#!/usr/bin/env python3
import argparse
import datetime
import json
import logging
import sys
import typing
import urllib.request

import oauth2client.service_account
import googleapiclient.discovery

SPREADSHEET_ID = '1rcYOxrr_bqkQWggCeP8W6eYkofl9_Zk0deHv62ilE8Y'
PLAN_URL_PAT_STR = r"^https://(?P<stack>dev.)?planscore.org/plan.html\?(?P<id>[\.\w]+)$"
INDEX_URL_FMT = "https://{bucket}.s3.amazonaws.com/uploads/{id}/index.json"
STACK_BUCKETS = {None: "planscore", "dev.": "planscore--dev"}

STATE_ABBREVS = {
    'Alabama': 'AL', 'Alaska': 'AK', 'Arizona': 'AZ', 'Arkansas': 'AR', 'California': 'CA',
    'Colorado': 'CO', 'Connecticut': 'CT', 'Delaware': 'DE', 'Florida': 'FL', 'Georgia': 'GA',
    'Hawaii': 'HI', 'Idaho': 'ID', 'Illinois': 'IL', 'Indiana': 'IN', 'Iowa': 'IA',
    'Kansas': 'KS', 'Kentucky': 'KY', 'Louisiana': 'LA', 'Maine': 'ME', 'Maryland': 'MD',
    'Massachusetts': 'MA', 'Michigan': 'MI', 'Minnesota': 'MN', 'Mississippi': 'MS',
    'Missouri': 'MO', 'Montana': 'MT', 'Nebraska': 'NE', 'Nevada': 'NV', 'New Hampshire': 'NH',
    'New Jersey': 'NJ', 'New Mexico': 'NM', 'New York': 'NY', 'North Carolina': 'NC',
    'North Dakota': 'ND', 'Ohio': 'OH', 'Oklahoma': 'OK', 'Oregon': 'OR', 'Pennsylvania': 'PA',
    'Rhode Island': 'RI', 'South Carolina': 'SC', 'South Dakota': 'SD', 'Tennessee': 'TN',
    'Texas': 'TX', 'Utah': 'UT', 'Vermont': 'VT', 'Virginia': 'VA', 'Washington': 'WA',
    'West Virginia': 'WV', 'Wisconsin': 'WI', 'Wyoming': 'WY'
}

logging.basicConfig(level=logging.DEBUG, stream=sys.stderr)

def load_google_service(credentials_file: str):
    """Load Google Sheets service"""
    scope = ['https://www.googleapis.com/auth/spreadsheets']
    credentials = oauth2client.service_account.ServiceAccountCredentials.from_json_keyfile_name(
        credentials_file, scope
    )
    return googleapiclient.discovery.build('sheets', 'v4', credentials=credentials)

def read_vote_swings_worksheet(service) -> dict:
    """Read the Vote Swings worksheet to understand its structure"""
    logging.debug("Reading Vote Swings worksheet structure...")

    try:
        result = service.spreadsheets().values().get(
            spreadsheetId=SPREADSHEET_ID,
            range='Vote Swings!A:Z'  # Read all columns
        ).execute()

        values = result.get('values', [])
        if values:
            logging.debug(f"Vote Swings has {len(values)} rows")
            logging.debug(f"Headers: {values[0] if values else 'None'}")
            if len(values) > 1:
                logging.debug(f"Sample row: {values[1]}")

        return {'headers': values[0] if values else [], 'sample_rows': values[1:3] if len(values) > 1 else []}
    except Exception as e:
        logging.debug(f"Could not read Vote Swings worksheet: {e}")
        return {'headers': [], 'sample_rows': []}

def load_states_from_google(service) -> dict:
    """Load states data from Google Sheets"""
    logging.debug("Loading States worksheet...")

    result = service.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID,
        range='States!A:M'
    ).execute()

    values = result.get('values', [])
    headers = values[0]

    states = {}
    for row_idx, row in enumerate(values[1:], start=2):
        row_padded = row + [''] * (len(headers) - len(row))
        state_data = dict(zip(headers, row_padded))
        state_name = state_data.get('State Name', '')
        abbrev = STATE_ABBREVS.get(state_name)

        if abbrev:
            state_data['_row_index'] = row_idx
            states[abbrev] = state_data

    logging.debug(f"Loaded {len(states)} states from Google Sheets")
    return states

def fetch_district_data(plan_url: str) -> list:
    """Fetch district-level predictions from a PlanScore URL"""
    import re

    plan_match = re.match(PLAN_URL_PAT_STR, plan_url)
    if not plan_match:
        logging.warning(f"Invalid plan URL: {plan_url}")
        return []

    plan_bucket = STACK_BUCKETS[plan_match.group("stack")]
    index_url = INDEX_URL_FMT.format(bucket=plan_bucket, id=plan_match.group("id"))

    try:
        logging.debug(f"Fetching plan data from: {index_url}")
        index_data = json.load(urllib.request.urlopen(index_url))

        districts = []
        for district in index_data.get("districts", []):
            totals = district.get("totals", {})

            # Get vote counts
            dem_votes = totals.get("Democratic Votes", 0)
            rep_votes = totals.get("Republican Votes", 0)
            dem_wins = totals.get("Democratic Wins", 0)

            districts.append({
                'dem_votes': dem_votes,
                'rep_votes': rep_votes,
                'dem_wins': dem_wins
            })

        logging.debug(f"Fetched {len(districts)} districts from plan")
        return districts

    except Exception as e:
        logging.error(f"Error fetching plan data: {e}")
        return []

def build_district_predictions(states: dict) -> list:
    """Build district prediction rows for all states"""
    all_rows = []

    # Get FIPS codes mapping (state name to FIPS)
    state_name_to_fips = {
        'Alabama': '01', 'Alaska': '02', 'Arizona': '04', 'Arkansas': '05', 'California': '06',
        'Colorado': '08', 'Connecticut': '09', 'Delaware': '10', 'Florida': '12', 'Georgia': '13',
        'Hawaii': '15', 'Idaho': '16', 'Illinois': '17', 'Indiana': '18', 'Iowa': '19',
        'Kansas': '20', 'Kentucky': '21', 'Louisiana': '22', 'Maine': '23', 'Maryland': '24',
        'Massachusetts': '25', 'Michigan': '26', 'Minnesota': '27', 'Mississippi': '28',
        'Missouri': '29', 'Montana': '30', 'Nebraska': '31', 'Nevada': '32', 'New Hampshire': '33',
        'New Jersey': '34', 'New Mexico': '35', 'New York': '36', 'North Carolina': '37',
        'North Dakota': '38', 'Ohio': '39', 'Oklahoma': '40', 'Oregon': '41', 'Pennsylvania': '42',
        'Rhode Island': '44', 'South Carolina': '45', 'South Dakota': '46', 'Tennessee': '47',
        'Texas': '48', 'Utah': '49', 'Vermont': '50', 'Virginia': '51', 'Washington': '53',
        'West Virginia': '54', 'Wisconsin': '55', 'Wyoming': '56'
    }

    for abbrev in sorted(states.keys()):
        state_data = states[abbrev]
        plan_url = state_data.get('PlanScore URL', '').strip()

        if not plan_url:
            logging.debug(f"Skipping {abbrev} - no PlanScore URL")
            continue

        state_name = state_data.get('State Name', '')
        fips_code = state_name_to_fips.get(state_name, '')

        logging.debug(f"Processing {abbrev} - {state_name}")
        districts = fetch_district_data(plan_url)

        for idx, district in enumerate(districts, start=1):
            all_rows.append({
                'state_name': state_name,
                'state_abbrev': abbrev,
                'fips_code': fips_code,
                'district': str(idx),
                'district_num': idx,
                'dem_votes': district['dem_votes'],
                'rep_votes': district['rep_votes'],
                'dem_wins': district['dem_wins']
            })

    logging.debug(f"Built {len(all_rows)} district prediction rows")
    return all_rows

def delete_worksheet_if_exists(service, worksheet_name: str):
    """Delete a worksheet if it exists"""
    try:
        # Get all sheets
        spreadsheet = service.spreadsheets().get(spreadsheetId=SPREADSHEET_ID).execute()

        for sheet in spreadsheet['sheets']:
            if sheet['properties']['title'] == worksheet_name:
                sheet_id = sheet['properties']['sheetId']
                logging.debug(f"Deleting existing worksheet: {worksheet_name} (ID: {sheet_id})")

                body = {
                    'requests': [{
                        'deleteSheet': {
                            'sheetId': sheet_id
                        }
                    }]
                }

                service.spreadsheets().batchUpdate(
                    spreadsheetId=SPREADSHEET_ID,
                    body=body
                ).execute()

                logging.debug(f"Successfully deleted worksheet: {worksheet_name}")
                return True

        logging.debug(f"Worksheet {worksheet_name} does not exist, nothing to delete")
        return False

    except Exception as e:
        logging.error(f"Error deleting worksheet: {e}")
        raise

def create_worksheet(service, worksheet_name: str, row_count: int, column_count: int):
    """Create a new worksheet with proper formatting"""
    logging.debug(f"Creating worksheet: {worksheet_name} ({row_count} rows, {column_count} columns)")

    body = {
        'requests': [{
            'addSheet': {
                'properties': {
                    'title': worksheet_name,
                    'gridProperties': {
                        'rowCount': row_count,
                        'columnCount': column_count,
                        'frozenRowCount': 1
                    }
                }
            }
        }]
    }

    try:
        result = service.spreadsheets().batchUpdate(
            spreadsheetId=SPREADSHEET_ID,
            body=body
        ).execute()

        sheet_id = result['replies'][0]['addSheet']['properties']['sheetId']
        logging.debug(f"Successfully created worksheet: {worksheet_name} (ID: {sheet_id})")

        # Apply bold Roboto font to header row
        format_body = {
            'requests': [{
                'repeatCell': {
                    'range': {
                        'sheetId': sheet_id,
                        'startRowIndex': 0,
                        'endRowIndex': 1
                    },
                    'cell': {
                        'userEnteredFormat': {
                            'textFormat': {
                                'fontFamily': 'Roboto',
                                'bold': True
                            }
                        }
                    },
                    'fields': 'userEnteredFormat.textFormat'
                }
            }]
        }

        service.spreadsheets().batchUpdate(
            spreadsheetId=SPREADSHEET_ID,
            body=format_body
        ).execute()

        logging.debug("Applied header formatting")

        # Apply number formatting to data columns
        # Columns E & F (indices 4, 5): Predicted Dem/Rep Votes - comma separated, no decimals
        # Column G (index 6): Predicted Dem Wins - three decimal places
        number_format_body = {
            'requests': [
                {
                    # Format columns E & F (vote counts) with commas, no decimals
                    'repeatCell': {
                        'range': {
                            'sheetId': sheet_id,
                            'startRowIndex': 1,  # Skip header
                            'startColumnIndex': 4,  # Column E
                            'endColumnIndex': 6  # Through column F
                        },
                        'cell': {
                            'userEnteredFormat': {
                                'numberFormat': {
                                    'type': 'NUMBER',
                                    'pattern': '#,##0;(#,##0)'
                                }
                            }
                        },
                        'fields': 'userEnteredFormat.numberFormat'
                    }
                },
                {
                    # Format column G (dem wins) with three decimal places
                    'repeatCell': {
                        'range': {
                            'sheetId': sheet_id,
                            'startRowIndex': 1,  # Skip header
                            'startColumnIndex': 6,  # Column G
                            'endColumnIndex': 7
                        },
                        'cell': {
                            'userEnteredFormat': {
                                'numberFormat': {
                                    'type': 'NUMBER',
                                    'pattern': '0.000'
                                }
                            }
                        },
                        'fields': 'userEnteredFormat.numberFormat'
                    }
                }
            ]
        }

        service.spreadsheets().batchUpdate(
            spreadsheetId=SPREADSHEET_ID,
            body=number_format_body
        ).execute()

        logging.debug("Applied number formatting to columns E, F, G")
        return True

    except Exception as e:
        logging.error(f"Error creating worksheet: {e}")
        raise

def write_predictions_worksheet(service, rows: list, vote_swings_structure: dict):
    """Write district predictions to Google Sheets"""
    logging.debug("Writing predictions to Google Sheets...")

    # Build headers matching Vote Swings: State Name, Postal Code, FIPS Code, District
    # Plus our 3 prediction columns
    headers = ['State Name', 'Postal Code', 'FIPS Code', 'District',
               'Predicted Dem Votes', 'Predicted Rep Votes', 'Predicted Dem Wins']

    output_rows = [headers]

    for row in rows:
        output_rows.append([
            row['state_name'],
            row['state_abbrev'],
            row['fips_code'],
            row['district'],
            row['dem_votes'],
            row['rep_votes'],
            row['dem_wins']
        ])

    # Create worksheet name with today's date: "Vote Swings YYYY-MM-DD"
    today = datetime.date.today()
    worksheet_name = f"Vote Swings {today.strftime('%Y-%m-%d')}"

    # Delete existing worksheet if it exists
    delete_worksheet_if_exists(service, worksheet_name)

    # Create the worksheet with exact dimensions and formatting
    # 436 rows (1 header + 435 districts), 7 columns (4 base + 3 predictions)
    create_worksheet(service, worksheet_name, row_count=436, column_count=7)

    # Write data to the worksheet
    range_name = f"{worksheet_name}!A1"

    body = {
        'values': output_rows
    }

    logging.debug(f"Writing {len(output_rows)} rows to {worksheet_name}")

    try:
        result = service.spreadsheets().values().update(
            spreadsheetId=SPREADSHEET_ID,
            range=range_name,
            valueInputOption='RAW',
            body=body
        ).execute()

        logging.debug(f"Successfully wrote {result.get('updatedCells', 0)} cells")
        logging.info(f"Data written to worksheet: {worksheet_name}")
    except Exception as e:
        logging.error(f"Error writing to Google Sheets: {e}")
        raise

def main(credentials_file: str):
    # Load Google Sheets service
    service = load_google_service(credentials_file)

    # Read Vote Swings worksheet structure
    vote_swings_structure = read_vote_swings_worksheet(service)

    # Load states data
    states = load_states_from_google(service)

    # Build district predictions
    rows = build_district_predictions(states)

    logging.info(f"Total districts: {len(rows)}")

    # Write to Google Sheets
    write_predictions_worksheet(service, rows, vote_swings_structure)

    logging.info("Done!")

parser = argparse.ArgumentParser()
parser.add_argument("credentials_file", help="Path to Google service account credentials JSON file")

if __name__ == "__main__":
    args = parser.parse_args()
    exit(main(args.credentials_file))
