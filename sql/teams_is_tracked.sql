-- =====================================================================
-- Teams: add opponents support (espn_id + is_tracked)
--
-- Lets teams hold every opponent our four teams play, so
-- games.home_team_id / away_team_id always have a row to point at.
--
--   espn_id     ESPN's team ID. Games come from ESPN, so this is how a
--               schedule's team gets matched to a row here.
--   is_tracked  true for our four teams; false for opponents.
--
-- external_id becomes nullable: opponents have no balldontlie/NHL ID,
-- and we can't reuse ESPN's ID there because they collide — ESPN NBA
-- team 12 is the Clippers, but "12" is already the Pacers' external_id.
--
-- Safe to rerun. Run this BEFORE deploying the matching db.py /
-- api_pulls.py changes, since the new code expects these columns.
-- =====================================================================

BEGIN;

ALTER TABLE teams ADD COLUMN IF NOT EXISTS espn_id text;
ALTER TABLE teams ADD COLUMN IF NOT EXISTS is_tracked boolean NOT NULL DEFAULT false;
ALTER TABLE teams ALTER COLUMN external_id DROP NOT NULL;

-- Backfill our four teams, matched on their existing (league, external_id).
UPDATE teams SET espn_id = '11',   is_tracked = true WHERE league = 'NBA'   AND external_id = '12';   -- Pacers
UPDATE teams SET espn_id = '2509', is_tracked = true WHERE league = 'NCAAB' AND external_id = '125';  -- Purdue
UPDATE teams SET espn_id = '5',    is_tracked = true WHERE league = 'NHL'   AND external_id = 'DET';  -- Red Wings
UPDATE teams SET espn_id = '11',   is_tracked = true WHERE league = 'NFL'   AND external_id = '11';   -- Colts

-- One row per ESPN team per league. Postgres has no
-- "ADD CONSTRAINT IF NOT EXISTS", so check pg_constraint first.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'teams_league_espn_id_key'
    ) THEN
        ALTER TABLE teams
            ADD CONSTRAINT teams_league_espn_id_key UNIQUE (league, espn_id);
    END IF;
END $$;

COMMIT;
