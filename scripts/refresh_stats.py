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
"""

from db import (
    box_score_rows,
    get_box_score,
    get_connection,
    get_game_periods,
    get_recent_final_games,
    insert_box_score,
    insert_game_periods,
)
from espn import fetch_summary, parse_periods, parse_team_box_score

# How far back to re-check. With a weekly run, 14 days means every game
# gets checked twice before it ages out — ESPN corrections usually land
# within a few days of the game.
LOOKBACK_DAYS = 14

# Print at most this many individual differences per game, to keep the log readable
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


conn = get_connection()
games = get_recent_final_games(conn, LOOKBACK_DAYS)
print(f"Checking {len(games)} final games from the last {LOOKBACK_DAYS} days")

periods_updated = 0
box_scores_updated = 0
unchanged = 0
for game_id, league, external_id, regulation_periods, team_id, espn_id in games:
    summary = fetch_summary(league, external_id)
    game_changed = False

    # --- Period scores ---
    # A None/empty result from ESPN is skipped rather than written, so a
    # temporary ESPN glitch can never wipe out good stored data.
    fresh_periods = parse_periods(summary, regulation_periods)
    stored_periods = get_game_periods(conn, game_id)
    if fresh_periods and set(fresh_periods) != set(stored_periods):
        insert_game_periods(conn, game_id, fresh_periods, replace=True)
        periods_updated += 1
        game_changed = True
        print(f"{league} game {external_id}: period scores updated")
        print(f"    was: {sorted(stored_periods)}")
        print(f"    now: {sorted(fresh_periods)}")

    # --- Box score ---
    fresh_box = parse_team_box_score(summary, espn_id, league)
    if fresh_box:
        changes = describe_box_score_changes(get_box_score(conn, game_id), fresh_box)
        if changes:
            insert_box_score(
                conn,
                game_id,
                box_score_rows(conn, team_id, league, fresh_box),
                replace=True,
            )
            box_scores_updated += 1
            game_changed = True
            print(
                f"{league} game {external_id}: box score updated ({len(changes)} changes)"
            )
            for change in changes[:MAX_CHANGES_SHOWN]:
                print(f"    {change}")
            if len(changes) > MAX_CHANGES_SHOWN:
                print(f"    ... and {len(changes) - MAX_CHANGES_SHOWN} more")

    if not game_changed:
        unchanged += 1

print(
    f"Done: {periods_updated} games had period score changes, "
    f"{box_scores_updated} had box score changes, {unchanged} unchanged"
)
conn.close()
