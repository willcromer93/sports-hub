-- =====================================================================
-- Game summary details: more of what ESPN's per-game summary already sends
--
-- The pipeline fetches each finished game's summary once (periods, box score and
-- everything below come from that one page). This migration adds the places to keep:
--
--   player_game_appearances (one row per player per game), new columns. NULL means
--   "ESPN does not provide this for this sport", which is different from false:
--     is_starter     basketball only: started the game
--     was_ejected    basketball only
--     dnp_reason     why a player did not play (e.g. COACH'S DECISION); set only when
--                    did_play is false (ESPN also fills the reason for players who played)
--     is_active      NHL only: ESPN's "active" flag
--     was_scratched  NHL only: healthy scratch / did not dress
--     jersey         number worn in THAT game (text: '00' and '0' both exist)
--     position       position abbreviation in that game (F, G, C, D, ...). ESPN
--                    sends none for the NFL box score, so NFL stays NULL.
--
--   games.attendance      announced attendance.
--
--   game_officials        referees, linesmen, umpires, etc. NHL gives every official
--                         order 0, so sort_order is not part of the key.
--
--   games.summary_parsed_version
--                         which version of the summary parser last processed this game
--                         (NULL = never, i.e. loaded before this migration). The pipeline
--                         re-processes any final game below the parser's current version,
--                         so the existing games backfill themselves and a future parser
--                         addition is a version bump, not a migration.
--
--   game_plays            play-by-play, one row per play, for every league: shot
--                         locations (basketball, hockey), event types (hockey Corsi/
--                         Fenwick counts), substitutions (on/off), football down and
--                         distance. Columns a sport does not send stay NULL; `extra` keeps
--                         ESPN fields not modeled here (e.g. NFL yardsAfterCatch), so a
--                         new field later needs no schema change.
--   game_play_participants
--                         the players on a play, in ESPN's order, with a role where ESPN
--                         gives one (NHL: scorer, assister, ...). player_id is NULL when
--                         the player has no players row; espn_athlete_id is always kept.
--
--   game_summary_cache    a trimmed copy (boxscore, gameInfo, header; about 60-100 KB,
--                         NOT the 500 KB full page) of the summary the pipeline just
--                         parsed, so a parser change can be re-run without asking ESPN
--                         again. The pipeline deletes rows older than 14 days.
--
-- Safe to rerun. Run on live BEFORE deploying the matching code.
-- Existing games are not changed: their new columns stay NULL until a backfill re-fetches them.
-- =====================================================================

BEGIN;

ALTER TABLE player_game_appearances
    ADD COLUMN IF NOT EXISTS is_starter    boolean,
    ADD COLUMN IF NOT EXISTS was_ejected   boolean,
    ADD COLUMN IF NOT EXISTS dnp_reason    text,
    ADD COLUMN IF NOT EXISTS is_active     boolean,
    ADD COLUMN IF NOT EXISTS was_scratched boolean,
    ADD COLUMN IF NOT EXISTS jersey        text,
    ADD COLUMN IF NOT EXISTS position      text;

ALTER TABLE games
    ADD COLUMN IF NOT EXISTS attendance            integer,
    ADD COLUMN IF NOT EXISTS summary_parsed_version smallint;

CREATE TABLE IF NOT EXISTS game_plays (
    play_id          BIGSERIAL PRIMARY KEY,
    game_id          integer      NOT NULL REFERENCES games (game_id) ON DELETE CASCADE,
    sequence_number  integer      NOT NULL,   -- ESPN's order within the game
    espn_play_id     text,
    period_number    integer,
    clock_seconds    numeric(6,1),            -- time left in the period (football/hockey/basketball)
    play_type        text,                    -- 'Jump Shot', 'Goal', 'Substitution', 'Rush', ...
    description      text,
    team_id          integer REFERENCES teams (team_id),  -- the team the play belongs to (football: offense)
    home_score       integer,                 -- running score after the play
    away_score       integer,
    is_scoring       boolean,
    score_value      integer,
    is_shooting      boolean,                 -- basketball/hockey shot attempt
    points_attempted integer,                 -- basketball: 1, 2 or 3
    x                numeric(8,2),            -- shot location; NULL when ESPN sends none
    y                numeric(8,2),
    strength         text,                    -- hockey: even strength / power play / ...
    shot_detail      text,                    -- hockey: ESPN shotInfo (regular, ...)
    down             smallint,                -- football, at the start of the play
    distance         smallint,
    yard_line        smallint,
    yards_to_endzone smallint,
    yardage          smallint,                -- football: yards gained
    is_penalty       boolean,
    is_turnover      boolean,
    drive_id         text,                    -- football: ESPN drive id
    occurred_at      timestamptz,
    extra            jsonb,                   -- any ESPN play field not modeled above
    CONSTRAINT game_plays_game_seq_key UNIQUE (game_id, sequence_number)
);

CREATE INDEX IF NOT EXISTS game_plays_shots_idx
    ON game_plays (game_id) WHERE is_shooting;

CREATE TABLE IF NOT EXISTS game_play_participants (
    play_id          bigint  NOT NULL REFERENCES game_plays (play_id) ON DELETE CASCADE,
    participant_order smallint NOT NULL,
    espn_athlete_id  text    NOT NULL,
    player_id        integer REFERENCES players (player_id),
    role             text,
    PRIMARY KEY (play_id, participant_order)
);

CREATE INDEX IF NOT EXISTS game_play_participants_player_idx
    ON game_play_participants (player_id);

CREATE TABLE IF NOT EXISTS game_officials (
    official_id   SERIAL  PRIMARY KEY,
    game_id       integer NOT NULL REFERENCES games (game_id) ON DELETE CASCADE,
    official_name text    NOT NULL,
    role          text    NOT NULL,
    sort_order    integer,
    CONSTRAINT game_officials_unique UNIQUE (game_id, official_name, role)
);

CREATE TABLE IF NOT EXISTS game_summary_cache (
    game_id    integer     PRIMARY KEY REFERENCES games (game_id) ON DELETE CASCADE,
    fetched_at timestamptz NOT NULL DEFAULT now(),
    payload    jsonb       NOT NULL
);

CREATE INDEX IF NOT EXISTS game_summary_cache_fetched_idx ON game_summary_cache (fetched_at);

-- The read-only dashboard role reads the new columns/tables like everything else.
-- (Column grants on existing tables already cover new columns when granted at table level.)
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'dashboard_ro') THEN
        GRANT SELECT ON game_officials, game_summary_cache, game_plays,
                        game_play_participants TO dashboard_ro;
    END IF;
END $$;

COMMIT;
