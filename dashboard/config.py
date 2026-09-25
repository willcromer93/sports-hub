"""
Dashboard settings — THE file to edit to change what the dashboard shows.

Every stat table, leader tile, and chart dropdown in the dashboard is built
from the lists below, so changing a stat never means touching page code:

- Add a column:     add a line to a group's "columns" list.
- Remove a column:  delete (or comment out with #) its line.
- Reorder columns:  move the lines around — tables follow this order.
- Add a table:      add another {...} group to a league's list.
- Change the tiles: edit HEADLINE_STATS.

Stat keys are ESPN's names exactly as stored in player_game_stats.stat_name
(see Schema.md). To list every key a league has, run in SQLTools:

    SELECT DISTINCT s.stat_name
    FROM player_game_stats s JOIN games g USING (game_id)
    WHERE g.league = 'NHL'
    ORDER BY 1;
"""

# ---------------------------------------------------------------------------
# Column builders. Each returns a small dict describing one table column.
# They exist so the lists below read like a spec sheet instead of raw dicts.
# ---------------------------------------------------------------------------


def stat(label, *keys, fmt="count", average=True):
    """
    A stat added up across games.

    stat("PTS", "points")              -> one ESPN stat
    stat("PTS", "goals", "assists")    -> several stats added together
    fmt: "count" (default), "time" (seconds shown as MM:SS),
         or "minutes" (seconds shown as decimal minutes, e.g. 32.5)
    average: set to False for a stat that should always show as a season
         total, even in per-game mode (e.g. +/-)
    """
    return {
        "kind": "stat",
        "label": label,
        "keys": list(keys),
        "format": fmt,
        "average": average,
    }


def ratio(label, made, attempted, fmt="pct"):
    """
    A rate computed from totals: sum(made) / sum(attempted).

    Rates are never averaged game by game — a 1-for-1 night and a 10-for-20
    night aren't worth the same. `made` and `attempted` can each be one key or
    a list of keys that get added together first.
    fmt: "pct" (shown as 45.6%) or "decimal" (shown as 4.3, e.g. yards/carry)
    """
    made = [made] if isinstance(made, str) else list(made)
    attempted = [attempted] if isinstance(attempted, str) else list(attempted)
    return {
        "kind": "ratio",
        "label": label,
        "made": made,
        "attempted": attempted,
        "format": fmt,
    }


# Playing time lives in player_game_appearances.seconds_played rather than
# player_game_stats, but the dashboard treats it as a stat under this key.
PLAYING_TIME = "seconds_played"


# ---------------------------------------------------------------------------
# Tracked teams: display name, brand color (used as a thin accent only), logo.
# Keys must match teams.name exactly.
# ---------------------------------------------------------------------------

TEAMS = {
    "Indiana Pacers": {
        "short": "Pacers",
        "color": "#002D62",
        "logo": "https://a.espncdn.com/i/teamlogos/nba/500/ind.png",
    },
    "Purdue Boilermakers": {
        "short": "Purdue",
        "color": "#9D7A2B",
        "logo": "https://a.espncdn.com/i/teamlogos/ncaa/500/2509.png",
    },
    "Detroit Red Wings": {
        "short": "Red Wings",
        "color": "#CE1126",
        "logo": "https://a.espncdn.com/i/teamlogos/nhl/500/det.png",
    },
    "Indianapolis Colts": {
        "short": "Colts",
        "color": "#002C5F",
        "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/ind.png",
    },
}

# Order teams appear in on the Overview page and in the team picker.
TEAM_ORDER = [
    "Indiana Pacers",
    "Purdue Boilermakers",
    "Detroit Red Wings",
    "Indianapolis Colts",
]

# Game times are stored in UTC-aware timestamps; this is how they're shown.
DISPLAY_TIMEZONE = "America/Indiana/Indianapolis"


# ---------------------------------------------------------------------------
# Stat tables, per league.
#
# Each group becomes one table (on the Team, Game, and Player pages):
#   title     – table heading
#   requires  – a player only appears in this table for games where they
#               recorded this stat (e.g. only goalies have "saves")
#   sort_by   – label of the column the table is sorted by (highest first)
#   columns   – the columns, in display order
# ---------------------------------------------------------------------------

BASKETBALL = [
    {
        "title": "Box score",
        "requires": "points",
        "sort_by": "PTS",
        "columns": [
            stat("MIN", PLAYING_TIME, fmt="minutes"),
            stat("PTS", "points"),
            stat("REB", "rebounds"),
            stat("AST", "assists"),
            stat("STL", "steals"),
            stat("BLK", "blocks"),
            stat("TO", "turnovers"),
            ratio("FG%", "fieldGoalsMade", "fieldGoalsAttempted"),
            ratio("3P%", "threePointFieldGoalsMade", "threePointFieldGoalsAttempted"),
            ratio("FT%", "freeThrowsMade", "freeThrowsAttempted"),
            stat("3PM", "threePointFieldGoalsMade"),
            stat("OREB", "offensiveRebounds"),
            stat("PF", "fouls"),
        ],
    },
]

STAT_GROUPS = {
    "NBA": BASKETBALL,
    "NCAAB": BASKETBALL,
    "NHL": [
        {
            "title": "Skaters",
            "requires": "shotsTotal",
            "sort_by": "PTS",
            "columns": [
                stat("TOI", PLAYING_TIME, fmt="time"),
                stat("G", "goals"),
                stat("A", "assists"),
                stat("PTS", "goals", "assists"),
                stat("+/-", "plusMinus", average=False),
                stat("SOG", "shotsTotal"),
                stat("HIT", "hits"),
                stat("BLK", "blockedShots"),
                stat("PIM", "penaltyMinutes"),
                ratio("FO%", "faceoffsWon", ["faceoffsWon", "faceoffsLost"]),
                stat("PPTOI", "powerPlayTimeOnIce", fmt="time"),
            ],
        },
        {
            "title": "Goalies",
            "requires": "saves",
            "sort_by": "SV",
            "columns": [
                stat("TOI", PLAYING_TIME, fmt="time"),
                stat("SA", "shotsAgainst"),
                stat("SV", "saves"),
                stat("GA", "goalsAgainst"),
                ratio("SV%", "saves", "shotsAgainst"),
            ],
        },
    ],
    "NFL": [
        {
            "title": "Passing",
            "requires": "passing.passingAttempts",
            "sort_by": "YDS",
            "columns": [
                stat("CMP", "passing.completions"),
                stat("ATT", "passing.passingAttempts"),
                ratio("CMP%", "passing.completions", "passing.passingAttempts"),
                stat("YDS", "passing.passingYards"),
                ratio(
                    "Y/A",
                    "passing.passingYards",
                    "passing.passingAttempts",
                    fmt="decimal",
                ),
                stat("TD", "passing.passingTouchdowns"),
                stat("INT", "passing.interceptions"),
                stat("SCK", "passing.sacks"),
            ],
        },
        {
            "title": "Rushing",
            "requires": "rushing.rushingAttempts",
            "sort_by": "YDS",
            "columns": [
                stat("CAR", "rushing.rushingAttempts"),
                stat("YDS", "rushing.rushingYards"),
                ratio(
                    "Y/C",
                    "rushing.rushingYards",
                    "rushing.rushingAttempts",
                    fmt="decimal",
                ),
                stat("TD", "rushing.rushingTouchdowns"),
            ],
        },
        {
            "title": "Receiving",
            "requires": "receiving.receptions",
            "sort_by": "YDS",
            "columns": [
                stat("TGT", "receiving.receivingTargets"),
                stat("REC", "receiving.receptions"),
                stat("YDS", "receiving.receivingYards"),
                ratio(
                    "Y/R",
                    "receiving.receivingYards",
                    "receiving.receptions",
                    fmt="decimal",
                ),
                stat("TD", "receiving.receivingTouchdowns"),
            ],
        },
        {
            "title": "Defense",
            "requires": "defensive.totalTackles",
            "sort_by": "TKL",
            "columns": [
                stat("TKL", "defensive.totalTackles"),
                stat("SOLO", "defensive.soloTackles"),
                stat("SACK", "defensive.sacks"),
                stat("TFL", "defensive.tacklesForLoss"),
                stat("QB HIT", "defensive.QBHits"),
                stat("PD", "defensive.passesDefended"),
                stat("INT", "interceptions.interceptions"),
                stat("TD", "defensive.defensiveTouchdowns"),
            ],
        },
        {
            "title": "Kicking",
            "requires": "kicking.fieldGoalAttempts",
            "sort_by": "PTS",
            "columns": [
                stat("FGM", "kicking.fieldGoalsMade"),
                stat("FGA", "kicking.fieldGoalAttempts"),
                ratio("FG%", "kicking.fieldGoalsMade", "kicking.fieldGoalAttempts"),
                stat("XPM", "kicking.extraPointsMade"),
                stat("XPA", "kicking.extraPointAttempts"),
                stat("PTS", "kicking.totalKickingPoints"),
            ],
        },
    ],
}

# Whether each page opens showing per-game averages or season totals.
# Both pages have a Per game / Totals toggle; this is just the starting position.
DEFAULT_STAT_MODE = {
    "team": "Per game",
    "player": "Totals",
}

# Leader tiles at the top of the Team page: (group title, column label).
HEADLINE_STATS = {
    "NBA": [
        ("Box score", "PTS"),
        ("Box score", "REB"),
        ("Box score", "AST"),
        ("Box score", "3PM"),
    ],
    "NCAAB": [
        ("Box score", "PTS"),
        ("Box score", "REB"),
        ("Box score", "AST"),
        ("Box score", "3PM"),
    ],
    "NHL": [("Skaters", "G"), ("Skaters", "A"), ("Skaters", "PTS"), ("Goalies", "SV%")],
    "NFL": [
        ("Passing", "YDS"),
        ("Rushing", "YDS"),
        ("Receiving", "YDS"),
        ("Defense", "TKL"),
    ],
}

# Leaders for per-game averages and rates only count players who appeared in
# at least this share of the team's games — so a 1-for-1 backup doesn't lead
# the team in FG%.
LEADER_MIN_GAMES_SHARE = 0.5
