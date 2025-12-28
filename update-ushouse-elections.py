#!/usr/bin/env python3
import argparse
import csv
import dataclasses
import datetime
import http.client
import json
import logging
import operator
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import typing
import urllib.parse
import urllib.request
import zipfile

import oauth2client.service_account
import googleapiclient.discovery

@dataclasses.dataclass
class Election:
    cycle: str
    stateabrev: str
    EG: float
    seats: int
    url: str
    districts: str

@dataclasses.dataclass
class District:
    dem_wins: float
    dem_share: float
    total_votes: int

@dataclasses.dataclass
class GdocsStates:
    states: dict
    service: typing.Any

UA = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/26.1 Safari/605.1.15'

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

def update_google_sheet_plan_url(gdocs: GdocsStates, state_abbrev: str, google_state: dict, new_plan_url: str):
    """Update the PlanScore URL in Google Sheets for a given state"""
    row_index = google_state['_row_index']

    # Column M is the PlanScore URL column (12th column, A=1, B=2, ... M=13)
    cell_range = f'States!M{row_index}'

    logging.debug(f"Updating Google Sheet {state_abbrev} at {cell_range} with URL: {new_plan_url}")

    body = {
        'values': [[new_plan_url]]
    }

    gdocs.service.spreadsheets().values().update(
        spreadsheetId=SPREADSHEET_ID,
        range=cell_range,
        valueInputOption='RAW',
        body=body
    ).execute()

    logging.debug(f"Successfully updated Google Sheet for {state_abbrev}")

def get_plan_details(plan_url) -> tuple[str, datetime.date]:
    """Get incumbents and score date from an existing PlanScore plan"""
    if not plan_url:
        return None, None

    if not (plan_match := PLAN_URL_PAT.match(plan_url)):
        return None, None

    plan_bucket = STACK_BUCKETS[plan_match.group("stack")]
    index_url = INDEX_URL_FMT.format(bucket=plan_bucket, id=plan_match.group("id"))

    try:
        index_data = json.load(urllib.request.urlopen(index_url))
        incumbents = ''.join(index_data.get("incumbents", []))
        start_datetime = datetime.date.fromtimestamp(index_data.get("start_time"))
        return incumbents, start_datetime
    except Exception:
        return None, None

def download_shapefile(url):
    """Download shapefile to a temporary location, filtering out ZZ districts if needed"""
    # Download original shapefile
    req = urllib.request.Request(url, headers={'User-Agent': UA})
    response = urllib.request.urlopen(req)
    original_zip = tempfile.NamedTemporaryFile(delete=False, suffix='.zip')
    original_zip.write(response.read())
    original_zip.close()

    try:
        # Use GDAL's /vsizip/ to read the shapefile directly from the zip
        vsizip_path = f"/vsizip/{original_zip.name}"

        # Use ogrinfo to list files in the zip and find the .shp file
        ogrinfo_list = subprocess.run(
            ['ogrinfo', vsizip_path],
            capture_output=True,
            text=True
        )

        # Parse the layer name from ogrinfo output
        # Format is like: "1: tl_2025_17_cd119 (Multi Polygon)"
        layer_name = None
        for line in ogrinfo_list.stdout.split('\n'):
            if ': ' in line and '(' in line:
                parts = line.split(': ', 1)
                if len(parts) > 1:
                    layer_name = parts[1].split(' (')[0]
                    break

        if not layer_name:
            logging.debug("Could not find layer in zip, using original")
            return original_zip.name

        shp_path = f"{vsizip_path}/{layer_name}.shp"

        # Use ogrinfo to check if CD119FP field exists
        ogrinfo_result = subprocess.run(
            ['ogrinfo', '-al', '-so', shp_path],
            capture_output=True,
            text=True
        )

        has_cd119fp = 'CD119FP' in ogrinfo_result.stdout

        if not has_cd119fp:
            logging.debug("No CD119FP field found, using original shapefile")
            return original_zip.name

        # Check if there are any ZZ districts
        ogrinfo_zz = subprocess.run(
            ['ogrinfo', '-al', shp_path, '-where', "CD119FP = 'ZZ'"],
            capture_output=True,
            text=True
        )

        has_zz_district = 'Feature Count:' in ogrinfo_zz.stdout and 'Feature Count: 0' not in ogrinfo_zz.stdout

        if not has_zz_district:
            logging.debug("No ZZ districts found, using original shapefile")
            return original_zip.name

        logging.debug("Found ZZ districts, filtering them out")

        # Create temp directory for filtered output
        filtered_dir = tempfile.mkdtemp()

        try:
            # Filter out CD119FP='ZZ' districts using ogr2ogr
            output_shp = os.path.join(filtered_dir, f"{layer_name}.shp")
            result = subprocess.run(
                [
                    'ogr2ogr',
                    '-f', 'ESRI Shapefile',
                    output_shp,
                    shp_path,
                    '-where', "CD119FP != 'ZZ'"
                ],
                capture_output=True,
                text=True
            )

            if result.returncode != 0:
                logging.debug(f"ogr2ogr filtering failed, using original: {result.stderr}")
                return original_zip.name

            # Create new zip with filtered shapefile
            filtered_zip = tempfile.NamedTemporaryFile(delete=False, suffix='.zip')
            filtered_zip.close()

            with zipfile.ZipFile(filtered_zip.name, 'w') as zip_ref:
                for root, dirs, files in os.walk(filtered_dir):
                    for file in files:
                        file_path = os.path.join(root, file)
                        arcname = os.path.relpath(file_path, filtered_dir)
                        zip_ref.write(file_path, arcname)

            # Clean up
            os.unlink(original_zip.name)
            logging.debug("Filtered shapefile created successfully")
            return filtered_zip.name

        finally:
            # Clean up temp directory
            shutil.rmtree(filtered_dir, ignore_errors=True)

    except Exception as e:
        logging.debug(f"Error processing shapefile: {e}, using original")
        return original_zip.name

def upload_new_plan(api_key, plan_name, auth_url, shapefile_url, incumbents):
    """Upload a new plan to PlanScore API"""
    logging.debug(f"Uploading new plan: {plan_name}")
    logging.debug(f"  Shapefile URL: {shapefile_url}")
    logging.debug(f"  Incumbents: {incumbents}")

    # Download the shapefile
    local_shapefile = download_shapefile(shapefile_url)
    shapefile_filename = shapefile_url.split('/')[-1]
    if not shapefile_filename.lower().endswith(".zip"):
        shapefile_filename += ".zip"

    try:
        # Step 1: Prepare upload
        api_base = "https://api.planscore.org"
        prepare_url = f"{api_base}/upload"

        prepare_request = urllib.request.Request(
            prepare_url,
            headers={"Authorization": f"Bearer {api_key}"}
        )
        prepare_response = urllib.request.urlopen(prepare_request)
        prepare_data = json.load(prepare_response)

        s3_url = prepare_data[0]
        s3_fields = prepare_data[1]

        logging.debug(f"S3 upload URL: {s3_url}")
        logging.debug(f"Upload key: {s3_fields['key']}")

        # Step 2: Upload file to S3
        # Read the file
        with open(local_shapefile, 'rb') as f:
            file_data = f.read()

        # Build multipart form data
        boundary = '----WebKitFormBoundary' + ''.join(str(id(None)) for _ in range(16))
        body = []

        # Add all the S3 fields
        for key, value in s3_fields.items():
            body.append(f'--{boundary}'.encode())
            body.append(f'Content-Disposition: form-data; name="{key}"'.encode())
            body.append(b'')
            body.append(str(value).encode())

        # Add the file
        body.append(f'--{boundary}'.encode())
        body.append(f'Content-Disposition: form-data; name="file"; filename="{shapefile_filename}"'.encode())
        body.append(b'Content-Type: application/zip')
        body.append(b'')
        body.append(file_data)
        body.append(f'--{boundary}--'.encode())

        body_bytes = b'\r\n'.join(body)

        # Parse S3 URL
        s3_parsed = urllib.parse.urlparse(s3_url)

        # Upload to S3
        conn = http.client.HTTPSConnection(s3_parsed.netloc)
        headers = {
            'Content-Type': f'multipart/form-data; boundary={boundary}',
            'Content-Length': str(len(body_bytes))
        }
        conn.request('POST', s3_parsed.path, body_bytes, headers)
        response = conn.getresponse()

        # Get redirect URL from Location header
        redirect_url = response.getheader('Location')
        conn.close()

        if not redirect_url:
            raise Exception("No redirect URL found in S3 response")

        logging.debug(f"File uploaded, redirect URL: {redirect_url}")

        # Step 3: Finalize upload with metadata
        incumbents_list = list(incumbents)
        metadata = {
            "description": plan_name,
            "incumbents": incumbents_list,
            "library_metadata": {
                "authoritative_link": auth_url,
                "shapefile_file": shapefile_url
            }
        }

        logging.debug("Metadata being sent:")
        logging.debug(f"  authoritative_link: {auth_url}")
        logging.debug(f"  shapefile_file: {shapefile_url}")
        logging.debug(f"  incumbents: {incumbents_list}")

        metadata_json = json.dumps(metadata).encode('utf-8')
        finalize_request = urllib.request.Request(
            redirect_url,
            data=metadata_json,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            }
        )
        finalize_response = urllib.request.urlopen(finalize_request)
        finalize_data = json.load(finalize_response)

        logging.debug("Upload complete!")
        logging.debug(f"Response: {json.dumps(finalize_data, indent=2)}")

        plan_url = finalize_data.get('plan_url')
        index_url = finalize_data.get('index_url')

        if plan_url and index_url:
            # Poll until status is true
            logging.debug("Waiting for plan to be scored...")
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

                # Check if status is False (failed)
                if status is False:
                    raise Exception(f"Plan upload failed! Status: False, message: {message}")

                # Check if status is True (complete)
                if status is True:
                    logging.debug("Plan scoring complete!")
                    break

        return plan_url

    finally:
        os.unlink(local_shapefile)

def row2election(api_key: str, gdocs: GdocsStates, row: dict) -> typing.Optional[Election]:
    """
    Process a 2026 election row, checking if it needs to be updated based on Google Sheet data.
    """
    stateabrev = row.get("stateabrev")
    plan_url = row.get("url")

    # Look up the state in Google Sheets by abbreviation
    google_state = gdocs.states.get(stateabrev)

    if not google_state:
        logging.debug(f"No Google state found for {stateabrev}, returning as-is")
        return planscore2election(plan_url, row) if plan_url else None

    # Check if we should skip this state
    has_redraw = google_state.get('2026 Redraw', '').strip().upper() == 'Y'
    filing_deadline_str = google_state.get('Filing Deadline', '').strip()

    filing_deadline_passed = False
    if filing_deadline_str:
        try:
            filing_deadline = datetime.datetime.strptime(filing_deadline_str, '%Y-%m-%d').date()
            today = datetime.datetime.now().date()
            filing_deadline_passed = today > filing_deadline
        except ValueError:
            logging.debug(f"Could not parse filing deadline: {filing_deadline_str}")

    # Decision logic

    # if not has_redraw:
    #     logging.debug(f"{google_state['State Name']} - no redraw and we don't care about filing deadline, skipping")
    #     return planscore2election(plan_url, row) if plan_url else None
    # if not has_redraw and not filing_deadline_passed:
    #     logging.debug(f"{google_state['State Name']} - no redraw and filing deadline not passed, skipping")
    #     return planscore2election(plan_url, row) if plan_url else None

    # Check if incumbents have changed
    current_incumbents, score_date = get_plan_details(google_state.get('PlanScore URL', ''))
    new_incumbents = google_state.get('Incumbents', '').strip()

    logging.debug(f"{google_state['State Name']} - checking incumbents and score date")
    logging.debug(f"  Deadline: {filing_deadline}")
    logging.debug(f"  Current:  {current_incumbents}")
    logging.debug(f"  New:      {new_incumbents}")

    if current_incumbents == new_incumbents and score_date > filing_deadline:
        logging.debug(f"{google_state['State Name']} - incumbents unchanged and {score_date} new enough, skipping")
        return planscore2election(plan_url, row) if plan_url else None
    elif current_incumbents == new_incumbents and not filing_deadline_passed:
        logging.debug(f"{google_state['State Name']} - incumbents unchanged and {score_date} filing deadline not passed, skipping")
        return planscore2election(plan_url, row) if plan_url else None

    # Incumbents have changed, need to upload new plan
    logging.debug(f"{google_state['State Name']} - incumbents changed or {score_date} too old, uploading new plan")
    logging.debug(f"  Plan Name: {google_state['Plan Name']}")
    logging.debug(f"  Authoritative URL: {google_state['Authoritative URL']}")
    logging.debug(f"  Shapefile URL: {google_state['Shapefile URL']}")
    new_plan_url = upload_new_plan(
        api_key,
        google_state['Plan Name'],
        google_state['Authoritative URL'],
        google_state['Shapefile URL'],
        new_incumbents
    )

    # Update Google Sheet with the new plan URL
    update_google_sheet_plan_url(gdocs, stateabrev, google_state, new_plan_url)

    # Update the row dict to use the new URL
    row = dict(row)
    row['url'] = new_plan_url

    # Process the new plan to get election data
    return planscore2election(new_plan_url, row)

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
    district_values = [(d.dem_wins, d.dem_share, round(d.total_votes)) for d in districts]
    efficiency_gap = (seat_share - .5) - 2 * (vote_share - .5)

    return Election(
        row.get("cycle"),
        row.get("stateabrev"),
        round(efficiency_gap, 3),
        row.get("seats"),
        row.get("url"),
        json.dumps(
            [list(map(lambda n: round(n, 3), v)) for v in district_values],
            separators=(',', ':'),
        ),
    )

def main(api_key: str, credentials_file: str, filename: str):
    # Load Google Sheets states data
    logging.debug("Loading Google Sheets states data...")
    gdocs = load_google_states(credentials_file)
    logging.debug(f"Loaded {len(gdocs.states)} states from Google Sheets")

    with open(filename, "r") as file1:
        rows = list(csv.DictReader(file1))

    logging.info(f"{rows[:3]}, {rows[-3:]}")

    elections = [
        Election(*(row.get(f) for f in ELECTION_FIELDS))
        for row in rows if row.get("cycle") != "2026"
    ]

    elections += [
        row2election(api_key, gdocs, row) or Election(*(row.get(f) for f in ELECTION_FIELDS))
        for row in rows if row.get("cycle") == "2026"
    ]

    logging.info(f"{elections[:3]}, {elections[-3:]}")

    with open(filename, "w") as file2:
        out = csv.DictWriter(file2, ELECTION_FIELDS)
        out.writeheader()
        for election in elections:
            out.writerow(dataclasses.asdict(election))

parser = argparse.ArgumentParser()
parser.add_argument("api_key")
parser.add_argument("credentials_file")
parser.add_argument("filename")

if __name__ == "__main__":
    args = parser.parse_args()
    exit(main(args.api_key, args.credentials_file, args.filename))