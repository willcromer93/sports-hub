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

# Period scores vs final score. ESPN's own data is occasionally inconsistent (its line
# scores add up to one goal fewer than its own final score), so a mismatch is judged by
# how NEW it is and how COMMON it is, not by whether it exists:
RECENT_DAYS = 3  # a mismatch on a game finished this recently is reported (once, in effect)
SYSTEMIC_RATE = 0.02  # more than 2% of a league's finals mismatching is no ESPN quirk
MIN_GAMES_FOR_RATE = 50  # ...but only judge a rate once a league has this many games

# Known upstream data errors we have looked into and can't fix, so they don't alert
# every night. Each entry says WHY. If ESPN later corrects one, the check logs a note
# so the entry can be deleted. Keys are (league, ESPN event id).
ACKNOWLEDGED_PERIOD_MISMATCHES = {
    ("NHL", "401892450"): (
        "Red Wings 5, Senators 3 on 2026-10-06: ESPN's own line scores are 2-2-0 "
        "(total 4) but its final score is 5. ESPN's feed contradicts itself; "
        "checked against the live API on 2026-10-23."
    ),
    ("NHL", "401886441"): (
        "Maple Leafs 6, Senators 1 on 2026-09-23 (preseason): ESPN's line scores for "
        "Toronto are 2-3-0 (total 5) but its final score is 6; checked against the live "
        "API on 2026-10-24."
    ),
    ("NHL", "401879364"): (
        "Avalanche 4, Mammoth 1 on 2026-09-20 (preseason): ESPN's line scores for "
        "Colorado are 0-1-2 (total 3) but its final score is 4; checked against the live "
        "API on 2026-10-24. Like the other two, the HOME team's line score is one goal short."
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
    """Each league has the number of tracked teams we expect, with no duplicates.
    `expected` maps league code -> count (the pipeline fills it in from what it
    just collected); a league missing from it is skipped, e.g. one whose team
    list could not be fetched tonight. A duplicate tracked team (e.g. the
    orphaned Colts row from 2026-08-30) means an upsert stopped matching and is
    silently creating new rows."""
    problems = []
    found = dict(
        _fetch(conn, "SELECT league, count(*) FROM teams WHERE is_tracked GROUP BY league;")
    )
    for league, want in expected.items():
        have = found.get(league, 0)
        if have != want:
            problems.append(f"{league}: {have} tracked teams, expected {want}")
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


def check_featured_teams(conn, featured):
    """The teams flagged is_featured must be exactly the featured teams in the
    configuration (leagues.FEATURED_TEAMS). `featured` is a set of (league, espn_id).
    The dashboard is built around these, so a changed flag should never be a surprise."""
    in_db = {(league, espn_id) for league, espn_id in _fetch(
        conn, "SELECT league, espn_id FROM teams WHERE is_featured;"
    )}
    problems = []
    if in_db - featured:
        problems.append("featured in the database but not in the config: " + ", ".join(f"{lg} {eid}" for lg, eid in sorted(in_db - featured)))
    if featured - in_db:
        problems.append("in the config but not featured in the database: " + ", ".join(f"{lg} {eid}" for lg, eid in sorted(featured - in_db)))
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
    """Per-period scores should add up to the final score (the check done by hand on
    2026-09-24; NHL shootouts add up too, since the winner's shootout entry is 1).

    ESPN's own data is occasionally inconsistent, so a mismatch is judged by how new and
    how common it is. Reported: (1) a mismatch on a game that finished in the last
    RECENT_DAYS days, which alerts when it first appears rather than every night forever,
    and (2) a league where more than SYSTEMIC_RATE of the finals mismatch, which is more
    likely a bug in our data than an ESPN quirk. Games in ACKNOWLEDGED_PERIOD_MISMATCHES
    (looked into, documented, not fixable) are never reported."""
    rows = _fetch(
        conn,
        """
        SELECT g.league, g.external_id, g.game_time >= now() - make_interval(days => %s)
        FROM games g
        JOIN (SELECT game_id, sum(home_score) AS h, sum(away_score) AS a
              FROM game_periods GROUP BY game_id) p USING (game_id)
        WHERE g.status = 'final' AND (g.home_score <> p.h OR g.away_score <> p.a)
        ORDER BY g.game_time DESC;
        """,
        (RECENT_DAYS,),
    )
    totals = dict(
        _fetch(
            conn,
            """
            SELECT g.league, count(*)
            FROM games g
            WHERE g.status = 'final' AND EXISTS (SELECT 1 FROM game_periods p WHERE p.game_id = g.game_id)
            GROUP BY g.league;
            """,
        )
    )
    mismatched = {(league, external_id) for league, external_id, _recent in rows}
    for key in ACKNOWLEDGED_PERIOD_MISMATCHES:
        if key not in mismatched:
            log.info(
                "Acknowledged period mismatch %s no longer occurs (ESPN fixed it?); "
                "remove it from ACKNOWLEDGED_PERIOD_MISMATCHES",
                key,
            )
    new = [row for row in rows if (row[0], row[1]) not in ACKNOWLEDGED_PERIOD_MISMATCHES]

    problems = []
    recent = [(league, eid) for league, eid, is_recent in new if is_recent]
    if recent:
        problems.append(
            f"{len(recent)} final game(s) from the last {RECENT_DAYS} days whose periods "
            f"don't add up to the score (e.g. {_examples(recent)})"
        )
    per_league = {}
    for league, _eid, _recent in new:
        per_league[league] = per_league.get(league, 0) + 1
    for league, n in sorted(per_league.items()):
        total = totals.get(league, 0)
        if total >= MIN_GAMES_FOR_RATE and n / total > SYSTEMIC_RATE:
            problems.append(
                f"{league}: {n} of {total} final games ({100 * n / total:.1f}%) have periods "
                f"that don't add up, too many to be an ESPN quirk"
            )
    return problems


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


def run_sanity_checks(conn, report, expected_tracked, featured):
    """Run every check. Each runs in its own report.step, so a broken check is
    recorded as an error instead of being silently skipped; each failed check
    becomes a warning. The row counts are saved in last_<job>.json for tomorrow."""
    previous = load_previous_counts(report.name)
    counts = {}

    checks = [
        ("tracked teams", lambda: check_tracked_teams(conn, expected_tracked)),
        ("featured teams", lambda: check_featured_teams(conn, featured)),
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
