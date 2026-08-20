-- ============================================
-- teams: one row per team
-- ============================================
CREATE TABLE teams (
    team_id     SERIAL PRIMARY KEY,
    league      TEXT NOT NULL,          -- 'NBA', 'NCAAB', 'NHL', 'NFL'
    external_id TEXT NOT NULL,          -- ID used by that team's source API
    name        TEXT NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (league, external_id)
);

-- ============================================
-- players: one row per player
-- ============================================dd

CREATE TABLE players (
    player_id             SERIAL PRIMARY KEY,
    team_id               INTEGER REFERENCES teams(team_id),
    league                TEXT NOT NULL,
    external_id           TEXT NOT NULL,
    name                  TEXT NOT NULL,
    position              TEXT,
    height_inches         INTEGER,
    weight_lbs            INTEGER,
    jersey_number          TEXT,
    birth_date            DATE,
    birth_city            TEXT,
    birth_state           TEXT,
    birth_country          TEXT,
    experience_years       INTEGER,
    status                 TEXT,
    college                TEXT,
    headshot_url            TEXT,
    shoots_catches          TEXT,
    contract_salary          NUMERIC,
    contract_season          INTEGER,
    contract_total_value      NUMERIC,
    contract_years            INTEGER,
    contract_expires          DATE,
    injury_status             TEXT,
    draft_year                INTEGER,
    draft_round                INTEGER,
    draft_pick                 INTEGER,
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (league, external_id)
);

-- ============================================
-- games: one row per game
-- ============================================
CREATE TABLE games (
    game_id        SERIAL PRIMARY KEY,
    team_id        INTEGER NOT NULL REFERENCES teams(team_id),
    external_id    TEXT NOT NULL,
    game_date      DATE NOT NULL,
    season         TEXT,                -- e.g. '2025-26'
    opponent       TEXT,
    is_home        BOOLEAN,
    venue          TEXT,
    attendance     INTEGER,
    team_score     INTEGER,
    opponent_score INTEGER,
    status         TEXT,                -- 'final', 'scheduled', 'in_progress'
    raw_data       JSONB,               -- full API response as a fallback
    inserted_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (team_id, external_id)
);

-- ============================================
-- player_game_appearances: one row per player per game
-- tracks whether they played and how long (if applicable)
-- ============================================
CREATE TABLE player_game_appearances (
    appearance_id  SERIAL PRIMARY KEY,
    game_id        INTEGER NOT NULL REFERENCES games(game_id),
    player_id      INTEGER NOT NULL REFERENCES players(player_id),
    did_play       BOOLEAN NOT NULL,
    seconds_played INTEGER,      -- NBA: whole minutes*60. NHL: exact seconds. NFL: NULL (see player_game_stats for snaps).
    UNIQUE (game_id, player_id)
);

-- ============================================
-- player_game_stats: one row per player, per game, per stat
-- (long format — only insert what the API actually returns, no placeholder 0s)
-- ============================================
CREATE TABLE player_game_stats (
    stat_id     SERIAL PRIMARY KEY,
    game_id     INTEGER NOT NULL REFERENCES games(game_id),
    player_id   INTEGER NOT NULL REFERENCES players(player_id),
    stat_name   TEXT NOT NULL,          -- 'points', 'rebounds', 'goals', 'snaps_played'...
    stat_value  NUMERIC NOT NULL,
    UNIQUE (game_id, player_id, stat_name)
);

-- ============================================
-- player_season_stats: pre-aggregated rollup per player, per season, per stat
-- ============================================
CREATE TABLE player_season_stats (
    season_stat_id SERIAL PRIMARY KEY,
    player_id      INTEGER NOT NULL REFERENCES players(player_id),
    team_id        INTEGER NOT NULL REFERENCES teams(team_id),
    season         TEXT NOT NULL,
    stat_name      TEXT NOT NULL,
    games_played   INTEGER NOT NULL,
    total_value    NUMERIC NOT NULL,
    avg_value      NUMERIC NOT NULL,
    max_value      NUMERIC NOT NULL,
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (player_id, team_id, season, stat_name)
);

-- ============================================
-- player_career_stats: pre-aggregated rollup per player, per stat, all-time
-- ============================================
CREATE TABLE player_career_stats (
    career_stat_id SERIAL PRIMARY KEY,
    player_id      INTEGER NOT NULL REFERENCES players(player_id),
    stat_name      TEXT NOT NULL,
    games_played   INTEGER NOT NULL,
    total_value    NUMERIC NOT NULL,
    avg_value      NUMERIC NOT NULL,
    max_value      NUMERIC NOT NULL,
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (player_id, stat_name)
);