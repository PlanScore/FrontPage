#!/usr/bin/env python3
import argparse
import concurrent.futures
import csv
import dataclasses
import json
import logging
import operator
import re
import sys
import typing
import urllib.request

import oauth2client.service_account
import googleapiclient.discovery

@dataclasses.dataclass
class Election:
    cycle: str
    stateabrev: str
    newplan: str
    EG: float
    seats: int
    url: str

@dataclasses.dataclass
class District:
    dem_wins: float
    dem_share: float
    total_votes: int

@dataclasses.dataclass
class GdocsStates:
    states: dict
    service: typing.Any

PLAN_URL_PAT = re.compile(r"^https://(?P<stack>dev.)?planscore.org/plan.html\?(?P<id>[\.\w]+)$")
INDEX_URL_FMT = "https://{bucket}.s3.amazonaws.com/uploads/{id}/index.json"
STACK_BUCKETS = {None: "planscore", "dev.": "planscore--dev"}
ELECTION_FIELDS = tuple(f.name for f in dataclasses.fields(Election))

SPREADSHEET_ID = '1rcYOxrr_bqkQWggCeP8W6eYkofl9_Zk0deHv62ilE8Y'

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

def load_google_states(credentials_file: str) -> GdocsStates:
    """Load states data from Google Sheets"""
    scope = ['https://www.googleapis.com/auth/spreadsheets']
    credentials = oauth2client.service_account.ServiceAccountCredentials.from_json_keyfile_name(
        credentials_file, scope
    )
    service = googleapiclient.discovery.build('sheets', 'v4', credentials=credentials)

    result = service.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID,
        range='States!A:M'
    ).execute()

    values = result.get('values', [])
    headers = values[0]

    states = {}
    for row_idx, row in enumerate(values[1:], start=2):  # start=2 because row 1 is headers
        row_padded = row + [''] * (len(headers) - len(row))
        state_data = dict(zip(headers, row_padded))
        state_name = state_data['State Name']
        # Store by abbreviation for easy lookup, also store row index for updates
        abbrev = STATE_ABBREVS.get(state_name)
        if abbrev:
            state_data['_row_index'] = row_idx
            states[abbrev] = state_data

    return GdocsStates(states, service)

def load_google_state_swings(service: typing.Any) -> dict:
    """Load most recent State Swings worksheet data"""
    # Get all sheets in the spreadsheet
    spreadsheet = service.spreadsheets().get(spreadsheetId=SPREADSHEET_ID).execute()
    sheets = spreadsheet.get('sheets', [])

    # Find all State Swings worksheets
    swings_sheets = []
    for sheet in sheets:
        title = sheet['properties']['title']
        if title.startswith('State Swings '):
            # Extract date from title like "State Swings 2026-01-17"
            date_str = title.replace('State Swings ', '')
            swings_sheets.append((date_str, title))

    if not swings_sheets:
        logging.debug("No State Swings worksheets found")
        return {}

    # Sort by date and get the most recent
    swings_sheets.sort(reverse=True)
    most_recent_date, most_recent_title = swings_sheets[0]
    logging.debug(f"Using State Swings worksheet: {most_recent_title}")

    # Load data from the most recent sheet - read wide range to get all columns
    result = service.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=f"'{most_recent_title}'!A:AZ"
    ).execute()

    values = result.get('values', [])
    if not values:
        return {}

    headers = values[0]

    # Build dict mapping state abbreviation -> dict of column names to URLs
    # Structure: {state_abbrev: {column_name: url}}
    state_swings = {}
    for row in values[1:]:
        row_padded = row + [''] * (len(headers) - len(row))
        state_data = dict(zip(headers, row_padded))
        state_name = state_data.get('State Name', '')

        # Convert state name to abbreviation
        abbrev = STATE_ABBREVS.get(state_name)
        if not abbrev:
            continue

        # Extract all PlanScore URL columns
        state_urls = {}
        for header, value in state_data.items():
            if 'PlanScore URL' in header and value and value.strip():
                state_urls[header] = value.strip()

        if state_urls:
            state_swings[abbrev] = state_urls
            logging.debug(f"  {abbrev}: {len(state_urls)} URLs found")

    return state_swings

def get_state_swings_column_name(cycle: str) -> typing.Optional[str]:
    """Convert cycle name to State Swings worksheet column name

    Examples:
        predict0 -> No-Swing PlanScore URL
        predict1D -> D+1 PlanScore URL
        predict12D -> D+12 PlanScore URL
        predict1R -> R+1 PlanScore URL
        predict12R -> R+12 PlanScore URL
    """
    if cycle == "predict0":
        return "No-Swing PlanScore URL"

    # Parse predictXD or predictXR format
    match = re.match(r'^predict(\d+)([DR])$', cycle)
    if not match:
        return None

    number = match.group(1)
    party = match.group(2)

    return f"{party}+{number} PlanScore URL"

def planscore2election(plan_url: str, row: dict) -> typing.Optional[Election]:
    """Process an existing plan URL to calculate election data"""
    if not (plan_match := PLAN_URL_PAT.match(plan_url)):
        raise ValueError(plan_url)

    logging.debug(f"Processing plan: {plan_url}")
    plan_bucket = STACK_BUCKETS[plan_match.group("stack")]
    index_url = INDEX_URL_FMT.format(bucket=plan_bucket, id=plan_match.group("id"))
    index_data = json.load(urllib.request.urlopen(index_url))

    districts = [
        District(
            t["Democratic Wins"],
            t["Democratic Votes"] / (t["Democratic Votes"] + t["Republican Votes"]),
            t.get("US President 2024 - DEM", t["US President 2020 - DEM"]) + t.get("US President 2024 - REP", t["US President 2020 - REP"]),
        )
        for t in map(operator.itemgetter("totals"), index_data["districts"])
    ]
    state_votes = sum(d.total_votes for d in districts)

    # vote share is turnout-weighted, seat share is not
    seat_share = sum(d.dem_wins * 1 / len(districts) for d in districts)
    vote_share = sum(d.dem_share * d.total_votes / state_votes for d in districts)
    efficiency_gap = (seat_share - .5) - 2 * (vote_share - .5)

    return Election(
        row.get("cycle"),
        row.get("stateabrev"),
        row.get("newplan"),
        round(efficiency_gap, 3),
        row.get("seats"),
        row.get("url"),
    )

def process_row(index: int, row: dict, gdocs: GdocsStates, state_swings: dict) -> tuple[int, Election]:
    """Process a single row and return (index, Election) tuple"""
    cycle = row.get("cycle")

    if cycle == "2026":
        # For 2026 rows, check if state has a redraw (column G)
        stateabrev = row.get("stateabrev")
        google_state = gdocs.states.get(stateabrev)

        if google_state:
            has_redraw = google_state.get('2026 Redraw', '').strip().upper() == 'Y'
            plan_url = google_state.get('PlanScore URL', '').strip()

            if has_redraw and plan_url:
                # State has a redraw and URL in Google Sheets, process the plan
                row = dict(row)
                row['url'] = plan_url
                election = planscore2election(plan_url, row)
                return (index, election)
            else:
                # No redraw or no URL, keep row as-is without URL
                return (index, Election(*(row.get(f) for f in ELECTION_FIELDS)))
        else:
            # No Google Sheets data for this state, keep row as-is
            return (index, Election(*(row.get(f) for f in ELECTION_FIELDS)))
    elif cycle and cycle.startswith("predict"):
        # For predict* rows, check State Swings worksheet
        stateabrev = row.get("stateabrev")
        column_name = get_state_swings_column_name(cycle)

        if column_name and stateabrev in state_swings:
            # Get the URL for this specific column/cycle
            plan_url = state_swings[stateabrev].get(column_name, '').strip()

            if plan_url:
                # State has a URL for this cycle in State Swings, process the plan
                row = dict(row)
                row['url'] = plan_url
                election = planscore2election(plan_url, row)
                return (index, election)
            else:
                # No URL for this cycle, keep row as-is
                return (index, Election(*(row.get(f) for f in ELECTION_FIELDS)))
        else:
            # State not in State Swings or invalid cycle name, keep row as-is
            return (index, Election(*(row.get(f) for f in ELECTION_FIELDS)))
    else:
        # Not a 2026 or predict cycle, keep row as-is
        return (index, Election(*(row.get(f) for f in ELECTION_FIELDS)))

def main(credentials_file: str, filename: str):
    # Load Google Sheets states data
    logging.debug("Loading Google Sheets states data...")
    gdocs = load_google_states(credentials_file)
    logging.debug(f"Loaded {len(gdocs.states)} states from Google Sheets")

    # Load State Swings data
    logging.debug("Loading State Swings data...")
    state_swings = load_google_state_swings(gdocs.service)
    logging.debug(f"Loaded {len(state_swings)} states from State Swings")

    with open(filename, "r") as file1:
        rows = list(csv.DictReader(file1))

    logging.info(f"{rows[:3]}, {rows[-3:]}")

    # Process all rows in parallel using ThreadPoolExecutor with 10 workers
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        # Submit all rows with their indices
        futures = [
            executor.submit(process_row, index, row, gdocs, state_swings)
            for index, row in enumerate(rows)
        ]

        # Collect results as they complete
        results = []
        for future in concurrent.futures.as_completed(futures):
            results.append(future.result())

    # Sort results by original index to maintain ordering
    results.sort(key=lambda x: x[0])

    # Extract just the Election objects
    elections = [election for index, election in results]

    logging.info(f"{elections[:3]}, {elections[-3:]}")

    with open(filename, "w") as file2:
        out = csv.DictWriter(file2, ELECTION_FIELDS)
        out.writeheader()
        for election in elections:
            out.writerow(dataclasses.asdict(election))

parser = argparse.ArgumentParser()
parser.add_argument("credentials_file")
parser.add_argument("filename")

if __name__ == "__main__":
    args = parser.parse_args()
    exit(main(args.credentials_file, args.filename))
