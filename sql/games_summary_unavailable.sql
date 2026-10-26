-- =====================================================================
-- Games: remember when ESPN has no summary page for a finished game
--
-- Box scores and period scores both come from ESPN's per-game "summary" page. A
-- few finished games simply have none (seen: a WNBA game answering 404 for good),
-- and for college basketball, with its many small-school games, there will be many.
-- Without a memory of that, every nightly run asks again, and (before per-game
-- isolation) one such game stopped the whole box-score step.
--
--   summary_unavailable_at  when ESPN's summary for this game was last found missing
--                           (still a 404 after retries). NULL for normal games. The
--                           pipeline stops asking, rechecks after 3 days in case ESPN
--                           publishes it late, and clears this when a summary arrives.
--
-- Sanity checks and the league gate treat flagged games as known gaps, and warn
-- when a league has too many of them.
--
-- Safe to rerun. Run BEFORE deploying the matching code (it expects the column).
-- =====================================================================

BEGIN;

ALTER TABLE games ADD COLUMN IF NOT EXISTS summary_unavailable_at timestamptz;

CREATE INDEX IF NOT EXISTS games_summary_unavailable_idx
    ON games (league) WHERE summary_unavailable_at IS NOT NULL;

COMMIT;
