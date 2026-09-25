import os

import psycopg2
from dotenv import load_dotenv

load_dotenv()


def get_connection():
    """Open a new connection to the sports_hub Postgres database."""
    return psycopg2.connect(
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT"),
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
    )


def insert_team(
    conn,
    league,
    external_id,
    name,
    espn_id=None,
    venue=None,
    city=None,
    capacity=None,
    founded_year=None,
):
    """
    Insert one of our tracked teams into the teams table.
    If a team with the same (league, external_id) already exists,
    update its enrichment fields and updated_at timestamp instead of erroring out.
    Returns the team_id.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO teams (league, external_id, name, espn_id, is_tracked,
                               venue, city, capacity, founded_year)
            VALUES (%s, %s, %s, %s, true, %s, %s, %s, %s)
            ON CONFLICT (league, external_id)
            DO UPDATE SET
                name = EXCLUDED.name,
                espn_id = COALESCE(EXCLUDED.espn_id, teams.espn_id),
                is_tracked = true,
                venue = EXCLUDED.venue,
                city = EXCLUDED.city,
                capacity = EXCLUDED.capacity,
                founded_year = EXCLUDED.founded_year,
                updated_at = now()
            RETURNING team_id;
            """,
            (league, external_id, name, espn_id, venue, city, capacity, founded_year),
        )
        team_id = cur.fetchone()[0]
    conn.commit()
    return team_id


def upsert_opponent_team(conn, league, espn_id, name):
    """
    Insert an opponent team (one we don't track) into the teams table,
    keyed on (league, espn_id). Used by the games pull so every game's
    home/away team has a row to point at. Only touches name/updated_at,
    so it never changes is_tracked, external_id, or venue fields.
    Returns the team_id.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO teams (league, espn_id, name)
            VALUES (%s, %s, %s)
            ON CONFLICT (league, espn_id)
            DO UPDATE SET
                name = EXCLUDED.name,
                updated_at = now()
            RETURNING team_id;
            """,
            (league, espn_id, name),
        )
        team_id = cur.fetchone()[0]
    conn.commit()
    return team_id


def insert_player(
    conn,
    team_id,
    league,
    external_id,
    name,
    position,
    height_inches=None,
    weight_lbs=None,
    jersey_number=None,
    birth_date=None,
    birth_city=None,
    birth_state=None,
    birth_country=None,
    experience_years=None,
    status=None,
    college=None,
    headshot_url=None,
    shoots_catches=None,
    contract_salary=None,
    contract_season=None,
    contract_total_value=None,
    contract_years=None,
    contract_expires=None,
    injury_status=None,
    draft_year=None,
    draft_round=None,
    draft_pick=None,
):
    """
    Insert a player into the players table.
    Upserts on (league, external_id).
    Returns the player_id.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO players (
                team_id, league, external_id, name, position,
                height_inches, weight_lbs, jersey_number,
                birth_date, birth_city, birth_state, birth_country,
                experience_years, status, college, headshot_url,
                shoots_catches,
                contract_salary, contract_season,
                contract_total_value, contract_years, contract_expires,
                injury_status, draft_year, draft_round, draft_pick
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (league, external_id)
            DO UPDATE SET
                name = EXCLUDED.name,
                position = EXCLUDED.position,
                team_id = EXCLUDED.team_id,
                height_inches = EXCLUDED.height_inches,
                weight_lbs = EXCLUDED.weight_lbs,
                jersey_number = EXCLUDED.jersey_number,
                birth_date = EXCLUDED.birth_date,
                birth_city = EXCLUDED.birth_city,
                birth_state = EXCLUDED.birth_state,
                birth_country = EXCLUDED.birth_country,
                experience_years = EXCLUDED.experience_years,
                status = EXCLUDED.status,
                college = EXCLUDED.college,
                headshot_url = EXCLUDED.headshot_url,
                shoots_catches = EXCLUDED.shoots_catches,
                contract_salary = EXCLUDED.contract_salary,
                contract_season = EXCLUDED.contract_season,
                contract_total_value = EXCLUDED.contract_total_value,
                contract_years = EXCLUDED.contract_years,
                contract_expires = EXCLUDED.contract_expires,
                injury_status = EXCLUDED.injury_status,
                draft_year = EXCLUDED.draft_year,
                draft_round = EXCLUDED.draft_round,
                draft_pick = EXCLUDED.draft_pick,
                updated_at = now()
            RETURNING player_id;
            """,
            (
                team_id,
                league,
                external_id,
                name,
                position,
                height_inches,
                weight_lbs,
                jersey_number,
                birth_date,
                birth_city,
                birth_state,
                birth_country,
                experience_years,
                status,
                college,
                headshot_url,
                shoots_catches,
                contract_salary,
                contract_season,
                contract_total_value,
                contract_years,
                contract_expires,
                injury_status,
                draft_year,
                draft_round,
                draft_pick,
            ),
        )
        player_id = cur.fetchone()[0]
    conn.commit()
    return player_id


def insert_game(
    conn,
    league,
    external_id,
    season_year,
    home_team_id,
    away_team_id,
    game_time,
    status,
    home_score=None,
    away_score=None,
    venue_name=None,
    is_neutral_site=False,
):
    """
    Insert a game into the games table.
    Upserts on (league, external_id), so rerunning refreshes status,
    scores, and schedule changes (e.g. a new start time) in place.
    Returns the game_id.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO games (
                league, external_id, season_year,
                home_team_id, away_team_id, game_time, status,
                home_score, away_score, venue_name, is_neutral_site
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (league, external_id)
            DO UPDATE SET
                season_year = EXCLUDED.season_year,
                home_team_id = EXCLUDED.home_team_id,
                away_team_id = EXCLUDED.away_team_id,
                game_time = EXCLUDED.game_time,
                status = EXCLUDED.status,
                home_score = EXCLUDED.home_score,
                away_score = EXCLUDED.away_score,
                venue_name = EXCLUDED.venue_name,
                is_neutral_site = EXCLUDED.is_neutral_site,
                last_updated = now()
            RETURNING game_id;
            """,
            (
                league,
                external_id,
                season_year,
                home_team_id,
                away_team_id,
                game_time,
                status,
                home_score,
                away_score,
                venue_name,
                is_neutral_site,
            ),
        )
        game_id = cur.fetchone()[0]
    conn.commit()
    return game_id
