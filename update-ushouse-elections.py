#!/usr/bin/env python3
import argparse
import csv
import dataclasses
import json
import re
import operator
import urllib.request

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

PLAN_URL_PAT = re.compile(r"^https://(?P<stack>dev.)?planscore.org/plan.html\?(?P<id>[\.\w]+)$")
INDEX_URL_FMT = "https://{bucket}.s3.amazonaws.com/uploads/{id}/index.json"
STACK_BUCKETS = {None: "planscore", "dev.": "planscore--dev"}
ELECTION_FIELDS = tuple(f.name for f in dataclasses.fields(Election))

def row2election(row: dict) -> Election:
    """
    """
    plan_url = row.get("url")
    if not plan_url:
        return Election(*(row.get(f) for f in ELECTION_FIELDS))

    if not (plan_match := PLAN_URL_PAT.match(plan_url)):
        raise ValueError(plan_url)

    print(plan_url)
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

def main(filename):
    with open(filename, "r") as file1:
        rows = list(csv.DictReader(file1))

    print(rows[:3], rows[-3:])

    elections = [
        row2election(row) if row.get("cycle") == "2026" else Election(*(row.get(f) for f in ELECTION_FIELDS))
        for row in rows
    ]

    print(elections[:3], elections[-3:])

    with open(filename, "w") as file2:
        out = csv.DictWriter(file2, ELECTION_FIELDS)
        out.writeheader()
        for election in elections:
            out.writerow(dataclasses.asdict(election))

parser = argparse.ArgumentParser()
parser.add_argument("filename")

if __name__ == "__main__":
    args = parser.parse_args()
    exit(main(args.filename))