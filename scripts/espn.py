"""
Helpers for ESPN's per-game summary endpoint: fetching a game, and turning
its line scores and box score into the shapes db.py stores.

Shared by api_pulls.py (nightly: fills in new games) and refresh_stats.py
(weekly: re-checks recent games for ESPN stat corrections). These functions
don't touch the database.
"""

import requests

# League -> ESPN URL path segment
SPORT_PATHS = {
    "NBA": "basketball/nba",
    "NCAAB": "basketball/mens-college-basketball",
    "NHL": "hockey/nhl",
    "NFL": "football/nfl",
}


def fetch_summary(league, event_id):
    """Fetch ESPN's full summary (line scores, box score, ...) for one game."""
    response = requests.get(
        f"https://site.api.espn.com/apis/site/v2/sports/{SPORT_PATHS[league]}/summary",
        params={"event": event_id},
    )
    return response.json()


def extract_linescores(competitor):
    """ESPN's per-period scores for one team, as a list of ints in order:
    regulation periods first, then any overtimes, then a shootout (NHL)."""
    return [
        int(float(line["displayValue"])) for line in competitor.get("linescores", [])
    ]


def build_periods(home_lines, away_lines, regulation_periods, is_shootout):
    """Turn two lists of per-period scores into game_periods rows of
    (period_number, period_type, home_score, away_score).
    Numbering restarts for each type: regulation 1..N, overtime 1..k,
    shootout 1 — so NBA double overtime is ('overtime', 1) and ('overtime', 2).
    ESPN doesn't label which entry is which, so it's worked out from the
    league's regulation period count (from sport_period_labels) and, for
    hockey, whether the game ended in a shootout (always the last entry)."""
    periods = []
    last_index = len(home_lines) - 1
    for index, (home, away) in enumerate(zip(home_lines, away_lines)):
        if index < regulation_periods:
            periods.append((index + 1, "regulation", home, away))
        elif is_shootout and index == last_index:
            periods.append((1, "shootout", home, away))
        else:
            periods.append((index - regulation_periods + 1, "overtime", home, away))
    return periods


def parse_periods(summary, regulation_periods):
    """game_periods rows for one game's summary, or None if ESPN's line
    scores are missing or lopsided (so callers never store a partial game)."""
    competition = summary["header"]["competitions"][0]
    lines = {c["homeAway"]: extract_linescores(c) for c in competition["competitors"]}
    home_lines = lines.get("home", [])
    away_lines = lines.get("away", [])
    if not home_lines or len(home_lines) != len(away_lines):
        return None
    is_shootout = "/SO" in competition["status"]["type"].get("detail", "")
    return build_periods(home_lines, away_lines, regulation_periods, is_shootout)


# Box score keys that hold playing time. They go into
# player_game_appearances.seconds_played rather than player_game_stats.
PLAYING_TIME_KEYS = {"minutes", "timeOnIce"}

# NFL box scores are split into stat categories (passing, rushing, defensive, ...)
# that reuse key names with different meanings — "interceptions" is thrown under
# passing but caught under defensive — so NFL stat names get the category as a
# prefix, e.g. "passing.interceptions". NHL groups are positions (forwards,
# goalies), and a player is only ever in one, so no prefix is needed there.
STAT_GROUP_PREFIX_LEAGUES = {"NFL"}


def parse_stat_value(raw):
    """Convert one box score value to a number.
    '14' -> 14.0, '+6' -> 6.0, '.923' -> 0.923, '12:50' -> 770 (seconds).
    Returns None for blanks like '--' or ''."""
    if ":" in raw:
        minutes, seconds = raw.split(":")
        return int(minutes) * 60 + int(seconds)
    try:
        return float(raw)
    except ValueError:
        return None


def parse_box_score(team_box, league):
    """Flatten one team's ESPN box score into
    {espn_athlete_id: {"name", "did_play", "seconds_played", "stats"}}.
    A player can appear in several stat groups (an NFL running back is under
    both rushing and receiving), so their stats are merged into one entry."""
    players = {}
    for group in team_box.get("statistics", []):
        prefix = f"{group['name']}." if league in STAT_GROUP_PREFIX_LEAGUES else ""
        for entry in group.get("athletes", []):
            athlete = entry["athlete"]
            player = players.setdefault(
                athlete["id"],
                {
                    "name": athlete["displayName"],
                    # Only basketball marks DNPs; for other sports everyone listed played
                    "did_play": not entry.get("didNotPlay"),
                    "seconds_played": None,
                    "stats": {},
                },
            )
            for key, raw in zip(group["keys"], entry.get("stats", [])):
                if key in PLAYING_TIME_KEYS:
                    value = parse_stat_value(raw)
                    if value is not None:
                        # Basketball gives whole minutes; hockey's MM:SS is already seconds
                        seconds = value * 60 if key == "minutes" else value
                        player["seconds_played"] = int(seconds)
                    continue
                if key.startswith("ytd"):  # season-to-date totals, not this game
                    continue

                # Paired stats like "fieldGoalsMade-fieldGoalsAttempted": "6-10"
                # or "completions/passingAttempts": "19/31" become two stats.
                names, values = [key], [raw]
                for separator in ("/", "-"):
                    if separator in key:
                        names, values = key.split(separator), raw.split(separator)
                        break
                if len(names) != len(values):
                    continue
                for name, value in zip(names, values):
                    number = parse_stat_value(value)
                    if number is not None:
                        player["stats"][prefix + name] = number
    return players


def parse_team_box_score(summary, espn_team_id, league):
    """One team's parsed box score from a game summary ({} if ESPN has none)."""
    team_boxes = summary.get("boxscore", {}).get("players", [])
    team_box = next((t for t in team_boxes if t["team"]["id"] == espn_team_id), None)
    return parse_box_score(team_box, league) if team_box else {}
