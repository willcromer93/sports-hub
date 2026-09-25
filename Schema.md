# Sports Hub — Database Schema

Current-state documentation of the `sports_hub` Postgres database. This file
reflects what's actually live, not the original design — see
`CLAUDE_PROJECT_NOTES.md` for the dated history of how it got here.

*Last verified against the local (Mac) database via `information_schema`: 2026-09-24.
The Pi has not been re-verified since the 2026-08-30 migration.*

## Tables

9 tables. Build order on a fresh database:

1. Phase 1 — `teams`, `players`, `player_game_appearances`, `player_game_stats`,
   `player_season_stats`, `player_career_stats`
2. Phase 2 — `sql/phase2_games_schema.sql`: creates `games`, `game_periods`,
   `sport_period_labels` (with seed rows), then adds the `game_id` foreign keys
   to `player_game_appearances` and `player_game_stats`. Safe to rerun.
3. `sql/teams_is_tracked.sql`: adds `espn_id`/`is_tracked` to `teams`, makes
   `external_id` nullable, and backfills the four tracked teams. Safe to rerun.
4. `sql/games_season_type.sql`: adds `season_type` to `games`. Safe to rerun.

### teams
One row per team, across all four leagues — our four tracked teams plus
every opponent they play (added by the games pull as schedules come in), so
`games.home_team_id`/`away_team_id` always have a row to point at.

| Column       | Type        | Notes                                                    |
|--------------|-------------|----------------------------------------------------------|
| team_id      | SERIAL PK   |                                                          |
| league       | TEXT        | 'NBA', 'NCAAB', 'NHL', 'NFL'                             |
| external_id  | TEXT        | balldontlie/NHL/ESPN identity ID for tracked teams — never change it (see README); NULL for opponents |
| espn_id      | TEXT        | ESPN team ID, used to match schedule/game data to a row. Not interchangeable with external_id — ESPN NBA 12 is the Clippers, but '12' is the Pacers' external_id |
| is_tracked   | BOOLEAN     | true for our four teams, false (default) for opponents        |
| name         | TEXT        |                                                          |
| updated_at   | TIMESTAMPTZ | defaults to now(); refreshed on every upsert             |
| venue        | TEXT        | ESPN for NBA/NHL/NFL; hardcoded for Purdue               |
| city         | TEXT        | same sourcing as venue                                   |
| capacity     | INTEGER     | intentionally left NULL — candidate for `DROP COLUMN`    |
| founded_year | INTEGER     | hardcoded for all four teams                             |

Unique on (league, external_id) and on (league, espn_id). NULLs don't count
as duplicates in a UNIQUE constraint, so any number of opponents can have a
NULL external_id. Columns added by `sql/teams_is_tracked.sql`.

### players
One row per player, shared across all four sports rather than per-team or
per-sport tables — filtering by `team_id`/`league` covers cross-team queries
and makes adding a new team a data-only change, not a schema change.

| Column                | Type        | Notes                                                   |
|------------------------|-------------|----------------------------------------------------------|
| player_id              | SERIAL PK   |                                                            |
| team_id                | INTEGER FK  | references teams; nullable                                |
| league                 | TEXT        |                                                            |
| external_id            | TEXT        | ESPN athlete ID                                            |
| name                   | TEXT        |                                                            |
| position               | TEXT        | free text — holds NBA/NFL/NCAAB position codes AND hockey codes (C/LW/RW/D/G) |
| height_inches          | NUMERIC     |                                                            |
| weight_lbs             | NUMERIC     |                                                            |
| jersey_number          | TEXT        | text, not integer — some jerseys have letters/suffixes      |
| birth_date             | DATE        |                                                            |
| birth_city             | TEXT        |                                                            |
| birth_state            | TEXT        |                                                            |
| birth_country          | TEXT        |                                                            |
| experience_years       | INTEGER     |                                                            |
| status                 | TEXT        | e.g. 'Active'                                              |
| college                | TEXT        | NULL for pro-only leagues where not applicable             |
| headshot_url           | TEXT        |                                                            |
| shoots_catches         | TEXT        | hockey-only ('L'/'R'); NULL for other sports                |
| contract_salary        | NUMERIC     | most recent season, from ESPN's `contracts` list           |
| contract_season        | INTEGER     |                                                            |
| contract_total_value   | NUMERIC     | sum across all listed contract years                       |
| contract_years         | INTEGER     | count of contracts in ESPN's list                           |
| contract_expires       | DATE        |                                                            |
| injury_status          | TEXT        | e.g. 'Out', 'Questionable'; NULL if healthy                 |
| draft_year             | INTEGER     | currently always NULL — ESPN roster endpoint doesn't return this |
| draft_round            | INTEGER     | currently always NULL, same reason                          |
| draft_pick             | INTEGER     | currently always NULL, same reason                          |
| updated_at             | TIMESTAMPTZ | defaults to now(); refreshed on every upsert               |

Unique on (league, external_id).

### games
One row per game, stored home/away style — each game appears once, no
matter which of our teams played in it (so Pacers vs. Pistons is one row, and
a game between two tracked teams isn't duplicated). Populated nightly from
ESPN's team schedule endpoint — preseason, regular season, and postseason.

`season_year` is ESPN's season year: the year the season *ends* for
NBA/NHL/NCAAB (2026-27 → 2027), but the year it *starts* for the NFL (2026).
`game_time` holds ESPN's placeholder time when a start time hasn't been
announced yet (common for Purdue) — there's no column to flag that yet.

| Column          | Type        | Notes                                                      |
|-----------------|-------------|------------------------------------------------------------|
| game_id         | SERIAL PK   | sequence is named `games_id_seq` (column was renamed from `id`) |
| league          | TEXT        |                                                            |
| external_id     | TEXT        | source API's game ID                                       |
| season_year     | INTEGER     |                                                            |
| season_type     | TEXT        | must be preseason / regular / postseason; no default — every insert must set it |
| home_team_id    | INTEGER FK  | references teams                                           |
| away_team_id    | INTEGER FK  | references teams                                           |
| game_time       | TIMESTAMPTZ | scheduled start, with time zone                            |
| status          | TEXT        | default 'scheduled'; must be one of scheduled / in_progress / final / postponed / canceled |
| home_score      | INTEGER     | NULL until the game has a score                            |
| away_score      | INTEGER     | same                                                       |
| venue_name      | TEXT        |                                                            |
| is_neutral_site | BOOLEAN     | default false                                              |
| last_updated    | TIMESTAMPTZ | defaults to now()                                          |

Unique on (league, external_id). Check: `home_team_id <> away_team_id`.
Indexes: only the two that come with the primary key and the unique constraint.

Both team columns reference `teams`; opponents get their row via
`upsert_opponent_team()` in `db.py` (keyed on `espn_id`) before a game is inserted.

### game_periods
One row per game per period — the box-score line (quarters, halves, periods,
overtime, shootout). Filled in nightly for final games that don't have
rows yet, from ESPN's per-game `summary` endpoint.

Numbering restarts for each `period_type`: regulation 1..N, overtime 1..k,
shootout 1. NBA double overtime is ('overtime', 1) + ('overtime', 2). ESPN
lists periods in order without labeling them, so the type comes from the
league's `regulation_periods` (in `sport_period_labels`) plus the game's
`Final/SO` status for hockey shootouts. The shootout row holds the 1 goal
credited to the winner, so a game's periods always sum to its final score.

| Column        | Type       | Notes                                               |
|---------------|------------|-----------------------------------------------------|
| period_id     | SERIAL PK  |                                                     |
| game_id       | INTEGER FK | references games, `ON DELETE CASCADE` — deleting a game deletes its periods |
| period_number | INTEGER    |                                                     |
| period_type   | TEXT       | default 'regulation'; must be regulation / overtime / shootout |
| home_score    | INTEGER    | points scored in that period; default 0            |
| away_score    | INTEGER    | same; default 0                                     |

Unique on (game_id, period_number, period_type).

### sport_period_labels
Small lookup table: what a "period" is called in each league, and how many
there are in regulation. Seeded by `sql/phase2_games_schema.sql`.

| Column             | Type    | Notes        |
|--------------------|---------|--------------|
| league             | TEXT PK |              |
| period_label       | TEXT    |              |
| regulation_periods | INTEGER |              |

| league | period_label | regulation_periods |
|--------|--------------|--------------------|
| NBA    | Quarter      | 4                  |
| NCAAB  | Half         | 2                  |
| NHL    | Period       | 3                  |
| NFL    | Quarter      | 4                  |

### player_game_appearances
One row per player per game. Exists as a separate table (rather than
inferring "played" from the presence of stat rows) so a missing row can be
told apart from "played and recorded a zero" — a player who didn't dress
has no row at all, distinct from a player who played but had, say, zero
rebounds.

| Column         | Type       | Notes              |
|----------------|------------|--------------------|
| appearance_id  | SERIAL PK  |                    |
| game_id        | INTEGER FK | references games   |
| player_id      | INTEGER FK | references players |
| did_play       | BOOLEAN    |                    |
| seconds_played | INTEGER    | see below          |

Unique on (game_id, player_id).

`seconds_played` is the canonical time column across sports:
NBA stores whole minutes × 60, NHL stores exact seconds, NFL leaves this
NULL (snap counts go into `player_game_stats` instead). Converting to a
display format like MM:SS happens in the Python/dashboard layer, not here.

### player_game_stats
One row per player, per game, per stat — long format rather than wide
columns or a JSONB blob. Chosen because NBA/NHL/NFL/NCAAB each track
entirely different stat categories; long format keeps aggregation
queries (sums, averages across a season) simple regardless of sport.

| Column     | Type       | Notes                                     |
|------------|------------|-------------------------------------------|
| stat_id    | SERIAL PK  |                                           |
| game_id    | INTEGER FK | references games                          |
| player_id  | INTEGER FK | references players                        |
| stat_name  | TEXT       | e.g. 'points', 'goals', 'passing_yards'   |
| stat_value | NUMERIC    |                                           |

Unique on (game_id, player_id, stat_name).

### player_season_stats / player_career_stats
Pre-aggregated rollups, one row per player per stat (per season, or
all-time). Not yet populated — depends on `player_game_stats` being
populated first.

| Column         | Type        | Notes                                   |
|----------------|-------------|-----------------------------------------|
| season_stat_id / career_stat_id | SERIAL PK |                          |
| player_id      | INTEGER FK  | references players                      |
| team_id        | INTEGER FK  | season table only; references teams     |
| season         | TEXT        | season table only                       |
| stat_name      | TEXT        |                                         |
| games_played   | INTEGER     |                                         |
| total_value    | NUMERIC     |                                         |
| avg_value      | NUMERIC     |                                         |
| max_value      | NUMERIC     |                                         |
| updated_at     | TIMESTAMPTZ | defaults to now()                       |

Unique on (player_id, team_id, season, stat_name) for season stats;
(player_id, stat_name) for career stats.

## Design decisions

- **Upsert everywhere.** All inserts use `INSERT ... ON CONFLICT DO UPDATE`,
  keyed on (league, external_id) for teams/players (and the same key is in
  place for games). The whole pipeline can be rerun safely without creating
  duplicates.
- **Home/away games, not per-team games.** One row per real-world game, with
  both teams as foreign keys, rather than one row per team per game.
- **No permanent JSON files.** API responses go straight from Python into
  Postgres; JSON is only ever a temporary variable, never written to disk
  as a lasting artifact.
- **Raw psycopg2, not an ORM.** Deliberate choice to keep the SQL visible
  and explicit while learning, rather than abstracting it behind SQLAlchemy's
  ORM layer.

## Known gaps

- `draft_year`/`draft_round`/`draft_pick` always NULL — would need a
  different ESPN endpoint to populate.
- `teams.capacity` intentionally unpopulated.
- `games.game_time` can't tell "time TBD" apart from a real start time.
- `game_periods` rows are written once per game and never refreshed (fine
  unless ESPN corrects a score afterward).
- All player game/season/career stat tables exist but have no data yet.
- `sql/schema.sql` is currently a Markdown snapshot, not runnable SQL — the
  Phase 1 tables can't yet be rebuilt from the repo alone.
