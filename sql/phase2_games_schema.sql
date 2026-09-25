-- =====================================================================
-- Phase 2: games schema
--
-- Creates games, game_periods, and sport_period_labels, seeds
-- sport_period_labels, and links player_game_stats /
-- player_game_appearances to games via game_id foreign keys.
--
-- Matches the live sports_hub schema as of 2026-09-24.
--
-- Prerequisites (from sql/schema.sql, Phase 1): teams, players,
-- player_game_stats, and player_game_appearances must already exist.
--
-- Safe to rerun: every step checks whether its object already exists,
-- and the whole file runs inside one transaction, so it either fully
-- applies or changes nothing.
-- =====================================================================

BEGIN;

-- ---------------------------------------------------------------------
-- 1. games — one row per game, home/away style.
--    Depends on: teams
--
--    The sequence is created explicitly (instead of using SERIAL) so its
--    name matches the live database, where it's called games_id_seq —
--    SERIAL would have named it games_game_id_seq.
-- ---------------------------------------------------------------------
CREATE SEQUENCE IF NOT EXISTS games_id_seq AS integer;

CREATE TABLE IF NOT EXISTS games (
    game_id         integer     NOT NULL DEFAULT nextval('games_id_seq'),
    league          text        NOT NULL,
    external_id     text        NOT NULL,
    season_year     integer     NOT NULL,
    home_team_id    integer     NOT NULL REFERENCES teams (team_id),
    away_team_id    integer     NOT NULL REFERENCES teams (team_id),
    game_time       timestamptz NOT NULL,
    status          text        NOT NULL DEFAULT 'scheduled'
        CHECK (status IN ('scheduled', 'in_progress', 'final', 'postponed', 'canceled')),
    home_score      integer,
    away_score      integer,
    venue_name      text,
    is_neutral_site boolean     NOT NULL DEFAULT false,
    last_updated    timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT games_pkey PRIMARY KEY (game_id),
    CONSTRAINT games_league_external_id_key UNIQUE (league, external_id),
    CHECK (home_team_id <> away_team_id)
);

-- Ties the sequence to the column, so dropping games also drops it.
ALTER SEQUENCE games_id_seq OWNED BY games.game_id;

-- ---------------------------------------------------------------------
-- 2. game_periods — per-period score line (quarter/half/period/OT).
--    Depends on: games
--    ON DELETE CASCADE: deleting a game deletes its period rows too.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS game_periods (
    period_id     SERIAL  PRIMARY KEY,
    game_id       integer NOT NULL REFERENCES games (game_id) ON DELETE CASCADE,
    period_number integer NOT NULL,
    period_type   text    NOT NULL DEFAULT 'regulation'
        CHECK (period_type IN ('regulation', 'overtime', 'shootout')),
    home_score    integer NOT NULL DEFAULT 0,
    away_score    integer NOT NULL DEFAULT 0,
    UNIQUE (game_id, period_number, period_type)
);

-- ---------------------------------------------------------------------
-- 3. sport_period_labels — what a "period" is called in each league,
--    and how many there are in regulation. No dependencies.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sport_period_labels (
    league             text    PRIMARY KEY,
    period_label       text    NOT NULL,
    regulation_periods integer NOT NULL
);

-- ON CONFLICT DO NOTHING: rerunning won't duplicate or overwrite rows.
INSERT INTO sport_period_labels (league, period_label, regulation_periods)
VALUES
    ('NBA',   'Quarter', 4),
    ('NCAAB', 'Half',    2),
    ('NHL',   'Period',  3),
    ('NFL',   'Quarter', 4)
ON CONFLICT (league) DO NOTHING;

-- ---------------------------------------------------------------------
-- 4. Link the existing per-game player tables to games.
--    Postgres has no "ADD CONSTRAINT IF NOT EXISTS", so each one checks
--    pg_constraint (Postgres's catalog of constraints) first.
-- ---------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'player_game_stats_game_id_fkey'
    ) THEN
        ALTER TABLE player_game_stats
            ADD CONSTRAINT player_game_stats_game_id_fkey
            FOREIGN KEY (game_id) REFERENCES games (game_id);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'player_game_appearances_game_id_fkey'
    ) THEN
        ALTER TABLE player_game_appearances
            ADD CONSTRAINT player_game_appearances_game_id_fkey
            FOREIGN KEY (game_id) REFERENCES games (game_id);
    END IF;
END $$;

COMMIT;
