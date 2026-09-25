-- =====================================================================
-- Season/career rollups: split by season_type, match games' season key
--
-- player_season_stats and player_career_stats were designed before the
-- games table was, and would have mixed preseason, regular-season, and
-- playoff numbers together. This adds season_type to both, and changes
-- player_season_stats.season (text) to season_year (integer) so it
-- matches games.season_year exactly.
--
-- Both tables are empty until the rollup job first runs, which is why
-- season_type can be added as NOT NULL with no default. (If they ever
-- did have rows, this would fail loudly rather than guess a value.)
--
-- Safe to rerun. Run this BEFORE deploying the matching db.py /
-- api_pulls.py / refresh_stats.py changes.
-- =====================================================================

BEGIN;

-- ---------------------------------------------------------------------
-- player_season_stats
-- ---------------------------------------------------------------------
-- The old unique key used `season`, so it has to go before the column changes.
ALTER TABLE player_season_stats
    DROP CONSTRAINT IF EXISTS player_season_stats_player_id_team_id_season_stat_name_key;

-- Postgres has no "RENAME COLUMN IF EXISTS", so check information_schema first.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'player_season_stats' AND column_name = 'season'
    ) THEN
        ALTER TABLE player_season_stats RENAME COLUMN season TO season_year;
        ALTER TABLE player_season_stats
            ALTER COLUMN season_year TYPE integer USING season_year::integer;
    END IF;
END $$;

ALTER TABLE player_season_stats
    ADD COLUMN IF NOT EXISTS season_type text NOT NULL
    CONSTRAINT player_season_stats_season_type_check
        CHECK (season_type IN ('preseason', 'regular', 'postseason'));

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'player_season_stats_player_team_season_stat_key'
    ) THEN
        ALTER TABLE player_season_stats
            ADD CONSTRAINT player_season_stats_player_team_season_stat_key
            UNIQUE (player_id, team_id, season_year, season_type, stat_name);
    END IF;
END $$;

-- ---------------------------------------------------------------------
-- player_career_stats
-- ---------------------------------------------------------------------
ALTER TABLE player_career_stats
    DROP CONSTRAINT IF EXISTS player_career_stats_player_id_stat_name_key;

ALTER TABLE player_career_stats
    ADD COLUMN IF NOT EXISTS season_type text NOT NULL
    CONSTRAINT player_career_stats_season_type_check
        CHECK (season_type IN ('preseason', 'regular', 'postseason'));

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'player_career_stats_player_season_type_stat_key'
    ) THEN
        ALTER TABLE player_career_stats
            ADD CONSTRAINT player_career_stats_player_season_type_stat_key
            UNIQUE (player_id, season_type, stat_name);
    END IF;
END $$;

COMMIT;
