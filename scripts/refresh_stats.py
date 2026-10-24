"""
Weekly check for ESPN stat corrections.

The nightly pipeline (api_pulls.py) fills in each game's period scores and
box score once, right after it goes final, and never looks at it again.
ESPN sometimes corrects stats a few days later (a tackle or assist
reassigned, a play re-scored), so this script re-fetches recent final games,
compares ESPN's current numbers to what's stored, and rewrites a game only
if something actually changed. Games with no changes aren't written at all.

Game scores/status don't need this — the nightly schedule pull already
refreshes every game row each night.

Meant to run weekly via cron, e.g. Sundays at 5 AM (after the 4 AM nightly run).
Like the nightly pipeline, each game is checked inside report.step(...), so one
failed ESPN fetch is logged and alerted but doesn't stop the other games. Exits
0 if everything worked and 1 if any step failed.
"""

import logging
import sys

from db import (
    box_score_rows,
    get_box_score,
    get_connection,
    get_game_periods,
    get_recent_final_games,
    insert_box_score,
    insert_game_periods,
    rebuild_stat_rollups,
)
from espn import fetch_summary, parse_periods, parse_team_box_score
from log_setup import setup_logging
from run_report import RunReport

log = logging.getLogger("sports_hub.refresh")

# How far back to re-check. With a weekly run, 14 days means every game
# gets checked twice before it ages out — ESPN corrections usually land
# within a few days of the game.
LOOKBACK_DAYS = 14

# Log at most this many individual differences per game, to keep the log readable
MAX_CHANGES_SHOWN = 10


def describe_box_score_changes(stored, fresh):
    """Compare a stored box score to ESPN's current one (both shaped
    {espn_athlete_id: {"name", "did_play", "seconds_played", "stats"}}).
    Returns a list of human-readable differences — empty if they match."""
    changes = []
    for athlete_id in fresh.keys() - stored.keys():
        changes.append(f"{fresh[athlete_id]['name']}: added to box score")
    for athlete_id in stored.keys() - fresh.keys():
        changes.append(f"{stored[athlete_id]['name']}: removed from box score")

    for athlete_id in fresh.keys() & stored.keys():
        old, new = stored[athlete_id], fresh[athlete_id]
        name = new["name"]
        if old["did_play"] != new["did_play"]:
            changes.append(f"{name} did_play: {old['did_play']} -> {new['did_play']}")
        if old["seconds_played"] != new["seconds_played"]:
            changes.append(
                f"{name} seconds_played: {old['seconds_played']} -> {new['seconds_played']}"
            )
        for stat_name in sorted(old["stats"].keys() | new["stats"].keys()):
            before = old["stats"].get(stat_name)
            after = new["stats"].get(stat_name)
            if before != after:
                changes.append(f"{name} {stat_name}: {before} -> {after}")
    return changes


def check_game(conn, game, totals):
    """Re-check one game against ESPN and rewrite whatever changed.
    `totals` is a dict of running counters shared across games."""
    game_id, league, external_id, regulation_periods, sides = game
    summary = fetch_summary(league, external_id)
    game_changed = False

    # --- Period scores ---
    # A None/empty result from ESPN is skipped rather than written, so a
    # temporary ESPN glitch can never wipe out good stored data.
    fresh_periods = parse_periods(summary, regulation_periods)
    stored_periods = get_game_periods(conn, game_id)
    if fresh_periods and set(fresh_periods) != set(stored_periods):
        insert_game_periods(conn, game_id, fresh_periods, replace=True)
        totals["periods_updated"] += 1
        game_changed = True
        log.info("%s game %s: period scores updated", league, external_id)
        log.info("    was: %s", sorted(stored_periods))
        log.info("    now: %s", sorted(fresh_periods))

    # --- Box scores: each team's side is compared and rewritten on its own ---
    for team_id, espn_id in sides:
        fresh_box = parse_team_box_score(summary, espn_id, league)
        if not fresh_box:
            continue
        stored_box = get_box_score(conn, game_id, team_id)
        changes = describe_box_score_changes(stored_box, fresh_box)
        if changes:
            insert_box_score(
                conn,
                game_id,
                team_id,
                box_score_rows(conn, team_id, league, fresh_box),
                replace=True,
            )
            totals["box_scores_updated"] += 1
            game_changed = True
            log.info(
                "%s game %s, team %s: box score updated (%d changes)",
                league,
                external_id,
                team_id,
                len(changes),
            )
            for change in changes[:MAX_CHANGES_SHOWN]:
                log.info("    %s", change)
            if len(changes) > MAX_CHANGES_SHOWN:
                log.info("    ... and %d more", len(changes) - MAX_CHANGES_SHOWN)

    if not game_changed:
        totals["unchanged"] += 1


def main():
    setup_logging("refresh")
    report = RunReport("refresh")

    conn = None
    with report.step("Database connection"):
        conn = get_connection()
    if conn is None:
        return report.finish()
    report.conn = conn

    try:
        games = []
        with report.step("List recent games"):
            games = get_recent_final_games(conn, LOOKBACK_DAYS)
        log.info("Checking %d final games from the last %d days", len(games), LOOKBACK_DAYS)

        totals = {"periods_updated": 0, "box_scores_updated": 0, "unchanged": 0}
        for game in games:
            _game_id, league, external_id, _periods, _sides = game
            with report.step(f"{league} game {external_id}"):
                check_game(conn, game, totals)

        # Season/career totals are built from box scores, so rebuild them if any changed
        if totals["box_scores_updated"]:
            with report.step("Rollups"):
                season_rows, career_rows = rebuild_stat_rollups(conn)
                report.count("season rollup rows", season_rows)
                report.count("career rollup rows", career_rows)

        report.count("games checked", len(games))
        report.count("period changes", totals["periods_updated"])
        report.count("box score changes", totals["box_scores_updated"])
        report.count("unchanged", totals["unchanged"])
    finally:
        conn.close()

    return report.finish()


if __name__ == "__main__":
    sys.exit(main())
