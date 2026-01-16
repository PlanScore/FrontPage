#!/usr/bin/env python3
import argparse
import datetime
import json
import logging
import sys
import urllib.request

import oauth2client.service_account
import googleapiclient.discovery
import numpy as np
from scipy.special import expit
from scipy.optimize import root_scalar

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

def calculate_district_shifts(districts: list, target_diff: float) -> list:
    """
    Calculate per-district vote shifts needed to achieve a target nationwide vote share.

    Args:
        districts: List of district dicts with 'dem_votes' and 'rep_votes'
        target_share: Target nationwide Democratic vote share (e.g., 0.50 for 50%)

    Returns:
        List of shift values (in percentage points) for each district
    """
    # Extract arrays of votes
    ndv = np.array([d['dem_votes'] for d in districts])
    nrv = np.array([d['rep_votes'] for d in districts])

    target_share = ndv.sum() / (ndv.sum() + nrv.sum()) + target_diff
    turnout = ndv + nrv

    # Compute log-odds where turnout > 0
    log_odds = np.where(turnout > 0, np.log(ndv) - np.log(nrv), 0)

    # Find the shift value that achieves the target
    def objective(shift):
        return np.average(expit(log_odds + shift), weights=turnout) - target_share

    result = root_scalar(objective, bracket=[-1, 1], method='brentq')
    shift = result.root

    # Calculate per-district shifts as decimal values
    # Original vote share
    original_shares = np.where(turnout > 0, ndv / turnout, 0.5)
    # New vote share after shift
    new_shares = expit(log_odds + shift)
    # Difference as decimal (not percentage points)
    # e.g., 0.05 instead of 5.0 for a 5 percentage point shift
    shifts = (new_shares - original_shares)

    return shifts.tolist()

def load_google_service(credentials_file: str):
    """Load Google Sheets service"""
    scope = ['https://www.googleapis.com/auth/spreadsheets']
    credentials = oauth2client.service_account.ServiceAccountCredentials.from_json_keyfile_name(
        credentials_file, scope
    )
    return googleapiclient.discovery.build('sheets', 'v4', credentials=credentials)

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

        # Set column widths for shift columns (H-AF) to 54px
        width_body = {
            'requests': [{
                'updateDimensionProperties': {
                    'range': {
                        'sheetId': sheet_id,
                        'dimension': 'COLUMNS',
                        'startIndex': 7,  # Column H
                        'endIndex': 32  # Through column AF
                    },
                    'properties': {
                        'pixelSize': 54
                    },
                    'fields': 'pixelSize'
                }
            }]
        }

        service.spreadsheets().batchUpdate(
            spreadsheetId=SPREADSHEET_ID,
            body=width_body
        ).execute()

        logging.debug("Applied column widths to H-AF")

        # Apply number formatting to data columns
        # Columns E & F (indices 4, 5): Predicted Dem/Rep Votes - comma separated, no decimals
        # Column G (index 6): Predicted Dem Wins - three decimal places
        # Columns H-AF (indices 7-31): Shift columns - percentage with 2 decimal places
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
                },
                {
                    # Format columns H-AF (shift columns) as numbers with 3 decimal places
                    # Values are decimal fractions (e.g., 0.050 for 5% shift)
                    'repeatCell': {
                        'range': {
                            'sheetId': sheet_id,
                            'startRowIndex': 1,  # Skip header
                            'startColumnIndex': 7,  # Column H
                            'endColumnIndex': 32  # Through column AF
                        },
                        'cell': {
                            'userEnteredFormat': {
                                'numberFormat': {
                                    'type': 'NUMBER',
                                    'pattern': '0.0%'
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

        logging.debug("Applied number formatting to columns E, F, G, and H-AF")
        return True

    except Exception as e:
        logging.error(f"Error creating worksheet: {e}")
        raise

def write_predictions_worksheet(service, rows: list):
    """Write district predictions to Google Sheets"""
    logging.debug("Writing predictions to Google Sheets...")

    # Build headers for District Swings: State Name, Postal Code, FIPS Code, District
    # Plus our 3 prediction columns plus 25 shift columns
    shift_headers = ['R+12', 'R+11', 'R+10', 'R+9', 'R+8', 'R+7', 'R+6', 'R+5', 'R+4', 'R+3', 'R+2', 'R+1',
                     'Zero',
                     'D+1', 'D+2', 'D+3', 'D+4', 'D+5', 'D+6', 'D+7', 'D+8', 'D+9', 'D+10', 'D+11', 'D+12']
    headers = ['State Name', 'Postal Code', 'FIPS Code', 'District',
               'Predicted Dem Votes', 'Predicted Rep Votes', 'Predicted Dem Wins'] + shift_headers

    # Calculate all 25 shift columns
    # Target shares range from 38% (R+12) to 62% (D+12)
    # R+12 = 50% - 12% = 38%, ..., Zero = 50%, ..., D+12 = 50% + 12% = 62%
    logging.debug("Calculating logit shifts for 25 scenarios...")
    shift_columns = {}
    for i in range(-12, 13):  # -12 to +12 inclusive
        target_diff = (i / 100.0)  # Convert percentage points to decimal
        if i == 0:
            # Zero shift - all zeros
            shift_columns['Zero'] = [0.0] * len(rows)
        else:
            header = f'D+{i}' if i > 0 else f'R+{abs(i)}'
            shifts = calculate_district_shifts(rows, target_diff)
            shift_columns[header] = shifts
            logging.debug(f"Calculated shifts for {header} (target={target_diff:.1%})")

    output_rows = [headers]

    for idx, row in enumerate(rows):
        output_row = [
            row['state_name'],
            row['state_abbrev'],
            row['fips_code'],
            row['district'],
            row['dem_votes'],
            row['rep_votes'],
            row['dem_wins']
        ]
        # Add the 25 shift values for this district
        for shift_header in shift_headers:
            output_row.append(shift_columns[shift_header][idx])
        output_rows.append(output_row)

    # Create worksheet name with today's date: "District Swings YYYY-MM-DD"
    today = datetime.date.today()
    worksheet_name = f"District Swings {today.strftime('%Y-%m-%d')}"

    # Delete existing worksheet if it exists
    delete_worksheet_if_exists(service, worksheet_name)

    # Create the worksheet with exact dimensions and formatting
    # 436 rows (1 header + 435 districts), 32 columns (4 base + 3 predictions + 25 shifts)
    create_worksheet(service, worksheet_name, row_count=436, column_count=32)

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

    # Load states data
    states = load_states_from_google(service)

    # Build district predictions
    rows = build_district_predictions(states)

    logging.info(f"Total districts: {len(rows)}")

    # Write to Google Sheets
    write_predictions_worksheet(service, rows)

    logging.info("Done!")

parser = argparse.ArgumentParser()
parser.add_argument("credentials_file", help="Path to Google service account credentials JSON file")

if __name__ == "__main__":
    args = parser.parse_args()
    exit(main(args.credentials_file))
