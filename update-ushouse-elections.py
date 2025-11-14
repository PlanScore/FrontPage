#!/usr/bin/env python3
import argparse
import collections
import csv
import json
import re
import operator
import sys
import urllib.request

Election = collections.namedtuple("Election", ("cycle", "stateabrev", "EG", "seats", "url", "districts"))
District = collections.namedtuple("District", ("dem_wins", "dem_share", "total_votes"))

PLAN_URL_PAT = re.compile(r"^https://(?P<stack>dev.)?planscore.org/plan.html\?(?P<id>[\.\w]+)$")
INDEX_URL_FMT = "https://{bucket}.s3.amazonaws.com/uploads/{id}/index.json"
STACK_BUCKETS = {None: "planscore", "dev.": "planscore--dev"}

def main(filename):
    with open(filename, "r") as file1:
        rows = list(csv.DictReader(file1))

    print(rows[:3], rows[-3:])
    
    elections = []

    for row in rows:
        plan_url = row.get("url")
        if not plan_url:
            elections.append(Election(*(row.get(f) for f in Election._fields)))
            continue
        
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
        district_weights = [d.total_votes / state_votes for d in districts]
        
        seat_share = sum(d.dem_wins * d.total_votes / state_votes for d in districts)
        vote_share = sum(d.dem_share * d.total_votes / state_votes for d in districts)
        district_values = [(d.dem_wins, d.dem_share, round(d.total_votes)) for d in districts]
        efficiency_gap = (seat_share - .5) - 2 * (vote_share - .5)
        
        elections.append(
            Election(
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
        )

    print(elections[:3], elections[-3:])

    with open(filename, "w") as file2:
        out = csv.DictWriter(file2, Election._fields)
        out.writeheader()
        for election in elections:
            out.writerow(election._asdict())

parser = argparse.ArgumentParser()
parser.add_argument("filename")

if __name__ == "__main__":
    args = parser.parse_args()
    exit(main(args.filename))