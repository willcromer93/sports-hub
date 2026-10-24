-- =====================================================================
-- Teams: add is_featured (the teams the dashboard is built around)
--
-- Until now, is_tracked has meant "one of our four teams". Phase D collects full
-- data (rosters, schedules, box scores) for every team in several leagues, so the
-- two ideas must be separated:
--
--   is_tracked   we collect full data for this team (rosters, box scores, rollups)
--   is_featured  one of the teams the dashboard shows (Pacers, Purdue, Red Wings,
--                Colts). The dashboard's team picker and Overview read this flag.
--
-- Backfill: the teams that are tracked today ARE the four featured teams. This
-- runs only if no team is featured yet, so rerunning it later (when hundreds of
-- teams are tracked) can't wrongly feature them all. For the same reason it
-- refuses to run its first backfill if more than 10 teams are tracked.
--
-- Safe to rerun. Run this BEFORE deploying the matching code, which expects
-- the column.
-- =====================================================================

BEGIN;

ALTER TABLE teams ADD COLUMN IF NOT EXISTS is_featured boolean NOT NULL DEFAULT false;

DO $$
DECLARE
    tracked integer;
BEGIN
    IF NOT EXISTS (SELECT 1 FROM teams WHERE is_featured) THEN
        SELECT count(*) INTO tracked FROM teams WHERE is_tracked;
        IF tracked > 10 THEN
            RAISE EXCEPTION
                '% teams are tracked but none are featured yet. Mark the featured '
                'teams by hand (UPDATE teams SET is_featured = true WHERE ...) '
                'instead of assuming every tracked team is one.', tracked;
        END IF;
        UPDATE teams SET is_featured = true WHERE is_tracked;
    END IF;
END $$;

COMMIT;
