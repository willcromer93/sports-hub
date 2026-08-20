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


def insert_team(conn, league, external_id, name):
    """
    Insert a team into the teams table.
    If a team with the same (league, external_id) already exists,
    update its name and updated_at timestamp instead of erroring out.
    Returns the team_id.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO teams (league, external_id, name)
            VALUES (%s, %s, %s)
            ON CONFLICT (league, external_id)
            DO UPDATE SET name = EXCLUDED.name, updated_at = now()
            RETURNING team_id;
            """,
            (league, external_id, name),
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
