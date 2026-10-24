"""
Nightly pipeline: pulls teams, rosters, schedules, period scores and box scores
into Postgres, then rebuilds the season/career rollups.

Safe to rerun anytime: every write is an upsert. Run by cron at 4 AM (see README).

Each unit of work runs inside report.step(...), so one failure (an API outage, a
format change) is logged and alerted but doesn't stop the other steps. The script
exits 0 if everything worked and 1 if any step failed.
"""

import logging
import os
import sys
from dataclasses import dataclass

from db import (
    box_score_rows,
    count_on_roster,
    find_departing_players,
    get_connection,
    get_db_now,
    get_games_missing_box_scores,
    get_games_missing_periods,
    insert_box_score,
    insert_game,
    insert_game_periods,
    insert_player,
    insert_team,
    mark_players_departed,
    rebuild_stat_rollups,
    upsert_opponent_team,
)
from dotenv import load_dotenv
from espn import fetch_summary, parse_periods, parse_team_box_score
from http_client import fetch_json
from log_setup import setup_logging
from roster_tracking import decide_departures
from run_report import RunReport
from sanity_checks import run_sanity_checks

# --- Load API key from .env ---
load_dotenv()
BALLDONTLIE_KEY = os.getenv("BALLDONTLIE_KEY")
headers = {"Authorization": BALLDONTLIE_KEY}

log = logging.getLogger("sports_hub.pipeline")

ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports"


def extract_espn_fields(a):
    """Pull the common enrichment fields out of an ESPN athlete dict."""
    college = a.get("college", {}).get("name")
    headshot_url = a.get("headshot", {}).get("href")
    shoots_catches = a.get("hand", {}).get("abbreviation")  # NEW

    contracts = a.get("contracts", [])
    if contracts:
        contracts_sorted = sorted(
            contracts, key=lambda c: c.get("season", {}).get("year", 0), reverse=True
        )
        most_recent = contracts_sorted[0]
        contract_salary = most_recent.get("salary")
        contract_season = most_recent.get("season", {}).get("year")
        contract_total_value = sum(c.get("salary", 0) for c in contracts)
        contract_years = len(contracts)
        contract_expires = (
            most_recent.get("season", {}).get("endDate", "").split("T")[0] or None
        )
    else:
        contract_salary = None
        contract_season = None
        contract_total_value = None
        contract_years = None
        contract_expires = None

    injuries = a.get("injuries", [])
    if injuries:
        injury_status = injuries[0].get("status")  # CHANGED
    else:
        injury_status = None

    return (
        college,
        headshot_url,
        shoots_catches,  # NEW
        contract_salary,
        contract_season,
        contract_total_value,
        contract_years,
        contract_expires,
        injury_status,
    )


def extract_team_venue_fields(team_data):
    """Pull venue name and city out of an ESPN team dict.
    Nesting may vary by sport - falls back to None instead of erroring
    if a level of the structure isn't present."""
    franchise = team_data.get("franchise", {})
    venue_info = franchise.get("venue", team_data.get("venue", {}))
    venue = venue_info.get("fullName")
    city = venue_info.get("address", {}).get("city")
    return venue, city


def map_espn_status(status_type):
    """Translate ESPN's game status into one of the values games.status allows
    ('scheduled', 'in_progress', 'final', 'postponed', 'canceled').
    ESPN has many specific names (STATUS_HALFTIME, STATUS_END_PERIOD, ...),
    but every one also carries a simple state: 'pre', 'in', or 'post'."""
    name = status_type.get("name", "")
    if name == "STATUS_POSTPONED":
        return "postponed"
    if name in ("STATUS_CANCELED", "STATUS_CANCELLED"):
        return "canceled"
    state = status_type.get("state")
    if state == "in":
        return "in_progress"
    if state == "post":
        return "final"
    return "scheduled"


def extract_score(competitor):
    """ESPN gives scores as {"value": 23.0, "displayValue": "23"},
    or leaves the key out entirely before a game starts."""
    score = competitor.get("score")
    if isinstance(score, dict) and score.get("value") is not None:
        return int(score["value"])
    return None


# ESPN's numeric season types -> the values games.season_type allows
ESPN_SEASON_TYPES = {1: "preseason", 2: "regular", 3: "postseason"}


def pull_games(conn, league, sport_path, espn_team_id, our_team_id):
    """Pull one tracked team's preseason, regular-season, and postseason
    schedules from ESPN and upsert every game into games. The opponent is
    upserted into teams first (as an untracked team), so both home_team_id
    and away_team_id have a row to point at. Returns the number of games upserted."""
    game_count = 0
    for espn_season_type, season_type in ESPN_SEASON_TYPES.items():
        schedule = fetch_json(
            f"{ESPN_BASE}/{sport_path}/teams/{espn_team_id}/schedule",
            params={"seasontype": espn_season_type},
        )
        events = schedule.get("events", [])

        for event in events:
            competition = event["competitions"][0]

            # Look up (or create) a team_id for both sides of the game
            team_ids = {}
            scores = {}
            for competitor in competition["competitors"]:
                side = competitor["homeAway"]  # "home" or "away"
                team = competitor["team"]
                if team["id"] == espn_team_id:
                    team_ids[side] = our_team_id
                else:
                    team_ids[side] = upsert_opponent_team(
                        conn, league, team["id"], team["displayName"]
                    )
                scores[side] = extract_score(competitor)

            insert_game(
                conn,
                league,
                event["id"],
                event["season"]["year"],
                season_type,
                team_ids["home"],
                team_ids["away"],
                event["date"],
                map_espn_status(competition["status"]["type"]),
                home_score=scores["home"],
                away_score=scores["away"],
                venue_name=competition.get("venue", {}).get("fullName"),
                is_neutral_site=competition.get("neutralSite", False),
            )

        game_count += len(events)

    return game_count


def pull_game_periods(conn):
    """Fill in game_periods for every final game that doesn't have them yet.
    Uses ESPN's per-game summary endpoint (the schedule endpoint has no
    per-period scores) — one request per game, but only for games not
    already filled in, so a typical night is just the previous day's games.
    Returns the number of games filled in."""
    filled = 0
    for game_id, league, external_id, regulation_periods in get_games_missing_periods(
        conn
    ):
        periods = parse_periods(fetch_summary(league, external_id), regulation_periods)
        if periods is None:
            log.warning(
                "No usable period scores for %s game %s, skipping", league, external_id
            )
            continue
        insert_game_periods(conn, game_id, periods)
        filled += 1

    return filled


def pull_box_scores(conn):
    """Fill in player_game_appearances and player_game_stats for both teams in
    every final game, from ESPN's per-game summary endpoint. Each side (our
    team, the opponent) is filled in separately, only if it's missing.
    Opponent players who aren't in `players` yet get a minimal row.
    Returns the number of sides filled in."""
    filled = 0
    summaries = {}  # both sides of a game come from the same ESPN response
    for game_id, league, external_id, team_id, espn_id in get_games_missing_box_scores(
        conn
    ):
        if game_id not in summaries:
            summaries[game_id] = fetch_summary(league, external_id)
        parsed = parse_team_box_score(summaries[game_id], espn_id, league)
        if not parsed:
            log.warning(
                "No box score for team %s in %s game %s", team_id, league, external_id
            )
            continue
        insert_box_score(
            conn, game_id, team_id, box_score_rows(conn, team_id, league, parsed)
        )
        filled += 1

    return filled


# --- The four tracked teams ---


@dataclass(frozen=True)
class TrackedTeam:
    label: str  # short name used in logs and alerts
    league: str  # our league code: NBA, NCAAB, NHL, NFL
    sport_path: str  # ESPN URL segment, e.g. "basketball/nba"
    espn_id: str  # ESPN's team id (used to match this team in schedules)
    espn_slug: str  # what ESPN's team/roster URLs use: usually the id, "ind" for the Colts
    grouped_roster: bool  # NHL/NFL rosters are grouped by position; NBA/NCAAB are flat
    founded_year: int  # no API provides this, so it's hardcoded


def identify_pacers():
    """(external_id, name, venue, city) for the Pacers: identity from balldontlie,
    plus an extra ESPN call just for venue/city enrichment."""
    teams = fetch_json("https://api.balldontlie.io/nba/v1/teams", headers=headers)[
        "data"
    ]
    pacers = [t for t in teams if t["full_name"] == "Indiana Pacers"][0]
    team_data = fetch_json(f"{ESPN_BASE}/basketball/nba/teams/11")["team"]
    venue, city = extract_team_venue_fields(team_data)
    return str(pacers["id"]), pacers["full_name"], venue, city


def identify_purdue():
    """Purdue: identity from balldontlie. ESPN's college basketball team endpoint
    doesn't return venue data, unlike NBA/NHL/NFL, so venue/city are hardcoded."""
    teams = fetch_json("https://api.balldontlie.io/ncaab/v1/teams", headers=headers)[
        "data"
    ]
    purdue = [t for t in teams if t["college"] == "Purdue"][0]
    return str(purdue["id"]), purdue["full_name"], "Mackey Arena", "West Lafayette"


def identify_red_wings():
    """Red Wings: the external_id "DET" is fixed (never changed, or the upsert
    would create a duplicate team); venue/city come from ESPN."""
    team_data = fetch_json(f"{ESPN_BASE}/hockey/nhl/teams/5")["team"]
    venue, city = extract_team_venue_fields(team_data)
    return "DET", "Detroit Red Wings", venue, city


def identify_colts():
    """Colts: identity and venue/city all from ESPN."""
    team_data = fetch_json(f"{ESPN_BASE}/football/nfl/teams/ind")["team"]
    venue, city = extract_team_venue_fields(team_data)
    return team_data["id"], team_data["displayName"], venue, city


# (team, how to look up its identity), in the order they are processed
TRACKED_TEAMS = [
    (
        TrackedTeam("Pacers", "NBA", "basketball/nba", "11", "11", False, 1967),
        identify_pacers,
    ),
    (
        TrackedTeam(
            "Purdue",
            "NCAAB",
            "basketball/mens-college-basketball",
            "2509",
            "2509",
            False,
            1896,  # first season of Purdue men's basketball
        ),
        identify_purdue,
    ),
    (
        TrackedTeam("Red Wings", "NHL", "hockey/nhl", "5", "5", True, 1926),
        identify_red_wings,
    ),
    (
        TrackedTeam("Colts", "NFL", "football/nfl", "11", "ind", True, 1984),
        identify_colts,
    ),
]


def pull_team(conn, team, identify):
    """Upsert one tracked team into teams and return its team_id."""
    external_id, name, venue, city = identify()
    team_id = insert_team(
        conn,
        team.league,
        external_id,
        name,
        espn_id=team.espn_id,
        venue=venue,
        city=city,
        founded_year=team.founded_year,
    )
    log.info("%s inserted, team_id %s | %s, %s", team.label, team_id, venue, city)
    return team_id


def insert_roster_player(conn, team_id, league, a):
    """Upsert one player from an ESPN athlete dict; returns the player_id."""
    birth_place = a.get("birthPlace", {})
    (
        college,
        headshot_url,
        shoots_catches,
        contract_salary,
        contract_season,
        contract_total_value,
        contract_years,
        contract_expires,
        injury_status,
    ) = extract_espn_fields(a)
    return insert_player(
        conn,
        team_id,
        league,
        a["id"],
        a["fullName"],
        a["position"]["abbreviation"],
        height_inches=a.get("height"),
        weight_lbs=a.get("weight"),
        jersey_number=a.get("jersey"),
        birth_date=a.get("dateOfBirth", "").split("T")[0] or None,
        birth_city=birth_place.get("city"),
        birth_state=birth_place.get("state"),
        birth_country=birth_place.get("country"),
        experience_years=a.get("experience", {}).get("years"),
        status=a.get("status", {}).get("name"),
        college=college,
        headshot_url=headshot_url,
        shoots_catches=shoots_catches,
        contract_salary=contract_salary,
        contract_season=contract_season,
        contract_total_value=contract_total_value,
        contract_years=contract_years,
        contract_expires=contract_expires,
        injury_status=injury_status,
    )


def pull_roster(conn, team, team_id, report):
    """Pull a team's roster from ESPN, upsert every player, then mark anyone who
    was on the roster but is missing tonight as departed (see roster_tracking.py
    for the safety rule). Returns the number of players ESPN listed."""
    previous_on_roster = count_on_roster(conn, team_id)
    cutoff = get_db_now(conn)  # players seen from here on get last_seen_at after this
    roster = fetch_json(
        f"{ESPN_BASE}/{team.sport_path}/teams/{team.espn_slug}/roster"
    )
    if team.grouped_roster:  # NHL/NFL: a list of position groups, each with "items"
        athletes = []
        for group in roster["athletes"]:
            log.debug(
                "%s group %s: %d players",
                team.label,
                group["position"],
                len(group["items"]),
            )
            athletes.extend(group["items"])
    else:  # NBA/NCAAB: a flat list of players
        athletes = roster["athletes"]

    for a in athletes:
        player_id = insert_roster_player(conn, team_id, team.league, a)
        log.debug("player_id %s: %s", player_id, a["fullName"])
    log.info("%s roster: %d players", team.label, len(athletes))

    departing = find_departing_players(conn, team_id, cutoff)
    decision = decide_departures(previous_on_roster, len(athletes), len(departing))
    if not decision.record:
        report.warn(f"{team.label} roster", decision.warning)
    elif departing:
        mark_players_departed(conn, [player_id for player_id, _name, _pos in departing])
        names = ", ".join(f"{name} ({pos})" for _id, name, pos in departing)
        log.info("%s departed (%d): %s", team.label, len(departing), names)
        report.count(f"{team.label} departed", len(departing))
        if decision.heads_up:
            report.warn(f"{team.label} roster", decision.heads_up)
    return len(athletes)


def main():
    setup_logging("pipeline")
    report = RunReport("pipeline")

    conn = None
    with report.step("Database connection"):
        conn = get_connection()
    if conn is None:  # nothing else can work without the database
        return report.finish()
    report.conn = conn  # so a failed step can roll back the connection

    try:
        # --- Teams and rosters. Order matters: it keeps database ids stable. ---
        team_ids = {}  # label -> team_id, only for teams that were inserted OK
        for team, identify in TRACKED_TEAMS:
            with report.step(f"{team.label} team"):
                team_ids[team.label] = pull_team(conn, team, identify)
            if team.label not in team_ids:
                continue  # no team row, so its roster and games can't be loaded
            with report.step(f"{team.label} roster"):
                players = pull_roster(conn, team, team_ids[team.label], report)
                report.count(f"{team.label} players", players)

        # --- Games (ESPN schedules) ---
        # Needs each tracked team's team_id, so it runs after the teams are inserted.
        for team, _identify in TRACKED_TEAMS:
            if team.label not in team_ids:
                continue
            with report.step(f"{team.label} games"):
                games = pull_games(
                    conn,
                    team.league,
                    team.sport_path,
                    team.espn_id,
                    team_ids[team.label],
                )
                report.count(f"{team.label} games", games)
                if games == 0:
                    report.warn(f"{team.label} games", "ESPN returned 0 games")

        # --- Game periods and box scores (ESPN per-game summaries) ---
        # After the games pull, so games that just went final get filled in.
        with report.step("Game periods"):
            report.count("periods filled", pull_game_periods(conn))
        with report.step("Box scores"):
            report.count("box score sides filled", pull_box_scores(conn))

        # --- Season/career rollups (rebuilt from player_game_stats) ---
        with report.step("Rollups"):
            season_rows, career_rows = rebuild_stat_rollups(conn)
            report.count("season rollup rows", season_rows)
            report.count("career rollup rows", career_rows)

        # --- Sanity checks on the finished data (warnings only; see sanity_checks.py) ---
        run_sanity_checks(conn, report, expected_tracked_teams=len(TRACKED_TEAMS))
    finally:
        conn.close()

    return report.finish()


if __name__ == "__main__":
    sys.exit(main())
