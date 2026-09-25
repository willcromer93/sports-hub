-- =====================================================================
-- Games: add season_type (preseason / regular / postseason)
--
-- Lets the games pull load preseason and postseason games alongside the
-- regular season without mixing them up.
--
-- Existing rows are all regular-season games, so the column is added
-- with DEFAULT 'regular' to fill them in, and the default is then
-- dropped. From here on every insert must say which season type a game
-- is — forgetting to fails loudly instead of silently mislabeling a
-- playoff game as 'regular'.
--
-- Safe to rerun. Run this BEFORE deploying the matching db.py /
-- api_pulls.py changes, since the new code expects this column.
-- =====================================================================

BEGIN;

ALTER TABLE games
    ADD COLUMN IF NOT EXISTS season_type text NOT NULL DEFAULT 'regular'
    CONSTRAINT games_season_type_check
        CHECK (season_type IN ('preseason', 'regular', 'postseason'));

ALTER TABLE games ALTER COLUMN season_type DROP DEFAULT;

COMMIT;
