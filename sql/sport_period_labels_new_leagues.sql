-- =====================================================================
-- Period labels for the leagues added in Phase D
--
-- sport_period_labels says what a "period" is called in each league and how many there
-- are in regulation. The period-score pull JOINS this table, so a league with no row
-- here silently gets NO period scores (found when the WNBA trial filled 0 of 369).
-- NBA, NCAAB, NFL and NHL already have rows. This adds the other three.
--
--   WNBA  4 quarters     CFB  4 quarters     MLB  9 innings (extra innings are
--                                                  stored as overtime periods)
--
-- Safe to rerun (existing rows are left alone).
-- =====================================================================

BEGIN;

INSERT INTO sport_period_labels (league, period_label, regulation_periods) VALUES
    ('WNBA', 'Quarter', 4),
    ('CFB',  'Quarter', 4),
    ('MLB',  'Inning',  9)
ON CONFLICT (league) DO NOTHING;

COMMIT;
