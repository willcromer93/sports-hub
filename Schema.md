# Sports Hub — Database Schema

Current-state documentation of the `sports_hub` Postgres database. This file
reflects what's actually live, not the original design — see
`CLAUDE_PROJECT_NOTES.md` for the dated history of how it got here.

*Last verified against the local (Mac) database via `information_schema`: 2026-09-25.
The Pi was brought up to date the same day and its 93 columns match the Mac's exactly.*

## Tables

13 tables (9 core + 4 added by `sql/game_summary_details.sql`). Build order on a fresh database:

1. Phase 1 — `teams`, `players`, `player_game_appearances`, `player_game_stats`,
   `player_season_stats`, `player_career_stats`
2. Phase 2 — `sql/phase2_games_schema.sql`: creates `games`, `game_periods`,
   `sport_period_labels` (with seed rows), then adds the `game_id` foreign keys
   to `player_game_appearances` and `player_game_stats`. Safe to rerun.
3. `sql/teams_is_tracked.sql`: adds `espn_id`/`is_tracked` to `teams`, makes
   `external_id` nullable, and backfills the four tracked teams. Safe to rerun.
4. `sql/games_season_type.sql`: adds `season_type` to `games`. Safe to rerun.
5. `sql/stat_rollups_season_type.sql`: adds `season_type` to both rollup
   tables and changes `player_season_stats.season` (text) to `season_year`
   (integer). Safe to rerun.
6. `sql/appearances_team_id.sql`: adds `team_id` to `player_game_appearances`
   (which side the player was on) and backfills it. Safe to rerun.
7. `sql/game_summary_details.sql`: per-player game details, `games.attendance` and
   `games.summary_parsed_version`, and the tables `game_officials`, `game_summary_cache`,
   `game_plays`, `game_play_participants` (see "Game summary details" below). Safe to rerun.
   Apply it on a database BEFORE deploying the code that uses it.

### teams
One row per team: every team collected in full (tracked), including the four
featured teams, plus every opponent they play that isn't collected (added by the
games pull as schedules come in), so `games.home_team_id`/`away_team_id` always
have a row to point at.

| Column       | Type        | Notes                                                    |
|--------------|-------------|----------------------------------------------------------|
| team_id      | SERIAL PK   |                                                          |
| league       | TEXT        | 'NBA', 'NCAAB', 'NHL', 'NFL', 'WNBA', 'MLB', 'CFB' (see scripts/leagues.py; no database constraint restricts it) |
| external_id  | TEXT        | legacy identity ID (balldontlie/NHL/ESPN) of the four featured teams; the nightly run never writes it. NULL for every other team |
| espn_id      | TEXT        | ESPN team ID, used to match schedule/game data to a row. Not interchangeable with external_id — ESPN NBA 12 is the Clippers, but '12' is the Pacers' external_id |
| is_tracked   | BOOLEAN     | true for teams we collect full data for (rosters, schedules, box scores, rollups); false (default) for opponents |
| is_featured  | BOOLEAN     | true for the four teams the dashboard is built around (Pacers, Purdue, Red Wings, Colts); the nightly run only ever switches it on. Added by `sql/teams_is_featured.sql` |
| name         | TEXT        |                                                          |
| updated_at   | TIMESTAMPTZ | defaults to now(); refreshed on every upsert             |
| venue        | TEXT        | ESPN team detail where available; ESPN has none for college basketball, so Purdue's is kept from the config. A missing value never erases a stored one |
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
| last_seen_at           | TIMESTAMPTZ | last time ESPN's roster for their team listed them; NULL for opponents' players |
| departed_at            | TIMESTAMPTZ | when the nightly pull noticed they were gone; NULL while on the roster, cleared again if they reappear |

Unique on (league, external_id).

**Roster tracking.** `team_id` is the team a player was last seen on, and a
roster pull only ever adds or updates players, so on its own it can't tell
"still here" from "left in August". `last_seen_at` / `departed_at` (added by
`sql/players_roster_tracking.sql`) record that: each roster pull stamps
`last_seen_at` and clears `departed_at` for everyone ESPN lists, then marks
anyone previously on the team's roster but missing tonight as departed.
Rows are never deleted, because departed players still have box-score history.
A safety rule (`scripts/roster_tracking.py`) refuses to mark departures when
ESPN's roster comes back empty or under half its previous size, so a bad
response can't wipe a roster. Players on non-tracked (opponent) teams come from
box scores, not roster pulls, so both columns stay NULL for them.
"Currently on the roster" means `team_id = X AND last_seen_at IS NOT NULL AND departed_at IS NULL`: a
player known only from a box score (no `last_seen_at`) was never confirmed on a roster, so is neither
on it nor "departed".

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
| attendance      | INTEGER     | announced attendance from the summary's gameInfo; NULL when ESPN sends none or 0 |
| summary_parsed_version | SMALLINT | which `SUMMARY_PARSER_VERSION` last processed this game's summary; NULL = never (loaded before the details existed). Games below the current version are re-fetched, 400 a night |
| summary_unavailable_at | TIMESTAMPTZ | NULL for normal games; set when ESPN's summary page for this finished game was still a 404 after retries (so it has no box score or period scores). The pipeline stops asking, rechecks after 3 days, and clears it when a summary arrives. Added by `sql/games_summary_unavailable.sql` |

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
| WNBA   | Quarter      | 4                  |
| CFB    | Quarter      | 4                  |
| MLB    | Inning       | 9                  |

The last three rows come from `sql/sport_period_labels_new_leagues.sql`. **A league with no row here gets no
period scores at all** (the period pull joins this table): the first WNBA trial filled 0 of 369 games for that reason.
### player_game_appearances
One row per player per game. Exists as a separate table (rather than
inferring "played" from the presence of stat rows) so a missing row can be
told apart from "played and recorded a zero" — a player who didn't dress
has no row at all, distinct from a player who played but had, say, zero
rebounds.

Filled in nightly for **both teams** in every final game, from ESPN's
per-game `summary` box score. Each side is filled in separately, only if
that team has no rows for the game yet.
`did_play = false` only comes from basketball, where ESPN lists DNPs
(e.g. coach's decision); NHL/NFL box scores only list players who played.
NFL players who played without recording a stat (e.g. some special teams
snaps) aren't in ESPN's box score, so they have no row.

| Column         | Type       | Notes              |
|----------------|------------|--------------------|
| appearance_id  | SERIAL PK  |                    |
| game_id        | INTEGER FK | references games   |
| player_id      | INTEGER FK | references players |
| team_id        | INTEGER FK | references teams; NOT NULL — the team the player was on **in this game** (ours or the opponent). Use this, not `players.team_id` (current team only), to split a game's two sides |
| did_play       | BOOLEAN    |                    |
| seconds_played | INTEGER    | see below          |
| is_starter     | BOOLEAN    | basketball only: started the game. NULL = ESPN does not send it for this sport (not false) |
| was_ejected    | BOOLEAN    | basketball only |
| dnp_reason     | TEXT       | why a player did not play (e.g. COACH'S DECISION); set only when `did_play` is false |
| is_active      | BOOLEAN    | NHL only: ESPN's `active` flag |
| was_scratched  | BOOLEAN    | NHL only: healthy scratch / did not dress |
| jersey         | TEXT       | number worn in THAT game (text: '00' and '0' both exist) |
| position       | TEXT       | position abbreviation in that game; NULL for the NFL (its box score has none) |

Unique on (game_id, player_id). Index on (team_id, game_id). `team_id` added
by `sql/appearances_team_id.sql`. `player_game_stats` has no team column of
its own — join through this table on (game_id, player_id) to get a stat's side.

`seconds_played` is the canonical time column across sports:
NBA/NCAAB store whole minutes × 60, NHL stores exact seconds (from MM:SS
time on ice), NFL leaves this NULL (ESPN's box score has no playing time or
snap counts). Converting to a
display format like MM:SS happens in the Python/dashboard layer, not here.

### Game summary details (new tables)
All filled from the same one-per-game summary fetch (see `scripts/api_pulls.py`).

- **game_officials**: `official_id` SERIAL PK, `game_id` FK (cascade), `official_name`, `role` (referee, linesman, ...), `sort_order`. Unique on (game_id, official_name, role); NHL gives every official order 0, so `sort_order` is not part of the key.
- **game_summary_cache**: `game_id` PK/FK (cascade), `fetched_at`, `payload` JSONB, a trimmed copy of the summary (boxscore, gameInfo, header; about 60 to 100 KB, not the 500 KB page). Rows older than 14 days are deleted by each run. It exists so a parser change can be re-run without asking ESPN again.
- **game_plays** and **game_play_participants**: play-by-play (shot locations, hockey event types, substitutions, football down and distance). The tables exist but **nothing fills them yet**; the plays parser is a later step (it will bump `SUMMARY_PARSER_VERSION`).

The read-only `dashboard_ro` role is granted SELECT on all four by the migration.

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
| stat_name  | TEXT       | ESPN's key, e.g. 'points', 'goals', 'passing.passingYards' |
| stat_value | NUMERIC    |                                           |

Unique on (game_id, player_id, stat_name).

How ESPN's box score becomes rows (`parse_box_score()` in `api_pulls.py`):
- **Names are ESPN's camelCase keys** (`rebounds`, `faceoffsWon`, `saves`).
- **Paired stats are split:** `fieldGoalsMade-fieldGoalsAttempted` = `6-10`
  becomes `fieldGoalsMade` 6 + `fieldGoalsAttempted` 10 (same for NFL `19/31`).
- **NFL names are prefixed with their stat category** (`passing.interceptions`
  vs. `interceptions.interceptions`, `passing.sacks` vs. `defensive.sacks`),
  because ESPN reuses key names with different meanings across categories.
- **Time stats are stored in seconds** (e.g. NHL `powerPlayTimeOnIce`). The
  main playing-time key (`minutes`/`timeOnIce`) goes to
  `player_game_appearances.seconds_played` instead, not here.
- **Skipped:** blanks (`--`) and season-to-date keys (`ytdGoals`).
- **Rates and percentages are stored as given** (`savePct` 0.923,
  `yardsPerRushAttempt`, `QBRating`). Season rollups must recompute or
  average these, never sum them.
- In an NHL shootout, the extra goal credited to the winning team isn't a
  player goal, so player `goals` sum to the team score minus 1 for a
  shootout win.

A box score player who isn't in `players` yet (e.g. a preseason cut, or any
opponent player) gets a minimal row (team, league, ESPN ID, name) via
`upsert_box_score_player()`; existing players are never modified by the box
score pull. ESPN's box score has no position, so opponents' `position` is NULL.

### player_season_stats / player_career_stats
Pre-aggregated rollups of `player_game_stats`, one row per player per stat
per season type (per season, or across all seasons). Rebuilt from scratch by
`rebuild_stat_rollups()` in `db.py` at the end of every nightly run, and by
the weekly refresh whenever it corrects a box score. A full rebuild (delete +
insert in one transaction) rather than an upsert, so a corrected or removed
stat can't leave a stale total behind.

| Column         | Type        | Notes                                   |
|----------------|-------------|-----------------------------------------|
| season_stat_id / career_stat_id | SERIAL PK |                          |
| player_id      | INTEGER FK  | references players                      |
| team_id        | INTEGER FK  | season table only — `player_game_appearances.team_id` for those games (not `players.team_id`, which is the current team) |
| season_year    | INTEGER     | season table only — same meaning as `games.season_year` |
| season_type    | TEXT        | preseason / regular / postseason — never mixed together |
| stat_name      | TEXT        |                                         |
| games_played   | INTEGER     | games **this stat** was recorded for the player (per stat, not per player) |
| total_value    | NUMERIC     | SUM                                     |
| avg_value      | NUMERIC     | AVG per game played (unrounded)         |
| max_value      | NUMERIC     | best single game                        |
| updated_at     | TIMESTAMPTZ | defaults to now()                       |

Unique on (player_id, team_id, season_year, season_type, stat_name) for
season stats; (player_id, season_type, stat_name) for career stats.

**Only additive stats are rolled up.** Percentages, per-attempt averages,
ratings, and "longest" plays can't be summed, so they're left out — matched
by `NON_ADDITIVE_STAT_PATTERN` in `db.py` on the stat name after any NFL
category prefix (e.g. `savePct`, `faceoffPercent`, `rushing.yardsPerRushAttempt`,
`punting.grossAvgPuntYards`, `passing.QBRating`, `passing.adjQBR`,
`receiving.longReception`). Compute season versions from the totals
instead — e.g. save % = `saves` / `shotsAgainst`, FG% = `fieldGoalsMade` /
`fieldGoalsAttempted`, yards per carry = `rushing.rushingYards` /
`rushing.rushingAttempts` — and season longs as `MAX(stat_value)` from
`player_game_stats`. QBR/adjQBR can't be recomputed from box score data.

**"Career" means every game in this database** — our tracked teams since
data collection started (2026) — not a player's full professional career.

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
- `game_periods` and box scores are written once per game by the nightly
  pull (from a single summary fetch), then re-checked weekly by `refresh_stats.py` for 14 days after the
  game. A correction ESPN makes after that window isn't picked up.
- The rollups cover our tracked teams' players only. Opponents' box scores
  are stored, but the dashboard aggregates them from `player_game_stats`
  directly ("stats vs our team" isn't a real season line).
- `player_season_stats` / `player_career_stats` are rebuilt from scratch every night from
  `player_game_stats`, so their auto-numbered ids (`season_stat_id`, `career_stat_id`) are not
  stable between runs (the `GROUP BY` has no `ORDER BY`). Nothing references them.
- A departed player's *new* team is not recorded unless they join another tracked team.
- One ESPN data error is known and acknowledged: NHL game 401892450 (Red Wings 5, Senators 3,
  2026-10-06) has line scores summing to 4. See `ACKNOWLEDGED_PERIOD_MISMATCHES` in
  `scripts/sanity_checks.py`.
- `sql/schema.sql` is currently a Markdown snapshot, not runnable SQL — the
  Phase 1 tables can't yet be rebuilt from the repo alone.
