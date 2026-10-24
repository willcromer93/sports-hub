"""
Find every team in a league, straight from ESPN.

Two traps this module exists to defend against (found by probing ESPN on 2026-10-23):

  1. ESPN's teams endpoint returns only the FIRST 50 teams unless you pass `limit`,
     and the reply has no count or paging field, so truncation is invisible. We always
     pass limit=1000 AND require at least league.min_teams teams; a short list raises
     DiscoveryError instead of quietly loading a seventh of college basketball.
  2. ESPN's college football team list holds 762 teams of every level and ignores a
     division filter. The top division (FBS) comes from ESPN's FBS standings (138 teams).

Parsing is kept in small pure functions (parse_*) so it can be tested without the
network. A reply that doesn't have the shape we expect raises DiscoveryError, naming
the league, rather than a bare KeyError.
"""

from dataclasses import dataclass
from typing import Optional

from http_client import fetch_json

ESPN_SITE = "https://site.api.espn.com/apis/site/v2/sports"
ESPN_V2 = "https://site.api.espn.com/apis/v2/sports"
FBS_GROUP = 80  # ESPN's id for the college football top division


class DiscoveryError(Exception):
    """ESPN's team list was missing, malformed, or suspiciously short."""


@dataclass(frozen=True)
class DiscoveredTeam:
    espn_id: str
    name: str
    abbreviation: Optional[str] = None


def parse_teams_list(data):
    """Teams from ESPN's .../teams reply: sports[0].leagues[0].teams[*].team."""
    try:
        entries = data["sports"][0]["leagues"][0]["teams"]
        return [
            DiscoveredTeam(
                str(entry["team"]["id"]),
                entry["team"]["displayName"],
                entry["team"].get("abbreviation"),
            )
            for entry in entries
        ]
    except (KeyError, IndexError, TypeError) as exc:
        raise DiscoveryError(f"unexpected teams-list format ({type(exc).__name__}: {exc})") from exc


def parse_fbs_standings(data):
    """Teams from ESPN's standings reply. Standings are nested: conferences are
    "children", possibly several levels deep, and each holds standings entries."""
    teams = []

    def walk(node):
        for child in node.get("children", []):
            walk(child)
        for entry in node.get("standings", {}).get("entries", []):
            team = entry["team"]
            teams.append(
                DiscoveredTeam(str(team["id"]), team["displayName"], team.get("abbreviation"))
            )

    try:
        walk(data)
    except (KeyError, TypeError, AttributeError) as exc:
        raise DiscoveryError(f"unexpected standings format ({type(exc).__name__}: {exc})") from exc
    return teams


def check_team_list(league, teams):
    """The safety checks every team list must pass. Raises DiscoveryError."""
    if len(teams) < league.min_teams:
        raise DiscoveryError(
            f"{league.code}: ESPN listed {len(teams)} teams but at least "
            f"{league.min_teams} are expected (ESPN listed {league.expected_teams} on "
            f"2026-10-23). A short list usually means a truncated reply "
            f"(ESPN returns only 50 teams without limit=) or a format change."
        )
    ids = [team.espn_id for team in teams]
    if len(set(ids)) != len(ids):
        duplicated = sorted({i for i in ids if ids.count(i) > 1})
        raise DiscoveryError(f"{league.code}: duplicate ESPN team ids in the list: {duplicated[:5]}")


def discover_teams(league):
    """Every team in the league, as [DiscoveredTeam]. Raises DiscoveryError (or
    FetchError, from the HTTP client) if ESPN's answer can't be trusted."""
    if league.team_source == "teams_list":
        data = fetch_json(f"{ESPN_SITE}/{league.sport_path}/teams", params={"limit": 1000})
        teams = parse_teams_list(data)
    elif league.team_source == "fbs_standings":
        data = fetch_json(
            f"{ESPN_V2}/{league.sport_path}/standings",
            params={"group": FBS_GROUP, "level": 3},
        )
        teams = parse_fbs_standings(data)
    else:
        raise DiscoveryError(f"{league.code}: unknown team_source {league.team_source!r}")
    check_team_list(league, teams)
    return teams
