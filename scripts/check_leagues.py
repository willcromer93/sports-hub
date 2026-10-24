"""
Check what ESPN lists for each league: read-only, touches no database.

    venv/bin/python scripts/check_leagues.py              # all 7 leagues
    venv/bin/python scripts/check_leagues.py NBA WNBA     # just these

For each league it asks ESPN for the teams, runs the safety checks from
team_discovery.py (minimum count, no duplicate ids), and prints how many teams it
found against the expected number. This is the first gate before enabling a league:
if the count is wrong here, nothing downstream can be right. Exits 1 if any league
fails, so it can also be run from a script.
"""

import sys

from http_client import FetchError
from leagues import LEAGUES, parse_league_codes
from team_discovery import DiscoveryError, discover_teams


def main(argv):
    try:
        codes = parse_league_codes(",".join(argv)) or list(LEAGUES)
    except ValueError as exc:
        print(exc)
        return 2

    failures = 0
    print(f"{'league':7s} {'found':>6s} {'expected':>9s}  status")
    for code in codes:
        league = LEAGUES[code]
        try:
            teams = discover_teams(league)
        except (DiscoveryError, FetchError) as exc:
            failures += 1
            print(f"{code:7s} {'-':>6s} {league.expected_teams:9d}  FAILED: {exc}")
            continue
        note = "" if len(teams) == league.expected_teams else f"  (ESPN listed {league.expected_teams} when this was written)"
        print(f"{code:7s} {len(teams):6d} {league.expected_teams:9d}  ok{note}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
