"""
The league registry: one place that describes every league the project knows.

Adding a league means adding an entry here (plus its box-score parser if the format
is new, plus tests). Which leagues have EVERY team collected is a setting in .env:

    LEAGUES_ALL=NBA,NFL     collect every team in these leagues
                            (leave it out and only the featured teams are collected)

A league not listed in LEAGUES_ALL still collects its featured team(s), if any, so
turning a league on or off never touches the four teams the dashboard is built around.
"""

import os
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class League:
    code: str  # our league code, stored in teams.league, games.league, ...
    label: str  # for humans
    sport_path: str  # ESPN URL segment: .../sports/{sport_path}/teams/...
    team_source: str  # how to list every team: "teams_list" or "fbs_standings"
    min_teams: int  # fewer teams than this from ESPN means a truncated or broken reply
    expected_teams: int  # what ESPN listed on 2026-10-23 (documentation for humans)


# The 7 leagues. min_teams is a floor, not an exact count: ESPN's teams endpoint returns
# only 50 teams unless asked for more, with no count field, so a short list is the only
# way truncation shows itself (see team_discovery.py).
#
# The ORDER matters: the pipeline processes leagues in this order, and database rows are
# auto-numbered in insertion order. NBA, NCAAB, NHL, NFL is the order the original
# four-team pipeline used, kept first so ids stay stable.
LEAGUES = {
    league.code: league
    for league in [
        League("NBA", "NBA", "basketball/nba", "teams_list", 28, 30),
        # College basketball keeps the code NCAAB (Purdue's rows already use it).
        League(
            "NCAAB",
            "College basketball (men's D1)",
            "basketball/mens-college-basketball",
            "teams_list",
            350,
            362,
        ),
        League("NHL", "NHL", "hockey/nhl", "teams_list", 30, 32),
        League("NFL", "NFL", "football/nfl", "teams_list", 30, 32),
        League("WNBA", "WNBA", "basketball/wnba", "teams_list", 12, 15),
        League("MLB", "MLB", "baseball/mlb", "teams_list", 28, 30),
        # ESPN's college football team list holds 762 teams of every level and ignores
        # a division filter, so the top division (FBS) comes from its standings.
        League(
            "CFB",
            "College football (FBS)",
            "football/college-football",
            "fbs_standings",
            130,
            138,
        ),
    ]
}


@dataclass(frozen=True)
class FeaturedTeam:
    """A team the dashboard is built around. These are always collected, even in a
    league that isn't in LEAGUES_ALL."""

    label: str  # short name used in logs and alerts
    league: str
    espn_id: str
    founded_year: int  # no API provides this, so it's recorded here
    # Used only when ESPN has no venue for the team (it has none for college basketball)
    venue: Optional[str] = None
    city: Optional[str] = None


FEATURED_TEAMS = [
    FeaturedTeam("Pacers", "NBA", "11", 1967),
    # ESPN has no venue for college basketball teams, so Purdue's is recorded here
    FeaturedTeam("Purdue", "NCAAB", "2509", 1896, "Mackey Arena", "West Lafayette"),
    FeaturedTeam("Red Wings", "NHL", "5", 1926),
    FeaturedTeam("Colts", "NFL", "11", 1984),  # the Indianapolis relocation, not 1953
]


def featured_teams(league_code):
    """The featured teams in one league (usually none or one)."""
    return [t for t in FEATURED_TEAMS if t.league == league_code]


def parse_league_codes(text):
    """Turn "nba, NFL" into ["NBA", "NFL"]: upper-cased, de-duplicated, in registry
    order. Raises ValueError naming any code that isn't a known league (a typo
    here should stop the run, not silently collect nothing)."""
    wanted = {part.strip().upper() for part in (text or "").split(",") if part.strip()}
    unknown = sorted(wanted - LEAGUES.keys())
    if unknown:
        raise ValueError(
            f"Unknown league code(s) in LEAGUES_ALL: {', '.join(unknown)}. "
            f"Known: {', '.join(LEAGUES)}"
        )
    return [code for code in LEAGUES if code in wanted]


def leagues_all():
    """Leagues where every team is collected (the LEAGUES_ALL setting)."""
    return parse_league_codes(os.getenv("LEAGUES_ALL"))
