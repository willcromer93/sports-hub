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
    season_type,
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
                league, external_id, season_year, season_type,
                home_team_id, away_team_id, game_time, status,
                home_score, away_score, venue_name, is_neutral_site
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (league, external_id)
            DO UPDATE SET
                season_year = EXCLUDED.season_year,
                season_type = EXCLUDED.season_type,
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
                season_type,
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


def get_games_missing_periods(conn):
    """
    Find final games that don't have any game_periods rows yet, so the
    per-period pull only requests games it hasn't already filled in.
    Returns a list of (game_id, league, external_id, regulation_periods) tuples.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT g.game_id, g.league, g.external_id, l.regulation_periods
            FROM games g
            JOIN sport_period_labels l ON l.league = g.league
            WHERE g.status = 'final'
              AND NOT EXISTS (
                  SELECT 1 FROM game_periods p WHERE p.game_id = g.game_id
              )
            ORDER BY g.game_time;
            """
        )
        return cur.fetchall()


def insert_game_periods(conn, game_id, periods, replace=False):
    """
    Insert all of one game's period rows into game_periods.
    `periods` is a list of (period_number, period_type, home_score, away_score).
    Upserts on (game_id, period_number, period_type). With replace=True, the
    game's existing period rows are deleted first (used when ESPN corrects a
    game). Commits once at the end, so a game gets either all of its periods
    or none of them.
    """
    with conn.cursor() as cur:
        if replace:
            cur.execute("DELETE FROM game_periods WHERE game_id = %s;", (game_id,))
        for period_number, period_type, home_score, away_score in periods:
            cur.execute(
                """
                INSERT INTO game_periods (
                    game_id, period_number, period_type, home_score, away_score
                )
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (game_id, period_number, period_type)
                DO UPDATE SET
                    home_score = EXCLUDED.home_score,
                    away_score = EXCLUDED.away_score;
                """,
                (game_id, period_number, period_type, home_score, away_score),
            )
    conn.commit()


def get_games_missing_box_scores(conn):
    """
    Find each side of a final game that doesn't have a box score yet — both
    our team and the opponent, checked separately, so a game where only one
    side was stored (e.g. games loaded before opponents were kept) gets just
    the missing side filled in.
    Returns a list of (game_id, league, external_id, team_id, espn_id) tuples,
    one per missing side.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT g.game_id, g.league, g.external_id, t.team_id, t.espn_id
            FROM games g
            JOIN teams t ON t.team_id IN (g.home_team_id, g.away_team_id)
            WHERE g.status = 'final'
              AND NOT EXISTS (
                  SELECT 1 FROM player_game_appearances a
                  WHERE a.game_id = g.game_id AND a.team_id = t.team_id
              )
            ORDER BY g.game_time, t.is_tracked DESC;
            """
        )
        return cur.fetchall()


def upsert_box_score_player(conn, team_id, league, external_id, name):
    """
    Return the player_id for a player found in a box score, adding a minimal
    players row if they aren't there yet (e.g. a preseason cut who was never
    on a roster pull). An existing player is left completely unchanged —
    the no-op "SET name = players.name" is only there so RETURNING works,
    since ON CONFLICT DO NOTHING returns no row.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO players (team_id, league, external_id, name)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (league, external_id)
            DO UPDATE SET name = players.name
            RETURNING player_id;
            """,
            (team_id, league, external_id, name),
        )
        player_id = cur.fetchone()[0]
    conn.commit()
    return player_id


def box_score_rows(conn, team_id, league, parsed):
    """
    Turn a parsed ESPN box score ({espn_athlete_id: {...}}, from
    espn.parse_team_box_score) into the rows insert_box_score expects,
    looking up (or adding) each player's player_id.
    """
    rows = []
    for espn_athlete_id, player in parsed.items():
        player_id = upsert_box_score_player(
            conn, team_id, league, espn_athlete_id, player["name"]
        )
        rows.append(
            (player_id, player["did_play"], player["seconds_played"], player["stats"])
        )
    return rows


def insert_box_score(conn, game_id, team_id, box_score, replace=False):
    """
    Insert one team's side of a game's box score into player_game_appearances
    and player_game_stats. `box_score` is a list of
    (player_id, did_play, seconds_played, stats), where stats is a dict of
    {stat_name: stat_value}. Upserts both tables. With replace=True, that
    team's existing rows for the game are deleted first (the other team's
    side is left alone), so a stat or player ESPN has since removed doesn't
    linger. Commits once at the end, so a side gets either its whole box
    score or none of it.
    """
    with conn.cursor() as cur:
        if replace:
            # Stats have no team_id of their own, so match them through the
            # appearance rows for this team's side before those are deleted.
            cur.execute(
                """
                DELETE FROM player_game_stats s
                USING player_game_appearances a
                WHERE a.game_id = s.game_id
                  AND a.player_id = s.player_id
                  AND a.game_id = %s
                  AND a.team_id = %s;
                """,
                (game_id, team_id),
            )
            cur.execute(
                """
                DELETE FROM player_game_appearances
                WHERE game_id = %s AND team_id = %s;
                """,
                (game_id, team_id),
            )
        for player_id, did_play, seconds_played, stats in box_score:
            cur.execute(
                """
                INSERT INTO player_game_appearances (
                    game_id, player_id, team_id, did_play, seconds_played
                )
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (game_id, player_id)
                DO UPDATE SET
                    team_id = EXCLUDED.team_id,
                    did_play = EXCLUDED.did_play,
                    seconds_played = EXCLUDED.seconds_played;
                """,
                (game_id, player_id, team_id, did_play, seconds_played),
            )
            for stat_name, stat_value in stats.items():
                cur.execute(
                    """
                    INSERT INTO player_game_stats (
                        game_id, player_id, stat_name, stat_value
                    )
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (game_id, player_id, stat_name)
                    DO UPDATE SET stat_value = EXCLUDED.stat_value;
                    """,
                    (game_id, player_id, stat_name, stat_value),
                )
    conn.commit()


def get_recent_final_games(conn, days):
    """
    Final games played in the last `days` days — the ones the weekly refresh
    re-checks for ESPN stat corrections. Returns a list of
    (game_id, league, external_id, regulation_periods, sides), where sides is
    [(team_id, espn_id), ...] for both teams — box scores are checked for
    each side separately.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT g.game_id, g.league, g.external_id, l.regulation_periods,
                   home.team_id, home.espn_id, away.team_id, away.espn_id
            FROM games g
            JOIN sport_period_labels l ON l.league = g.league
            JOIN teams home ON home.team_id = g.home_team_id
            JOIN teams away ON away.team_id = g.away_team_id
            WHERE g.status = 'final'
              AND g.game_time >= now() - make_interval(days => %s)
            ORDER BY g.game_time;
            """,
            (days,),
        )
        games = []
        for row in cur.fetchall():
            game_id, league, external_id, regulation_periods = row[:4]
            home_id, home_espn_id, away_id, away_espn_id = row[4:]
            sides = [(home_id, home_espn_id), (away_id, away_espn_id)]
            games.append((game_id, league, external_id, regulation_periods, sides))
        return games


def get_game_periods(conn, game_id):
    """
    One game's stored period rows, as a list of
    (period_number, period_type, home_score, away_score) — the same shape
    espn.parse_periods returns, so the two can be compared directly.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT period_number, period_type, home_score, away_score
            FROM game_periods
            WHERE game_id = %s;
            """,
            (game_id,),
        )
        return cur.fetchall()


def get_box_score(conn, game_id, team_id):
    """
    One team's side of a game's stored box score, as
    {espn_athlete_id: {"name", "did_play", "seconds_played", "stats"}} — the
    same shape espn.parse_team_box_score returns, so the two can be compared
    directly. Stat values come back from Postgres as Decimal, so they're
    converted to float to match what's parsed from ESPN.
    """
    box_score = {}
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT p.external_id, p.name, a.did_play, a.seconds_played
            FROM player_game_appearances a
            JOIN players p ON p.player_id = a.player_id
            WHERE a.game_id = %s AND a.team_id = %s;
            """,
            (game_id, team_id),
        )
        for external_id, name, did_play, seconds_played in cur.fetchall():
            box_score[external_id] = {
                "name": name,
                "did_play": did_play,
                "seconds_played": seconds_played,
                "stats": {},
            }

        cur.execute(
            """
            SELECT p.external_id, s.stat_name, s.stat_value
            FROM player_game_stats s
            JOIN player_game_appearances a
              ON a.game_id = s.game_id AND a.player_id = s.player_id
            JOIN players p ON p.player_id = s.player_id
            WHERE s.game_id = %s AND a.team_id = %s;
            """,
            (game_id, team_id),
        )
        for external_id, stat_name, stat_value in cur.fetchall():
            box_score[external_id]["stats"][stat_name] = float(stat_value)
    return box_score


# Stats that can't be added up across games: percentages, per-attempt
# averages, ratings, and "longest" plays (e.g. savePct, yardsPerRushAttempt,
# QBRating, longRushing). They're matched on the part of the stat name after
# any NFL category prefix ("rushing.longRushing" -> "longRushing") and left
# out of the season/career rollups. Season versions of the rates can be
# recomputed from the totals instead (season savePct = saves / shotsAgainst);
# season "longest" values are MAX(stat_value) straight from player_game_stats.
NON_ADDITIVE_STAT_PATTERN = r"(Pct|Percent|Avg|QBR|QBRating)|^yardsPer|^long"

# SQL condition shared by both rollups: keep only additive stats.
_ADDITIVE_STATS_ONLY = r"regexp_replace(s.stat_name, '^.*\.', '') !~ %(non_additive)s"


def rebuild_stat_rollups(conn):
    """
    Recompute player_season_stats and player_career_stats from
    player_game_stats. Both are rebuilt from scratch (delete + insert)
    rather than upserted, so a stat corrected or removed by the weekly
    refresh can't leave a stale total behind. The data is small enough that
    a full rebuild takes well under a second. Done in one transaction, so
    anything reading the tables never sees them half-built.

    games_played is per stat: the number of games that stat was recorded
    for the player (e.g. an NFL receiver's passing stats only count games
    where he threw a pass). "Career" means every game in our database —
    our tracked teams since data collection began — not a player's full career.

    Only our tracked teams' players are rolled up. Opponents' box scores are
    stored too, but a total over "the games they happened to play against
    us" isn't a real season or career line; the dashboard aggregates those
    straight from player_game_stats instead.

    Returns (season_rows, career_rows).
    """
    params = {"non_additive": NON_ADDITIVE_STAT_PATTERN}
    with conn.cursor() as cur:
        cur.execute("DELETE FROM player_season_stats;")
        cur.execute(
            f"""
            INSERT INTO player_season_stats (
                player_id, team_id, season_year, season_type, stat_name,
                games_played, total_value, avg_value, max_value
            )
            SELECT s.player_id, a.team_id, g.season_year, g.season_type, s.stat_name,
                   COUNT(*), SUM(s.stat_value), AVG(s.stat_value), MAX(s.stat_value)
            FROM player_game_stats s
            JOIN games g ON g.game_id = s.game_id
            -- The team the player played for in that game comes from their
            -- appearance row, not players.team_id (their current team,
            -- which goes stale after a trade).
            JOIN player_game_appearances a
              ON a.game_id = s.game_id AND a.player_id = s.player_id
            JOIN teams t ON t.team_id = a.team_id AND t.is_tracked
            WHERE {_ADDITIVE_STATS_ONLY}
            GROUP BY s.player_id, a.team_id, g.season_year, g.season_type, s.stat_name;
            """,
            params,
        )
        season_rows = cur.rowcount

        cur.execute("DELETE FROM player_career_stats;")
        cur.execute(
            f"""
            INSERT INTO player_career_stats (
                player_id, season_type, stat_name,
                games_played, total_value, avg_value, max_value
            )
            SELECT s.player_id, g.season_type, s.stat_name,
                   COUNT(*), SUM(s.stat_value), AVG(s.stat_value), MAX(s.stat_value)
            FROM player_game_stats s
            JOIN games g ON g.game_id = s.game_id
            JOIN player_game_appearances a
              ON a.game_id = s.game_id AND a.player_id = s.player_id
            JOIN teams t ON t.team_id = a.team_id AND t.is_tracked
            WHERE {_ADDITIVE_STATS_ONLY}
            GROUP BY s.player_id, g.season_type, s.stat_name;
            """,
            params,
        )
        career_rows = cur.rowcount
    conn.commit()
    return season_rows, career_rows
