#!/usr/bin/env python3
import argparse
import concurrent.futures
import dataclasses
import datetime
import json
import logging
import re
import sys
import time
import urllib.request

import oauth2client.service_account
import googleapiclient.discovery
import numpy as np
from scipy.special import expit
from scipy.optimize import root_scalar

PARALLELISM = 10
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

# Shift headers (25 scenarios)
ZERO_HEADER = 'No-Swing'
SHIFT_HEADERS = ['R+12', 'R+11', 'R+10', 'R+9', 'R+8', 'R+7', 'R+6', 'R+5', 'R+4', 'R+3', 'R+2', 'R+1',
                 ZERO_HEADER, 'D+1', 'D+2', 'D+3', 'D+4', 'D+5', 'D+6', 'D+7', 'D+8', 'D+9', 'D+10', 'D+11', 'D+12']

@dataclasses.dataclass
class CloneTask:
    """Task for cloning or reusing a plan with vote swings"""
    api_key: str
    plan_id: str
    base_plan_url: str
    existing_url: str
    description: str
    vote_swings: list
    state_abbrev: str
    header: str

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

def find_latest_district_swings_sheet(service) -> str:
    """Find the most recent District Swings worksheet by date"""
    spreadsheet = service.spreadsheets().get(spreadsheetId=SPREADSHEET_ID).execute()

    district_swings_sheets = []
    for sheet in spreadsheet['sheets']:
        title = sheet['properties']['title']
        if title.startswith('District Swings '):
            # Extract date from "District Swings YYYY-MM-DD"
            try:
                date_str = title.replace('District Swings ', '')
                date_obj = datetime.datetime.strptime(date_str, '%Y-%m-%d').date()
                district_swings_sheets.append((date_obj, title))
            except ValueError:
                continue

    if not district_swings_sheets:
        raise Exception("No District Swings worksheet found")

    # Sort by date descending and return the most recent
    district_swings_sheets.sort(reverse=True)
    latest_sheet = district_swings_sheets[0][1]
    logging.debug(f"Found latest District Swings sheet: {latest_sheet}")
    return latest_sheet

def load_district_swings_from_google(service) -> dict:
    """Load district swings data from the most recent District Swings worksheet"""
    sheet_name = find_latest_district_swings_sheet(service)

    logging.debug(f"Loading {sheet_name}...")
    result = service.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=f'{sheet_name}!A:AF'
    ).execute()

    values = result.get('values', [])
    headers = values[0]

    # Columns H-AF are the shift columns (indices 7-31)
    # Headers are: R+12, R+11, ..., R+1, Zero, D+1, ..., D+11, D+12
    shift_headers = headers[7:32]  # 25 columns

    # Build mapping of state abbreviation to dict of scenario -> shifts
    state_swings = {}

    for row in values[1:]:
        if len(row) < 8:
            continue

        state_abbrev = row[1]  # Column B: Postal Code

        if state_abbrev not in state_swings:
            state_swings[state_abbrev] = {header: [] for header in shift_headers}

        # Extract shift values for this district (columns H-AF, indices 7-31)
        for i, header in enumerate(shift_headers):
            col_idx = 7 + i
            if col_idx < len(row) and row[col_idx]:
                try:
                    shift_value = float(row[col_idx])
                    state_swings[state_abbrev][header].append(shift_value)
                except (ValueError, TypeError):
                    state_swings[state_abbrev][header].append(0.0)
            else:
                state_swings[state_abbrev][header].append(0.0)

    logging.debug(f"Loaded district swings for {len(state_swings)} states")
    return state_swings

def find_latest_state_swings_sheet(service) -> str:
    """Find the most recent State Swings worksheet by date"""
    spreadsheet = service.spreadsheets().get(spreadsheetId=SPREADSHEET_ID).execute()

    state_swings_sheets = []
    for sheet in spreadsheet['sheets']:
        title = sheet['properties']['title']
        if title.startswith('State Swings '):
            # Extract date from "State Swings YYYY-MM-DD"
            try:
                date_str = title.replace('State Swings ', '')
                date_obj = datetime.datetime.strptime(date_str, '%Y-%m-%d').date()
                state_swings_sheets.append((date_obj, title))
            except ValueError:
                continue

    if not state_swings_sheets:
        raise Exception("No State Swings worksheet found")

    # Sort by date descending and return the most recent
    state_swings_sheets.sort(reverse=True)
    latest_sheet = state_swings_sheets[0][1]
    logging.debug(f"Found latest State Swings sheet: {latest_sheet}")
    return latest_sheet

def load_existing_state_plan_urls(service) -> dict:
    """Load existing plan URLs from the most recent State Swings worksheet for potential reuse"""
    sheet_name = find_latest_state_swings_sheet(service)

    logging.debug(f"Loading {sheet_name}...")
    result = service.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=f'{sheet_name}!A:AA'
    ).execute()

    values = result.get('values', [])
    headers = values[0]

    # Columns C-AA are the scenario columns (indices 2-26, 25 columns total)
    # Headers are: R+12 PlanScore URL, R+11 PlanScore URL, ..., D+11 PlanScore URL, D+12 PlanScore URL
    scenario_headers = headers[2:27]  # 25 columns

    # Build mapping of state abbreviation to dict of scenario -> URL
    state_plan_urls = {}

    for row in values[1:]:
        if len(row) < 3:
            continue

        state_name = row[0]  # Column A: State Name

        # Find state abbreviation from state name
        state_abbrev = None
        for name, abbrev in STATE_ABBREVS.items():
            if name == state_name:
                state_abbrev = abbrev
                break

        if not state_abbrev:
            continue

        if state_abbrev not in state_plan_urls:
            state_plan_urls[state_abbrev] = {}

        # Extract URLs for this state (columns C-Z, indices 2-25)
        for i, header in enumerate(scenario_headers):
            col_idx = 2 + i
            # Extract scenario name from header like "R+12 PlanScore URL"
            scenario_name = header.replace(' PlanScore URL', '')
            if col_idx < len(row) and row[col_idx]:
                state_plan_urls[state_abbrev][scenario_name] = row[col_idx]
            else:
                state_plan_urls[state_abbrev][scenario_name] = ""

    logging.debug(f"Loaded existing plan URLs for {len(state_plan_urls)} states")
    return state_plan_urls

def get_plan_data(plan_url: str) -> dict:
    """Get start_time and library_metadata from plan's index.json"""
    if not plan_url:
        return {'start_time': None, 'library_metadata': {}}

    plan_match = re.match(PLAN_URL_PAT_STR, plan_url)
    if not plan_match:
        return {'start_time': None, 'library_metadata': {}}

    plan_bucket = STACK_BUCKETS[plan_match.group("stack")]
    index_url = INDEX_URL_FMT.format(bucket=plan_bucket, id=plan_match.group("id"))

    try:
        index_data = json.load(urllib.request.urlopen(index_url))
        start_time = datetime.date.fromtimestamp(index_data.get("start_time")) if index_data.get("start_time") else None
        library_metadata = index_data.get("library_metadata", {})
        return {'start_time': start_time, 'library_metadata': library_metadata}
    except Exception:
        return {'start_time': None, 'library_metadata': {}}

def clone_plan_with_swings(api_key: str, plan_id: str, description: str, vote_swings: list, base_library_metadata: dict = None) -> str:
    """Clone a plan with vote swings via PlanScore API (or dummy mode if no api_key)"""
    if not api_key:
        # Dummy mode
        return "http://example.com/plan.html?dummy"

    api_base = "https://api.planscore.org"
    clone_url = f"{api_base}/clone"

    # Merge base library_metadata with new notes field
    library_metadata = base_library_metadata.copy() if base_library_metadata else {}
    library_metadata["notes"] = f"""
        This {description} plan is part of a simulated, hypothetical national vote swing using
        <a href="https://www.cambridge.org/core/journals/political-analysis/article/abs/recalibration-of-predicted-probabilities-using-the-logit-shift-why-does-it-work-and-when-can-it-be-expected-to-work-well/67B3C222EB34BBA376AD730F34038CA4">logit shifts for each district</a>.
    """

    payload = {
        "id": plan_id,
        "description": description,
        "vote_swings": [round(s, 3) for s in vote_swings],
        "library_metadata": library_metadata,
    }

    # Log statistics about the vote swings being sent
    if vote_swings:
        non_zero_count = sum(1 for v in vote_swings if abs(v) > 0.0001)
        avg_swing = sum(vote_swings) / len(vote_swings)
        max_swing = max(vote_swings)
        min_swing = min(vote_swings)
        logging.debug(f"Cloning plan: {description} (ID: {plan_id}) with {len(vote_swings)} vote swings")
        logging.debug(f"  Vote swing stats: {non_zero_count}/{len(vote_swings)} non-zero, avg={avg_swing:.4f}, range=[{min_swing:.4f}, {max_swing:.4f}]")
    else:
        logging.debug(f"Cloning plan: {description} (ID: {plan_id}) with {len(vote_swings)} vote swings")

    payload_json = json.dumps(payload).encode('utf-8')
    clone_request = urllib.request.Request(
        clone_url,
        data=payload_json,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
    )

    try:
        clone_response = urllib.request.urlopen(clone_request)
        clone_data = json.load(clone_response)

        plan_url = clone_data.get('plan_url')
        index_url = clone_data.get('index_url')

        if not plan_url or not index_url:
            raise Exception(f"Invalid clone response: {clone_data}")

        # Poll until complete
        logging.debug(f"Waiting for plan to be scored... {plan_url}")
        poll_count = 0
        while True:
            time.sleep(10)
            poll_count += 1

            index_response = urllib.request.urlopen(index_url)
            index_data = json.load(index_response)
            status = index_data.get('status')
            message = index_data.get('message', '')

            if message:
                logging.debug(f"Polling ({poll_count})... status: {status}, message: {message}")
            else:
                logging.debug(f"Polling ({poll_count})... status: {status}")

            if status is False:
                raise Exception(f"Plan clone failed! Status: False, message: {message}")

            if status is True:
                logging.debug(f"Plan scoring complete: {plan_url}")
                break

        return plan_url

    except Exception as e:
        logging.error(f"Error cloning plan {description}: {e}")
        raise

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

def clone_or_reuse_plan(api_key: str, plan_id: str, base_plan_url: str, existing_url: str, description: str, vote_swings: list, state_abbrev: str, header: str) -> str:
    """Clone a plan or reuse existing if it's new enough. Fetches plan data inside parallel task."""
    # Get base plan data (start_time and library_metadata)
    base_data = get_plan_data(base_plan_url)
    base_plan_date = base_data['start_time']
    base_library_metadata = base_data['library_metadata']

    logging.debug(f"{state_abbrev} {header} - base plan date: {base_plan_date}")

    # Check if we can reuse existing cloned plan
    if existing_url:
        existing_data = get_plan_data(existing_url)
        existing_date = existing_data['start_time']

        if existing_date and base_plan_date and existing_date >= base_plan_date:
            logging.debug(f"Reusing {state_abbrev} {header}: {existing_date} >= {base_plan_date}")
            return existing_url
        else:
            logging.debug(f"Re-cloning {state_abbrev} {header}: base plan is newer")

    # Clone the plan with merged metadata
    return clone_plan_with_swings(api_key, plan_id, description, vote_swings, base_library_metadata)

def build_state_swings(service, states: dict, district_swings: dict, api_key: str, existing_plan_urls: dict = {}) -> list:
    """Build state swings by cloning plans with vote swings, using parallelism. Reuses existing plan URLs if they're new enough."""
    logging.debug("Building state swings with cloned plans...")

    # Prepare all clone tasks
    clone_tasks = []
    state_rows = []

    for abbrev in sorted(states.keys()):
        state_data = states[abbrev]
        plan_url = state_data.get('PlanScore URL', '').strip()

        if not plan_url:
            logging.debug(f"Skipping {abbrev} - no PlanScore URL")
            continue

        state_name = state_data.get('State Name', '')
        plan_name = state_data.get('Plan Name', '')

        # Extract plan ID from URL
        plan_match = re.match(PLAN_URL_PAT_STR, plan_url)
        if not plan_match:
            logging.warning(f"Invalid plan URL for {abbrev}: {plan_url}")
            continue

        plan_id = plan_match.group("id")

        # Get district swings for this state
        state_swings = district_swings.get(abbrev)
        if not state_swings:
            logging.warning(f"No district swings found for {abbrev}")
            continue

        # Build row with state info
        row = {
            'state_name': state_name,
            'plan_name': plan_name,
            'plan_urls': {}
        }

        # Create clone task for each scenario
        for header in SHIFT_HEADERS:
            vote_swings = state_swings.get(header, [])
            if not vote_swings:
                logging.warning(f"No vote swings for {abbrev} {header}")
                continue

            # Get existing URL if available
            existing_url = existing_plan_urls.get(abbrev, {}).get(header, '').strip()

            # Format description like "R+12 Illinois 119th Congress Districts"
            description = f"{header} {plan_name}"

            clone_tasks.append(CloneTask(
                api_key=api_key,
                plan_id=plan_id,
                base_plan_url=plan_url,
                existing_url=existing_url,
                description=description,
                vote_swings=vote_swings,
                state_abbrev=abbrev,
                header=header
            ))

        state_rows.append(row)

    logging.debug(f"Prepared {len(clone_tasks)} clone tasks for {len(state_rows)} states")

    # Execute clones in parallel with max PARALLELISM workers
    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=PARALLELISM) as executor:
        future_to_task = {
            executor.submit(
                clone_or_reuse_plan,
                task.api_key,
                task.plan_id,
                task.base_plan_url,
                task.existing_url,
                task.description,
                task.vote_swings,
                task.state_abbrev,
                task.header
            ): task
            for task in clone_tasks
        }

        for future in concurrent.futures.as_completed(future_to_task):
            task = future_to_task[future]
            try:
                plan_url = future.result()
                key = (task.state_abbrev, task.header)
                results[key] = plan_url
                logging.debug(f"Completed: {task.description} -> {plan_url}")
            except Exception as e:
                logging.error(f"Failed: {task.description} - {e}")
                key = (task.state_abbrev, task.header)
                results[key] = ""

    # Fill in the URLs for each state row from parallel execution results
    for row in state_rows:
        state_name = row['state_name']
        # Find the state abbreviation
        abbrev = None
        for ab, st in states.items():
            if st.get('State Name') == state_name:
                abbrev = ab
                break

        if abbrev:
            for header in SHIFT_HEADERS:
                key = (abbrev, header)
                row['plan_urls'][header] = results.get(key, "")

    logging.debug(f"Built state swings for {len(state_rows)} states")
    return state_rows

def write_state_swings_worksheet(service, rows: list):
    """Write state swings to Google Sheets"""
    logging.debug("Writing state swings to Google Sheets...")

    # Build headers: State Name, Plan Name, then 24 shift scenarios
    headers = ['State Name', 'Plan Name'] + [f'{h} PlanScore URL' for h in SHIFT_HEADERS]

    # Build output rows
    output_rows = [headers]

    for row in rows:
        output_row = [
            row['state_name'],
            row['plan_name']
        ]
        # Add the 24 plan URLs
        for shift_header in SHIFT_HEADERS:
            output_row.append(row['plan_urls'].get(shift_header, ''))
        output_rows.append(output_row)

    # Create worksheet name with today's date: "State Swings YYYY-MM-DD"
    today = datetime.date.today()
    worksheet_name = f"State Swings {today.strftime('%Y-%m-%d')}"

    # Delete existing worksheet if it exists
    delete_worksheet_if_exists(service, worksheet_name)

    # Create the worksheet with exact dimensions
    # 51 rows (1 header + 50 states), 26 columns (2 base + 24 scenarios)
    logging.debug(f"Creating worksheet: {worksheet_name} (51 rows, 26 columns)")

    body = {
        'requests': [{
            'addSheet': {
                'properties': {
                    'title': worksheet_name,
                    'gridProperties': {
                        'rowCount': 51,
                        'columnCount': 27,
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

        # Set column widths: A=100px, B=302px, C-AA=138px
        width_body = {
            'requests': [
                {
                    # Column A: 100px
                    'updateDimensionProperties': {
                        'range': {
                            'sheetId': sheet_id,
                            'dimension': 'COLUMNS',
                            'startIndex': 0,
                            'endIndex': 1
                        },
                        'properties': {
                            'pixelSize': 100
                        },
                        'fields': 'pixelSize'
                    }
                },
                {
                    # Column B: 302px
                    'updateDimensionProperties': {
                        'range': {
                            'sheetId': sheet_id,
                            'dimension': 'COLUMNS',
                            'startIndex': 1,
                            'endIndex': 2
                        },
                        'properties': {
                            'pixelSize': 302
                        },
                        'fields': 'pixelSize'
                    }
                },
                {
                    # Columns C-AA: 138px, center-aligned
                    'updateDimensionProperties': {
                        'range': {
                            'sheetId': sheet_id,
                            'dimension': 'COLUMNS',
                            'startIndex': 2,
                            'endIndex': 27
                        },
                        'properties': {
                            'pixelSize': 138
                        },
                        'fields': 'pixelSize'
                    }
                },
                {
                    # Center-align columns C-AA
                    'repeatCell': {
                        'range': {
                            'sheetId': sheet_id,
                            'startColumnIndex': 2,
                            'endColumnIndex': 27
                        },
                        'cell': {
                            'userEnteredFormat': {
                                'horizontalAlignment': 'CENTER'
                            }
                        },
                        'fields': 'userEnteredFormat.horizontalAlignment'
                    }
                }
            ]
        }

        service.spreadsheets().batchUpdate(
            spreadsheetId=SPREADSHEET_ID,
            body=width_body
        ).execute()

        logging.debug("Applied column widths: A=100px, B=302px, C-AA=138px (center-aligned)")

        # Write data to the worksheet
        range_name = f"{worksheet_name}!A1"

        body = {
            'values': output_rows
        }

        logging.debug(f"Writing {len(output_rows)} rows to {worksheet_name}")

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

def calculate_all_district_shifts(rows: list) -> dict:
    """
    Calculate district-level vote shifts for all 24 scenarios (excluding Zero).

    Returns:
        dict: {state_abbrev: {scenario: [shifts per district]}}
    """
    logging.debug("Calculating logit shifts for 24 scenarios...")

    # Calculate shifts for all districts (flat list indexed by district)
    all_shifts = {}
    for i in range(-12, 13):  # -12 to +12 inclusive
        target_diff = (i / 100.0)  # Convert percentage points to decimal
        header = ZERO_HEADER if i == 0 else f'D+{i}' if i > 0 else f'R+{abs(i)}'
        shifts = calculate_district_shifts(rows, target_diff)
        all_shifts[header] = shifts
        logging.debug(f"Calculated shifts for {header} (target={target_diff:.1%})")

    # Organize by state
    state_shifts = {}
    for idx, row in enumerate(rows):
        state_abbrev = row['state_abbrev']
        if state_abbrev not in state_shifts:
            state_shifts[state_abbrev] = {header: [] for header in SHIFT_HEADERS}

        for header in SHIFT_HEADERS:
            state_shifts[state_abbrev][header].append(all_shifts[header][idx])

    logging.debug(f"Calculated district shifts for {len(state_shifts)} states")
    return state_shifts

def write_predictions_worksheet(service, rows: list, shift_data: dict):
    """Write district predictions to Google Sheets using pre-calculated shift data"""
    logging.debug("Writing predictions to Google Sheets...")

    # Build headers for District Swings: State Name, Postal Code, FIPS Code, District
    # Plus our 3 prediction columns plus 25 shift columns
    headers = ['State Name', 'Postal Code', 'FIPS Code', 'District',
               'Predicted Dem Votes', 'Predicted Rep Votes', 'Predicted Dem Wins'] + SHIFT_HEADERS

    # Build shift_columns from pre-calculated shift_data
    # shift_data is {state_abbrev: {scenario: [shifts per district]}}
    # We need to flatten it to match the order of rows
    shift_columns = {}
    for header in SHIFT_HEADERS:
        if header == ZERO_HEADER:
            shift_columns[ZERO_HEADER] = [0.0] * len(rows)
        else:
            shift_columns[header] = []

    for row in rows:
        state_abbrev = row['state_abbrev']
        state_data = shift_data.get(state_abbrev, {})
        for header in SHIFT_HEADERS:
            if header != ZERO_HEADER:
                # Get the next shift value for this district in this state
                state_shifts = state_data.get(header, [])
                # Find which district index this is within the state
                district_idx = len([r for r in rows[:rows.index(row)] if r['state_abbrev'] == state_abbrev])
                if district_idx < len(state_shifts):
                    shift_columns[header].append(state_shifts[district_idx])
                else:
                    shift_columns[header].append(0.0)

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
        for shift_header in SHIFT_HEADERS:
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

def main(api_key: str, credentials_file: str):
    # Load Google Sheets service
    service = load_google_service(credentials_file)

    # Load states data
    states = load_states_from_google(service)

    # Build district predictions
    rows = build_district_predictions(states)
    logging.info(f"Total districts: {len(rows)}")

    # Calculate district shifts for all scenarios
    logging.info("Calculating district shifts for all scenarios...")
    district_swings = calculate_all_district_shifts(rows)

    # Try to load existing plan URLs for reuse
    try:
        existing_plan_urls = load_existing_state_plan_urls(service)
        logging.info("Loaded existing plan URLs for potential reuse")
    except Exception as e:
        logging.info(f"No existing State Swings worksheet found (first run): {e}")
        existing_plan_urls = {}

    # Build and write State Swings worksheet
    logging.info("Building State Swings worksheet...")
    state_rows = build_state_swings(service, states, district_swings, api_key, existing_plan_urls)
    write_state_swings_worksheet(service, state_rows)

    # Write District Swings worksheet
    write_predictions_worksheet(service, rows, district_swings)

    logging.info("Done!")

parser = argparse.ArgumentParser()
parser.add_argument("api_key", help="PlanScore API key (empty string for dummy mode)")
parser.add_argument("credentials_file", help="Path to Google service account credentials JSON file")

if __name__ == "__main__":
    args = parser.parse_args()
    exit(main(args.api_key, args.credentials_file))
