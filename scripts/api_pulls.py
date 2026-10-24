"""
Nightly pipeline: pulls teams, rosters, schedules, period scores and box scores
into Postgres, then rebuilds the season/career rollups.

Safe to rerun anytime: every write is an upsert. Run by cron at 4 AM (see README).

Which teams are collected comes from the league registry (leagues.py): every team in
the leagues named in LEAGUES_ALL, plus the featured teams in the other leagues.
Per-team work runs through report.each(...), so one team's failure is logged and
tolerated (a few percent) while an outage is a single loud error; everything else runs
inside report.step(...). The script exits 0 if everything worked and 1 if any step failed.
"""

import logging
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
    mark_players_departed,
    rebuild_stat_rollups,
    set_team_venue,
    upsert_league_team,
    upsert_opponent_team,
)
from dotenv import load_dotenv
from espn import fetch_summary, parse_periods, parse_team_box_score
from http_client import fetch_json
from leagues import FEATURED_TEAMS, LEAGUES, featured_teams, leagues_all
from log_setup import setup_logging
from roster_tracking import decide_departures
from run_report import RunReport
from sanity_checks import run_sanity_checks
from team_discovery import discover_teams

load_dotenv()

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


# --- Teams, rosters and schedules, league by league ---


@dataclass(frozen=True)
class TeamRef:
    """A team being processed tonight, once its row exists in the teams table."""

    league: object  # a leagues.League
    espn_id: str
    name: str
    team_id: int


def fetch_team_detail(league, espn_id):
    """(name, venue, city) from ESPN's detail page for one team."""
    team = fetch_json(f"{ESPN_BASE}/{league.sport_path}/teams/{espn_id}")["team"]
    venue, city = extract_team_venue_fields(team)
    return team["displayName"], venue, city


def refresh_featured_team(conn, league, featured):
    """Upsert a featured team and record its venue and city. The name and venue come
    from ESPN's detail page; the config's venue is used only when ESPN has none
    (it has none for college basketball). Returns a TeamRef."""
    name, venue, city = fetch_team_detail(league, featured.espn_id)
    team_id = upsert_league_team(
        conn,
        league.code,
        featured.espn_id,
        name,
        featured=True,
        founded_year=featured.founded_year,
    )
    set_team_venue(conn, team_id, venue or featured.venue, city or featured.city)
    log.info("%s refreshed, team_id %s | %s, %s", name, team_id, venue, city)
    return TeamRef(league, featured.espn_id, name, team_id)


def resolve_teams(conn, report, league, everyone):
    """Make sure every team we collect in this league has a row, and return
    (refs, expected_count): the teams to process tonight, and how many tracked teams
    the league should now have (None if the team list couldn't be fetched, so the
    sanity check skips this league).

    everyone=False: only the league's featured teams (usually one).
    everyone=True: every team ESPN lists, found by discover_teams()."""
    if not everyone:
        featured = featured_teams(league.code)
        results = report.each(
            f"{league.code} teams",
            featured,
            lambda ft: refresh_featured_team(conn, league, ft),
            name=lambda ft: ft.label,
        )
        return [ref for _ft, ref in results], len(featured)

    discovered = []
    with report.step(f"{league.code} team list"):
        discovered = discover_teams(league)
    if not discovered:
        return [], None

    featured_by_id = {ft.espn_id: ft for ft in featured_teams(league.code)}

    def upsert(team):
        ft = featured_by_id.get(team.espn_id)
        team_id = upsert_league_team(
            conn,
            league.code,
            team.espn_id,
            team.name,
            featured=ft is not None,
            founded_year=ft.founded_year if ft else None,
        )
        return TeamRef(league, team.espn_id, team.name, team_id)

    results = report.each(
        f"{league.code} team rows", discovered, upsert, name=lambda t: t.name
    )
    refs = [ref for _team, ref in results]

    # Featured teams also get their venue refreshed from ESPN's detail page
    refs_by_id = {ref.espn_id: ref for ref in refs}
    featured_here = [ft for ft in featured_by_id.values() if ft.espn_id in refs_by_id]

    def refresh_venue(ft):
        _name, venue, city = fetch_team_detail(league, ft.espn_id)
        set_team_venue(
            conn, refs_by_id[ft.espn_id].team_id, venue or ft.venue, city or ft.city
        )

    report.each(
        f"{league.code} featured venues",
        featured_here,
        refresh_venue,
        name=lambda ft: ft.label,
    )
    return refs, len(discovered)


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


def roster_athletes(roster):
    """The players in an ESPN roster reply, flattened. NBA, WNBA and college basketball
    rosters are a flat list of players; NFL, NHL, MLB and college football rosters are a
    list of position groups, each holding its players under "items"."""
    athletes = roster["athletes"]
    if athletes and "items" in athletes[0]:
        return [player for group in athletes for player in group["items"]]
    return athletes


def pull_roster(conn, ref, report):
    """Pull a team's roster from ESPN, upsert every player, then mark anyone who
    was on the roster but is missing tonight as departed (see roster_tracking.py
    for the safety rule). Returns the number of players ESPN listed."""
    previous_on_roster = count_on_roster(conn, ref.team_id)
    cutoff = get_db_now(conn)  # players seen from here on get last_seen_at after this
    roster = fetch_json(f"{ESPN_BASE}/{ref.league.sport_path}/teams/{ref.espn_id}/roster")
    athletes = roster_athletes(roster)

    for a in athletes:
        player_id = insert_roster_player(conn, ref.team_id, ref.league.code, a)
        log.debug("player_id %s: %s", player_id, a["fullName"])
    log.info("%s roster: %d players", ref.name, len(athletes))

    departing = find_departing_players(conn, ref.team_id, cutoff)
    decision = decide_departures(previous_on_roster, len(athletes), len(departing))
    if not decision.record:
        report.warn(f"{ref.name} roster", decision.warning)
    elif departing:
        mark_players_departed(conn, [player_id for player_id, _name, _pos in departing])
        names = ", ".join(f"{name} ({pos})" for _id, name, pos in departing)
        log.info("%s departed (%d): %s", ref.name, len(departing), names)
        report.add_count(f"{ref.league.code} departed", len(departing))
        if decision.heads_up:
            report.warn(f"{ref.name} roster", decision.heads_up)
    return len(athletes)


def main():
    setup_logging("pipeline")
    report = RunReport("pipeline")

    everyone = set()
    with report.step("Settings"):
        everyone = set(leagues_all())  # a typo in LEAGUES_ALL raises here
    if report.errors:  # don't guess which leagues were meant
        return report.finish()

    conn = None
    with report.step("Database connection"):
        conn = get_connection()
    if conn is None:  # nothing else can work without the database
        return report.finish()
    report.conn = conn  # so a failed step can roll back the connection

    try:
        # --- Teams and rosters, league by league. The order is the registry's: it
        # keeps database ids stable (see leagues.py). ---
        teams_by_league = {}  # league code -> [TeamRef]
        expected_tracked = {}  # league code -> tracked teams it should now have
        for league in LEAGUES.values():
            everyone_here = league.code in everyone
            if not everyone_here and not featured_teams(league.code):
                continue  # nothing is collected in this league
            refs, expected = resolve_teams(conn, report, league, everyone_here)
            teams_by_league[league.code] = refs
            if expected is not None:
                expected_tracked[league.code] = expected
            if not refs:
                continue  # no team rows, so no rosters or games can be loaded
            results = report.each(
                f"{league.code} rosters",
                refs,
                lambda ref: pull_roster(conn, ref, report),
                name=lambda ref: ref.name,
            )
            report.count(f"{league.code} players", sum(n for _ref, n in results))

        # --- Games (ESPN schedules). Needs every team's team_id, so it runs after
        # all the team rows exist. ---
        for code, refs in teams_by_league.items():
            if not refs:
                continue
            results = report.each(
                f"{code} games",
                refs,
                lambda ref: pull_games(
                    conn, ref.league.code, ref.league.sport_path, ref.espn_id, ref.team_id
                ),
                name=lambda ref: ref.name,
            )
            games = sum(n for _ref, n in results)
            report.count(f"{code} games", games)
            if results and games == 0:
                report.warn(f"{code} games", "ESPN returned 0 games for every team")

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
        run_sanity_checks(
            conn,
            report,
            expected_tracked=expected_tracked,
            featured={(ft.league, ft.espn_id) for ft in FEATURED_TEAMS},
        )
    finally:
        conn.close()

    return report.finish()


if __name__ == "__main__":
    sys.exit(main())
