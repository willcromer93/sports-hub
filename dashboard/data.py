"""
Every database query the dashboard runs lives here, as plain SQL.

Each function returns a pandas DataFrame (a table in memory). They're wrapped
in @st.cache_data, which remembers a function's result for CACHE_SECONDS: the
first page load runs the query, and every click after that reuses the answer
instead of asking Postgres again. The data only changes nightly, so that's
safe — and the sidebar's "Refresh data" button clears the cache on demand.
"""

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

# Reuse get_connection() from scripts/db.py so the dashboard reads the same
# .env credentials as the pipeline, instead of keeping a second copy.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from db import get_connection  # noqa: E402
from espn import fetch_summary  # noqa: E402

from config import PLAYING_TIME  # noqa: E402

CACHE_SECONDS = 600

# Pregame previews come live from ESPN (nothing is stored), refreshed hourly.
PREGAME_CACHE_SECONDS = 3600


def run_query(sql, params=None):
    """Run a SELECT and return its rows as a DataFrame."""
    # Values picked out of a DataFrame are numpy types (numpy.int64), which
    # psycopg2 can't send to Postgres — .item() turns them into plain Python.
    if params:
        params = {k: v.item() if hasattr(v, "item") else v for k, v in params.items()}
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            columns = [col.name for col in cur.description]
            return pd.DataFrame(cur.fetchall(), columns=columns)
    finally:
        conn.close()


@st.cache_data(ttl=CACHE_SECONDS)
def tracked_teams():
    return run_query(
        """
        SELECT team_id, league, name, espn_id, venue, city, founded_year
        FROM teams
        WHERE is_tracked
        ORDER BY name;
        """
    )


@st.cache_data(ttl=CACHE_SECONDS)
def team_games(team_id):
    """
    Every game for one team, seen from that team's side: which team is the
    opponent, and our score vs. theirs — no matter if we were home or away.
    """
    df = run_query(
        """
        SELECT g.game_id,
               g.external_id,
               g.league,
               g.season_year,
               g.season_type,
               g.game_time,
               g.status,
               g.venue_name,
               g.is_neutral_site,
               g.home_team_id = %(team_id)s AS is_home,
               opp.team_id AS opponent_id,
               opp.name AS opponent,
               CASE WHEN g.home_team_id = %(team_id)s
                    THEN g.home_score ELSE g.away_score END AS team_score,
               CASE WHEN g.home_team_id = %(team_id)s
                    THEN g.away_score ELSE g.home_score END AS opp_score,
               -- Went past regulation? (drives "OT" labels and NHL OT losses)
               EXISTS (
                   SELECT 1 FROM game_periods gp
                   WHERE gp.game_id = g.game_id
                     AND gp.period_type <> 'regulation'
               ) AS extra_time,
               EXISTS (
                   SELECT 1 FROM game_periods gp
                   WHERE gp.game_id = g.game_id
                     AND gp.period_type = 'shootout'
               ) AS shootout,
               EXISTS (
                   SELECT 1 FROM player_game_appearances a
                   WHERE a.game_id = g.game_id AND a.team_id = %(team_id)s
               ) AS has_box_score
        FROM games g
        JOIN teams opp
          ON opp.team_id = CASE WHEN g.home_team_id = %(team_id)s
                                THEN g.away_team_id ELSE g.home_team_id END
        WHERE %(team_id)s IN (g.home_team_id, g.away_team_id)
        ORDER BY g.game_time;
        """,
        {"team_id": team_id},
    )
    df["game_time"] = pd.to_datetime(df["game_time"], utc=True)
    return df


@st.cache_data(ttl=CACHE_SECONDS)
def all_teams():
    """Every team (tracked and opponents), for looking up names by team_id."""
    return run_query("SELECT team_id, league, name, is_tracked FROM teams;")


@st.cache_data(ttl=CACHE_SECONDS)
def all_players():
    """Name and position for every player, for labelling opponent stat tables."""
    return run_query("SELECT player_id, name, position FROM players;")


@st.cache_data(ttl=CACHE_SECONDS)
def game_periods(game_id):
    """The line score for one game, one row per period, plus the league's label."""
    return run_query(
        """
        SELECT gp.period_number, gp.period_type, gp.home_score, gp.away_score,
               l.period_label, l.regulation_periods
        FROM game_periods gp
        JOIN games g ON g.game_id = gp.game_id
        JOIN sport_period_labels l ON l.league = g.league
        WHERE gp.game_id = %(game_id)s
        ORDER BY CASE gp.period_type
                     WHEN 'regulation' THEN 1
                     WHEN 'overtime' THEN 2
                     ELSE 3
                 END,
                 gp.period_number;
        """,
        {"game_id": game_id},
    )


@st.cache_data(ttl=CACHE_SECONDS)
def game_header(game_id):
    """Both teams, scores, and details for one game."""
    return run_query(
        """
        SELECT g.game_id, g.league, g.game_time, g.status, g.venue_name,
               g.season_type, g.home_score, g.away_score,
               g.home_team_id, g.away_team_id,
               home.name AS home_team, away.name AS away_team
        FROM games g
        JOIN teams home ON home.team_id = g.home_team_id
        JOIN teams away ON away.team_id = g.away_team_id
        WHERE g.game_id = %(game_id)s;
        """,
        {"game_id": game_id},
    )


@st.cache_data(ttl=CACHE_SECONDS)
def player_stat_rows(
    team_id, season_year=None, season_type=None, game_id=None, opponents=False
):
    """
    Player stats in long format — one row per player, per game, per stat —
    for a team's games, optionally narrowed to one season/season type or to
    a single game. stats.py pivots these into tables.

    opponents=False: the team's own players.
    opponents=True:  the players who played *against* the team in its games.
    Which side a player was on comes from player_game_appearances.team_id.

    Playing time is stored separately (player_game_appearances), so it's
    UNIONed in as if it were one more stat named PLAYING_TIME.
    """
    side = (
        "a.team_id <> %(team_id)s AND %(team_id)s IN (g.home_team_id, g.away_team_id)"
        if opponents
        else "a.team_id = %(team_id)s"
    )
    filters = f"""
        {side}
        AND (%(season_year)s::int IS NULL OR g.season_year = %(season_year)s)
        AND (%(season_type)s::text IS NULL OR g.season_type = %(season_type)s)
        AND (%(game_id)s::int IS NULL OR g.game_id = %(game_id)s)
    """
    return run_query(
        f"""
        SELECT s.game_id, s.player_id, a.team_id, s.stat_name,
               s.stat_value::float8 AS value
        FROM player_game_stats s
        JOIN player_game_appearances a
          ON a.game_id = s.game_id AND a.player_id = s.player_id
        JOIN games g ON g.game_id = s.game_id
        WHERE {filters}

        UNION ALL

        SELECT a.game_id, a.player_id, a.team_id, %(playing_time)s,
               a.seconds_played::float8
        FROM player_game_appearances a
        JOIN games g ON g.game_id = a.game_id
        WHERE {filters}
          AND a.did_play
          AND a.seconds_played IS NOT NULL;
        """,
        {
            "team_id": team_id,
            "season_year": season_year,
            "season_type": season_type,
            "game_id": game_id,
            "playing_time": PLAYING_TIME,
        },
    )


@st.cache_data(ttl=CACHE_SECONDS)
def players(team_id):
    """
    Everyone on the current roster, plus anyone who has a box score line for
    this team (e.g. a preseason cut), with bio details for the Player page.
    """
    return run_query(
        """
        SELECT p.player_id, p.name, p.position, p.jersey_number,
               p.height_inches, p.weight_lbs, p.birth_date, p.birth_city,
               p.birth_state, p.birth_country, p.experience_years, p.college,
               p.headshot_url, p.shoots_catches, p.contract_salary,
               p.contract_expires, p.injury_status, p.status,
               p.team_id = %(team_id)s AS on_roster
        FROM players p
        WHERE p.team_id = %(team_id)s
           OR p.player_id IN (
                SELECT a.player_id
                FROM player_game_appearances a
                WHERE a.team_id = %(team_id)s
           )
        ORDER BY p.name;
        """,
        {"team_id": team_id},
    )


# ---------------------------------------------------------------------------
# Pregame preview — live from ESPN, not from Postgres
# ---------------------------------------------------------------------------


@st.cache_data(ttl=PREGAME_CACHE_SECONDS, show_spinner="Loading preview from ESPN…")
def pregame(league, event_id):
    """
    ESPN's pregame preview for one upcoming game, trimmed to what the
    Game Preview page shows. Nothing is saved to the database — it's asked
    for when the page opens and cached for an hour, so there's nothing to
    clean up after the game.

    Returns a dict keyed by ESPN team id:
        {espn_team_id: {"name", "short", "logo", "home_away", "record",
                        "team_stats", "leaders", "injuries", "last_five"}}
    or None if ESPN can't be reached.
    """
    try:
        summary = fetch_summary(league, event_id)
    except Exception:  # network error, timeout, or a non-JSON reply
        return None

    teams = {}
    competition = summary.get("header", {}).get("competitions", [{}])[0]
    for competitor in competition.get("competitors", []):
        team = competitor["team"]
        records = {
            r.get("type"): r.get("summary") for r in competitor.get("record", [])
        }
        teams[team["id"]] = {
            "name": team.get("displayName"),
            "short": team.get("shortDisplayName") or team.get("name"),
            "logo": (team.get("logos") or [{}])[0].get("href"),
            "home_away": competitor.get("homeAway"),
            "record": records.get("total"),
            "team_stats": {},
            "leaders": [],
            "injuries": [],
            "last_five": [],
        }

    # Season team stats, e.g. {"Points Per Game": "26.5", ...}
    for team_box in summary.get("boxscore", {}).get("teams", []):
        team_id = team_box["team"]["id"]
        if team_id in teams:
            teams[team_id]["team_stats"] = {
                stat.get("label") or stat.get("name"): stat.get("displayValue")
                for stat in team_box.get("statistics", [])
            }

    # Season leaders per category, e.g. Passing Yards: Daniel Jones, 376 YDS
    for team_leaders in summary.get("leaders", []):
        team_id = team_leaders.get("team", {}).get("id")
        if team_id not in teams:
            continue
        for category in team_leaders.get("leaders", []):
            if not category.get("leaders"):
                continue
            top = category["leaders"][0]
            athlete = top.get("athlete", {})
            teams[team_id]["leaders"].append(
                {
                    "category": category.get("displayName"),
                    "player": athlete.get("displayName"),
                    "position": athlete.get("position", {}).get("abbreviation"),
                    "headshot": athlete.get("headshot", {}).get("href"),
                    "line": top.get("displayValue"),
                }
            )

    # Injury report
    for team_injuries in summary.get("injuries", []):
        team_id = team_injuries.get("team", {}).get("id")
        if team_id not in teams:
            continue
        for injury in team_injuries.get("injuries", []):
            athlete = injury.get("athlete", {})
            teams[team_id]["injuries"].append(
                {
                    "Player": athlete.get("displayName"),
                    "Pos": athlete.get("position", {}).get("abbreviation"),
                    "Status": injury.get("status"),
                    "Injury": injury.get("details", {}).get("type"),
                }
            )

    # Last five games
    for team_games_ in summary.get("lastFiveGames", []):
        team_id = team_games_.get("team", {}).get("id")
        if team_id not in teams:
            continue
        for event in team_games_.get("events", []):
            # ESPN writes the winner's score first ("33-30"); flip losses so
            # the team's own score comes first, like the rest of the dashboard.
            # A score can carry a suffix ("1-0 SO"), so split that off first.
            result = event.get("gameResult", "")
            score, _, suffix = event.get("score", "").partition(" ")
            if result == "L" and "-" in score:
                score = "-".join(reversed(score.split("-")))
            score = f"{score} {suffix}".strip()
            teams[team_id]["last_five"].append(
                {
                    "Date": event.get("gameDate"),
                    "Game": f"{event.get('atVs', '')} "
                    f"{event.get('opponent', {}).get('displayName', '')}",
                    "Result": f"{result} {score.replace('-', '–')}",
                }
            )
    return teams
