"""
The league gate: is a league's data good enough to switch on for real?

    venv/bin/python scripts/league_gate.py NBA                # judge NBA in the database .env points at
    DB_NAME=sports_hub_staging venv/bin/python scripts/league_gate.py NBA

Run it against the STAGING database after a trial run with the league enabled
(LEAGUES_ALL=NBA), and only add the league to LEAGUES_ALL on the live server once
every line says PASS (or a REVIEW you have looked at). It is read-only: it reads
the database and asks ESPN for the team count, and changes nothing.

Each check returns a status, and the tool exits 1 if any check FAILs:
    PASS    the data is as it should be
    FAIL    something is wrong; do not enable the league yet
    REVIEW  needs a human look (it prints what to look at)
"""

import json
import re
import sys
from datetime import timedelta
from pathlib import Path
from typing import NamedTuple

from db import NON_ADDITIVE_STAT_PATTERN, get_connection
from leagues import FEATURED_TEAMS, LEAGUES, parse_league_codes
from log_setup import LOG_DIR
from sanity_checks import ACKNOWLEDGED_PERIOD_MISMATCHES, check_featured_teams
from team_discovery import discover_teams

MIN_COVERAGE = 0.99  # box scores and period scores must exist/add up for 99%+ of games
MAX_EXAMPLES = 5
# Kept-as-additive stat names that look like rates, for the human review of stat names
LOOKS_LIKE_A_RATE = re.compile(r"(?i)(pct|percent|avg|average|rate|ratio|era\b|whip|ops\b|obp|slg|per|/)")


class Result(NamedTuple):
    name: str
    status: str  # PASS | FAIL | REVIEW
    detail: str


def _fetch(conn, sql, params=None):
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def _pct(part, whole):
    return 100.0 * part / whole if whole else 100.0


def gate_team_count(conn, league, espn_count):
    (have,) = _fetch(conn, "SELECT count(*) FROM teams WHERE is_tracked AND league = %s;", (league.code,))[0]
    if have == espn_count:
        return Result("Team count", "PASS", f"{have} tracked teams, ESPN lists {espn_count}")
    return Result("Team count", "FAIL", f"{have} tracked teams but ESPN lists {espn_count}")


def gate_rosters(conn, league):
    rows = _fetch(
        conn,
        """
        SELECT t.name, count(p.player_id) FILTER (
                   WHERE p.last_seen_at IS NOT NULL AND p.departed_at IS NULL)
        FROM teams t LEFT JOIN players p ON p.team_id = t.team_id
        WHERE t.is_tracked AND t.league = %s
        GROUP BY t.team_id, t.name
        HAVING count(p.player_id) FILTER (
                   WHERE p.last_seen_at IS NOT NULL AND p.departed_at IS NULL) < %s
        ORDER BY 2, 1;
        """,
        (league.code, league.min_roster),
    )
    if not rows:
        return Result("Rosters", "PASS", f"every team has at least {league.min_roster} players on its roster")
    shown = "; ".join(f"{name} ({n})" for name, n in rows[:MAX_EXAMPLES])
    return Result("Rosters", "FAIL", f"{len(rows)} team(s) under {league.min_roster} players: {shown}")


def gate_box_scores(conn, league):
    """Every tracked side of every final game should have a box score."""
    ((total, missing),) = _fetch(
        conn,
        """
        SELECT count(*), count(*) FILTER (WHERE NOT EXISTS (
                   SELECT 1 FROM player_game_appearances a
                   WHERE a.game_id = g.game_id AND a.team_id = t.team_id))
        FROM games g
        JOIN teams t ON t.is_tracked AND t.league = %s AND t.team_id IN (g.home_team_id, g.away_team_id)
        WHERE g.league = %s AND g.status = 'final';
        """,
        (league.code, league.code),
    )
    coverage = _pct(total - missing, total)
    detail = f"{total - missing} of {total} tracked sides have a box score ({coverage:.1f}%)"
    if total == 0:
        return Result("Box scores", "REVIEW", "no final games yet, so there is nothing to check")
    return Result("Box scores", "PASS" if coverage >= 100 * MIN_COVERAGE else "FAIL", detail)


def gate_period_scores(conn, league):
    """Final games should have period scores, and they should add up to the final score."""
    ((finals, with_periods, mismatched),) = _fetch(
        conn,
        """
        SELECT count(*), count(p.game_id),
               count(*) FILTER (WHERE p.game_id IS NOT NULL
                                  AND (g.home_score <> p.h OR g.away_score <> p.a))
        FROM games g
        LEFT JOIN (SELECT game_id, sum(home_score) AS h, sum(away_score) AS a
                   FROM game_periods GROUP BY game_id) p USING (game_id)
        WHERE g.league = %s AND g.status = 'final';
        """,
        (league.code,),
    )
    if finals == 0:
        return Result("Period scores", "REVIEW", "no final games yet, so there is nothing to check")
    acknowledged = len(
        [
            1
            for (lg, _eid) in ACKNOWLEDGED_PERIOD_MISMATCHES
            if lg == league.code
        ]
    )
    real_mismatches = max(0, mismatched - acknowledged)
    have = _pct(with_periods, finals)
    right = _pct(with_periods - real_mismatches, with_periods)
    ok = have >= 100 * MIN_COVERAGE and right >= 100 * MIN_COVERAGE
    detail = (
        f"{with_periods} of {finals} final games have periods ({have:.1f}%); "
        f"{with_periods - real_mismatches} of {with_periods} add up to the score ({right:.1f}%"
        f"{', ' + str(acknowledged) + ' acknowledged ESPN error(s) excluded' if acknowledged else ''})"
    )
    return Result("Period scores", "PASS" if ok else "FAIL", detail)


def gate_rollups(conn, league):
    """Independent check: re-add the box-score stats a different way and compare with
    player_season_stats, per stat and season type."""
    rows = _fetch(
        conn,
        r"""
        WITH direct AS (
            SELECT s.stat_name, g.season_type, sum(s.stat_value) AS total
            FROM player_game_stats s
            JOIN games g ON g.game_id = s.game_id
            JOIN player_game_appearances a ON a.game_id = s.game_id AND a.player_id = s.player_id
            JOIN teams t ON t.team_id = a.team_id AND t.is_tracked
            WHERE g.league = %s
              AND regexp_replace(s.stat_name, '^.*\.', '') !~ %s
            GROUP BY 1, 2),
        rolled AS (
            SELECT r.stat_name, r.season_type, sum(r.total_value) AS total
            FROM player_season_stats r JOIN teams t ON t.team_id = r.team_id
            WHERE t.league = %s
            GROUP BY 1, 2)
        SELECT coalesce(d.stat_name, r.stat_name), coalesce(d.season_type, r.season_type), d.total, r.total
        FROM direct d FULL JOIN rolled r USING (stat_name, season_type)
        WHERE d.total IS DISTINCT FROM r.total
        ORDER BY 1, 2;
        """,
        (league.code, NON_ADDITIVE_STAT_PATTERN, league.code),
    )
    if not rows:
        return Result("Rollup totals", "PASS", "every season total matches an independent re-addition of the box scores")
    shown = "; ".join(f"{name}/{stype}: direct {d} vs rollup {r}" for name, stype, d, r in rows[:MAX_EXAMPLES])
    return Result("Rollup totals", "FAIL", f"{len(rows)} stat total(s) differ: {shown}")


def suspicious_stat_names(names):
    """Stat names that are being SUMMED in the rollups but look like rates
    (percentages, averages, ERA, OPS...). Summing a rate gives nonsense."""
    return sorted(
        name
        for name in names
        if not re.search(NON_ADDITIVE_STAT_PATTERN, re.sub(r"^.*\.", "", name))
        and LOOKS_LIKE_A_RATE.search(re.sub(r"^.*\.", "", name))
    )


def review_stat_names(conn, league):
    names = [
        row[0]
        for row in _fetch(
            conn,
            """
            SELECT DISTINCT s.stat_name
            FROM player_game_stats s JOIN games g ON g.game_id = s.game_id
            WHERE g.league = %s;
            """,
            (league.code,),
        )
    ]
    if not names:
        return Result("Stat names", "REVIEW", "no stats yet, so there is nothing to review")
    bad = suspicious_stat_names(names)
    if bad:
        shown = ", ".join(bad[:15]) + (f", and {len(bad) - 15} more" if len(bad) > 15 else "")
        return Result(
            "Stat names",
            "REVIEW",
            f"{len(bad)} of {len(names)} names are summed but look like rates: {shown}. "
            f"Add them to NON_ADDITIVE_STAT_PATTERN in db.py if they are rates.",
        )
    return Result("Stat names", "PASS", f"{len(names)} stat names; none that are summed look like rates")


def gate_last_run(path, budget_minutes):
    """The most recent nightly run: ok, no warnings, no sanity problems, within budget."""
    try:
        run = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return Result("Last run", "REVIEW", f"no readable result file at {path}; run the pipeline first")
    problems = []
    if run.get("status") != "ok":
        problems.append(f"status {run.get('status')}")
    if run.get("errors"):
        problems.append(f"{len(run['errors'])} error(s)")
    if run.get("warnings"):
        problems.append(f"{len(run['warnings'])} warning(s)")
    if run.get("counts", {}).get("sanity problems"):
        problems.append(f"{run['counts']['sanity problems']} sanity problem(s)")
    seconds = run.get("duration_seconds", 0)
    if timedelta(seconds=seconds) > timedelta(minutes=budget_minutes):
        problems.append(f"took {seconds / 60:.0f} min, budget is {budget_minutes} min")
    detail = f"{run.get('started', '?')}: {run.get('status')} in {seconds} s"
    if problems:
        return Result("Last run", "FAIL", detail + " | " + ", ".join(problems))
    return Result("Last run", "PASS", detail + " | no errors, warnings or sanity problems, within budget")


def gate_featured(conn):
    problems = check_featured_teams(conn, {(t.league, t.espn_id) for t in FEATURED_TEAMS})
    if problems:
        return Result("Featured teams", "FAIL", "; ".join(problems))
    return Result("Featured teams", "PASS", "exactly the four dashboard teams, unchanged")


def run_gate(conn, league, espn_count, last_run_path, budget_minutes=25):
    return [
        gate_team_count(conn, league, espn_count),
        gate_rosters(conn, league),
        gate_box_scores(conn, league),
        gate_period_scores(conn, league),
        gate_rollups(conn, league),
        review_stat_names(conn, league),
        gate_last_run(last_run_path, budget_minutes),
        gate_featured(conn),
    ]


def main(argv):
    try:
        codes = parse_league_codes(",".join(argv))
    except ValueError as exc:
        print(exc)
        return 2
    if len(codes) != 1:
        print("usage: league_gate.py LEAGUE   (exactly one league code, e.g. NBA)")
        return 2
    league = LEAGUES[codes[0]]
    espn_count = len(discover_teams(league))
    conn = get_connection()
    conn.set_session(readonly=True)  # this tool only reads; make that a guarantee
    try:
        results = run_gate(conn, league, espn_count, Path(LOG_DIR) / "last_pipeline.json")
    finally:
        conn.close()
    print(f"League gate for {league.code} ({league.label})\n")
    for r in results:
        print(f"  {r.status:6s} {r.name:15s} {r.detail}")
    failed = [r for r in results if r.status == "FAIL"]
    print(f"\n{'NOT READY: ' + str(len(failed)) + ' check(s) failed.' if failed else 'No failures.'}"
          f"{' Look at the REVIEW lines before enabling.' if any(r.status == 'REVIEW' for r in results) else ''}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
