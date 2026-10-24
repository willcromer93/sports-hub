-- =====================================================================
-- Players: track roster departures (last_seen_at + departed_at)
--
-- The nightly roster pull only ever adds or updates players, so a player who
-- drops off ESPN's roster (cut, traded, retired) kept their old team and looked
-- current forever. These two columns record what actually happened:
--
--   last_seen_at  the last time ESPN's roster for their team listed them
--   departed_at   when the pipeline noticed they were gone. NULL while they
--                 are on the roster; cleared again if they come back.
--
-- Rows are never deleted: departed players still have box-score history.
-- Players on non-tracked (opponent) teams stay NULL in both columns; they come
-- from box scores, not roster pulls, so "last seen on a roster" doesn't apply.
--
-- Backfill: for players on tracked teams, last_seen_at = updated_at (the old
-- pull set it on every sighting). Anyone not touched in the last 36 hours,
-- i.e. missed by the last two nightly runs, is marked departed at that time.
-- Because of that rule, the migration REFUSES TO RUN if the nightly pull hasn't
-- run recently (it would mark the whole league as departed).
--
-- Safe to rerun. Run this BEFORE deploying the matching db.py / api_pulls.py
-- changes, since the new code expects these columns.
-- =====================================================================

BEGIN;

ALTER TABLE players ADD COLUMN IF NOT EXISTS last_seen_at timestamptz;
ALTER TABLE players ADD COLUMN IF NOT EXISTS departed_at  timestamptz;

-- Safety check: the backfill below only makes sense right after a roster pull.
DO $$
DECLARE
    newest timestamptz;
BEGIN
    SELECT max(p.updated_at) INTO newest
    FROM players p JOIN teams t ON t.team_id = p.team_id
    WHERE t.is_tracked;
    IF newest IS NULL OR newest < now() - interval '36 hours' THEN
        RAISE EXCEPTION
            'No tracked-team player was updated in the last 36 hours (newest: %). '
            'Run the nightly pipeline first, then rerun this migration.', newest;
    END IF;
END $$;

-- Backfill tracked-team players that haven't been backfilled yet (safe to rerun).
UPDATE players p
SET last_seen_at = p.updated_at,
    departed_at  = CASE WHEN p.updated_at < now() - interval '36 hours'
                        THEN p.updated_at END
FROM teams t
WHERE t.team_id = p.team_id
  AND t.is_tracked
  AND p.last_seen_at IS NULL;

-- "Who is on this team's roster right now?" is the common question: index it.
CREATE INDEX IF NOT EXISTS players_on_roster_idx
    ON players (team_id) WHERE departed_at IS NULL;

COMMIT;
