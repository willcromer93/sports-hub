"""
Post-run sanity checks: the invariants the data should always satisfy, checked
automatically at the end of every nightly run.

The pipeline can "succeed" while quietly doing the wrong thing (ESPN changes a
format, a step returns nothing, a duplicate row appears). These checks look at
the finished data instead of at the steps. A failed check does NOT fail the run;
it becomes a warning, which sends a phone alert (see run_report.py).

Each check_* function takes a database connection and returns a list of
problems: an empty list means the check passed.
"""

import json
import logging
from pathlib import Path

from log_setup import LOG_DIR

log = logging.getLogger("sports_hub.sanity")

MAX_EXAMPLES = 3  # how many offenders to name in an alert
STALE_HOURS = 36  # a game this old should have been filled in by the nightly runs

# Known upstream data errors we have looked into and can't fix, so they don't alert
# every night. Each entry says WHY. If ESPN later corrects one, the check logs a note
# so the entry can be deleted. Keys are (league, ESPN event id).
ACKNOWLEDGED_PERIOD_MISMATCHES = {
    ("NHL", "401892450"): (
        "Red Wings 5, Senators 3 on 2026-10-06: ESPN's own line scores are 2-2-0 "
        "(total 4) but its final score is 5. ESPN's feed contradicts itself; "
        "checked against the live API on 2026-10-23."
    ),
}

# Tables the pipeline only ever adds to. Their row counts must never shrink.
# (The rollup tables are rebuilt from scratch every night, so they are excluded.)
APPEND_ONLY_TABLES = [
    "teams",
    "players",
    "games",
    "game_periods",
    "player_game_appearances",
    "player_game_stats",
]


def _fetch(conn, sql, params=None):
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def _examples(rows):
    """'NFL 4018, NHL 4019' from rows of (league, external_id), at most MAX_EXAMPLES."""
    return ", ".join(f"{league} {external_id}" for league, external_id in rows[:MAX_EXAMPLES])


def check_tracked_teams(conn, expected):
    """Exactly the expected number of tracked teams, and no duplicates.
    A duplicate tracked team (e.g. the orphaned Colts row from 2026-08-30) means an
    upsert stopped matching and is silently creating new rows."""
    problems = []
    (count,) = _fetch(conn, "SELECT count(*) FROM teams WHERE is_tracked;")[0]
    if count != expected:
        problems.append(f"{count} tracked teams, expected {expected}")
    dupes = _fetch(
        conn,
        """
        SELECT league, name FROM teams WHERE is_tracked
        GROUP BY league, name HAVING count(*) > 1;
        """,
    )
    if dupes:
        problems.append("duplicate tracked team(s): " + ", ".join(f"{lg} {nm}" for lg, nm in dupes))
    return problems


def check_games_have_tracked_team(conn):
    """Every game should involve at least one of our tracked teams."""
    rows = _fetch(
        conn,
        """
        SELECT g.league, g.external_id FROM games g
        WHERE NOT EXISTS (
            SELECT 1 FROM teams t
            WHERE t.is_tracked AND t.team_id IN (g.home_team_id, g.away_team_id)
        )
        ORDER BY g.game_time DESC;
        """,
    )
    if not rows:
        return []
    return [f"{len(rows)} game(s) involve no tracked team (e.g. {_examples(rows)})"]


def check_final_games_have_scores(conn):
    """A final game must have both scores."""
    rows = _fetch(
        conn,
        """
        SELECT league, external_id FROM games
        WHERE status = 'final' AND (home_score IS NULL OR away_score IS NULL)
        ORDER BY game_time DESC;
        """,
    )
    if not rows:
        return []
    return [f"{len(rows)} final game(s) missing a score (e.g. {_examples(rows)})"]


def check_period_sums(conn):
    """Per-period scores must add up to the final score (this is the check that
    was done by hand on 2026-09-24; NHL shootouts add up too, since the winner's
    shootout entry is 1)."""
    rows = _fetch(
        conn,
        """
        SELECT g.league, g.external_id
        FROM games g
        JOIN (SELECT game_id, sum(home_score) AS h, sum(away_score) AS a
              FROM game_periods GROUP BY game_id) p USING (game_id)
        WHERE g.status = 'final' AND (g.home_score <> p.h OR g.away_score <> p.a)
        ORDER BY g.game_time DESC;
        """,
    )
    mismatched = {(league, external_id) for league, external_id in rows}
    for key in ACKNOWLEDGED_PERIOD_MISMATCHES:
        if key not in mismatched:
            log.info(
                "Acknowledged period mismatch %s no longer occurs (ESPN fixed it?); "
                "remove it from ACKNOWLEDGED_PERIOD_MISMATCHES",
                key,
            )
    new = [row for row in rows if tuple(row) not in ACKNOWLEDGED_PERIOD_MISMATCHES]
    if not new:
        return []
    return [f"{len(new)} final game(s) whose periods don't add up to the score (e.g. {_examples(new)})"]


def check_box_scores_present(conn):
    """Final games older than STALE_HOURS should have a box score for our team.
    A missing one usually means the box-score step is failing quietly."""
    rows = _fetch(
        conn,
        """
        SELECT g.league, g.external_id
        FROM games g
        JOIN teams t ON t.is_tracked AND t.team_id IN (g.home_team_id, g.away_team_id)
        WHERE g.status = 'final'
          AND g.game_time < now() - make_interval(hours => %s)
          AND NOT EXISTS (
              SELECT 1 FROM player_game_appearances a
              WHERE a.game_id = g.game_id AND a.team_id = t.team_id
          )
        ORDER BY g.game_time DESC;
        """,
        (STALE_HOURS,),
    )
    if not rows:
        return []
    return [f"{len(rows)} final game(s) older than {STALE_HOURS}h have no box score (e.g. {_examples(rows)})"]


def check_games_fresh(conn, since):
    """The nightly schedule pull touches every game row. If no game was touched
    since `since` (when this run started), that step 'succeeded' while doing nothing.
    (Compared with the run start, not a fixed window: a fixed 36 h window would let a
    single silent failure slip through, since last night's rows are only 24 h old.)"""
    ((stale,),) = _fetch(
        conn,
        "SELECT coalesce(max(last_updated) < %s, true) FROM games;",
        (since,),
    )
    return ["no game row was updated during this run (schedule pull did nothing?)"] if stale else []


def table_counts(conn):
    """Row count of every append-only table, as {table: count}."""
    return {
        table: _fetch(conn, f"SELECT count(*) FROM {table};")[0][0]  # table names are constants above
        for table in APPEND_ONLY_TABLES
    }


def check_row_counts(current, previous):
    """No append-only table should have fewer rows than after the previous run."""
    problems = []
    for table, before in (previous or {}).items():
        now = current.get(table)
        if now is not None and now < before:
            problems.append(f"{table} shrank from {before} to {now} rows")
    return problems


def load_previous_counts(job_name, log_dir=None):
    """Table counts saved by the previous run (in last_<job>.json), or None."""
    path = Path(log_dir or LOG_DIR) / f"last_{job_name}.json"
    try:
        return json.loads(path.read_text()).get("table_counts")
    except (OSError, ValueError):
        return None  # first run, or an unreadable file: nothing to compare with


def run_sanity_checks(conn, report, expected_tracked_teams):
    """Run every check. Each runs in its own report.step, so a broken check is
    recorded as an error instead of being silently skipped; each failed check
    becomes a warning. The row counts are saved in last_<job>.json for tomorrow."""
    previous = load_previous_counts(report.name)
    counts = {}

    checks = [
        ("tracked teams", lambda: check_tracked_teams(conn, expected_tracked_teams)),
        ("games have a tracked team", lambda: check_games_have_tracked_team(conn)),
        ("final games have scores", lambda: check_final_games_have_scores(conn)),
        ("periods add up to scores", lambda: check_period_sums(conn)),
        ("box scores present", lambda: check_box_scores_present(conn)),
        ("games fresh", lambda: check_games_fresh(conn, report.started.astimezone())),
    ]
    problem_total = 0
    for name, run_check in checks:
        with report.step(f"Sanity check: {name}"):
            problems = run_check()
            if problems:
                problem_total += len(problems)
                report.warn(f"Sanity: {name}", "; ".join(problems))

    with report.step("Sanity check: row counts"):
        counts = table_counts(conn)
        problems = check_row_counts(counts, previous)
        if problems:
            problem_total += len(problems)
            report.warn("Sanity: row counts", "; ".join(problems))
        elif previous is None:
            log.info("No previous table counts to compare with (first run with this check)")

    report.extra["table_counts"] = counts
    report.count("sanity problems", problem_total)
