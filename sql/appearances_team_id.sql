-- Adds team_id to player_game_appearances: which team the player was on
-- in that game.
--
-- Why: box scores used to store only our tracked team's players, so "the
-- tracked team in the game" was always the player's team. Once opponents'
-- box scores are stored too, both sides of a game live in the same tables,
-- and this column is what tells a Pacer apart from a Timberwolf. It also
-- keeps history right when a player changes teams — players.team_id is
-- only their *current* team.
--
-- player_game_stats doesn't get its own copy: every stat row has a
-- matching appearance row (same game_id + player_id) to join through.
--
-- Safe to rerun: the column is only added (and backfilled) if missing.

BEGIN;

ALTER TABLE player_game_appearances
    ADD COLUMN IF NOT EXISTS team_id INTEGER REFERENCES teams (team_id);

-- Backfill: every row stored before this migration is a tracked-team
-- player, so their team is the tracked team in that game.
UPDATE player_game_appearances a
SET team_id = t.team_id
FROM games g
JOIN teams t
  ON t.team_id IN (g.home_team_id, g.away_team_id)
 AND t.is_tracked
WHERE a.game_id = g.game_id
  AND a.team_id IS NULL;

-- Every future insert must say which side the player was on.
ALTER TABLE player_game_appearances
    ALTER COLUMN team_id SET NOT NULL;

-- Dashboard pages look up "this team's players in this game/season".
CREATE INDEX IF NOT EXISTS player_game_appearances_team_game_idx
    ON player_game_appearances (team_id, game_id);

COMMIT;
