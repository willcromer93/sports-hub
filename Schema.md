# Sports Hub — Database Schema

Current-state documentation of the `sports_hub` Postgres database. This file
reflects what's actually live, not the original design — see
`CLAUDE_PROJECT_NOTES.md` for the dated history of how it got here.

## Tables

### teams
One row per team, across all four leagues.

| Column      | Type        | Notes                              |
|-------------|-------------|-------------------------------------|
| team_id     | SERIAL PK   |                                      |
| league      | TEXT        | 'NBA', 'NCAAB', 'NHL', 'NFL'        |
| external_id | TEXT        | ID from that team's source API      |
| name        | TEXT        |                                      |
| updated_at  | TIMESTAMPTZ |                                      |

Unique on (league, external_id).

### players
One row per player, shared across all four sports rather than per-team or
per-sport tables — filtering by `team_id`/`league` covers cross-team queries
and makes adding a new team a data-only change, not a schema change.

| Column                | Type        | Notes                                                   |
|------------------------|-------------|----------------------------------------------------------|
| player_id              | SERIAL PK   |                                                            |
| team_id                | INTEGER FK  | references teams                                          |
| league                 | TEXT        |                                                            |
| external_id            | TEXT        | ID from that player's source API                          |
| name                   | TEXT        |                                                            |
| position               | TEXT        | free text — holds NBA/NFL/NCAAB position codes AND hockey codes (C/LW/RW/D/G) |
| height_inches          | INTEGER     |                                                            |
| weight_lbs             | INTEGER     |                                                            |
| jersey_number          | TEXT        |                                                            |
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
| updated_at             | TIMESTAMPTZ |                                                            |

Unique on (league, external_id).

### games
One row per game. Not yet populated — schema exists, pull not built.

### player_game_appearances
One row per player per game. Exists as a separate table (rather than
inferring "played" from the presence of stat rows) so a missing row can be
told apart from "played and recorded a zero" — a player who didn't dress
has no row at all, distinct from a player who played but had, say, zero
rebounds.

`seconds_played` is the canonical time column across sports:
NBA stores whole minutes × 60, NHL stores exact seconds, NFL leaves this
NULL (snap counts go into `player_game_stats` instead). Converting to a
display format like MM:SS happens in the Python/dashboard layer, not here.

### player_game_stats
One row per player, per game, per stat — long format rather than wide
columns or a JSONB blob. Chosen because NBA/NHL/NFL/NCAAB each track
entirely different stat categories; long format keeps aggregation
queries (sums, averages across a season) simple regardless of sport.

### player_season_stats / player_career_stats
Pre-aggregated rollups, one row per player per stat (per season, or
all-time). Not yet populated — depends on `player_game_stats` being
populated first.

## Design decisions

- **Upsert everywhere.** All inserts use `INSERT ... ON CONFLICT DO UPDATE`,
  keyed on (league, external_id) for teams/players. The whole pipeline can
  be rerun safely without creating duplicates.
- **No permanent JSON files.** API responses go straight from Python into
  Postgres; JSON is only ever a temporary variable, never written to disk
  as a lasting artifact.
- **Raw psycopg2, not an ORM.** Deliberate choice to keep the SQL visible
  and explicit while learning, rather than abstracting it behind SQLAlchemy's
  ORM layer.

## Known gaps

- `draft_year`/`draft_round`/`draft_pick` always NULL — would need a
  different ESPN endpoint to populate.
- `games` and both stats-rollup tables exist but have no data yet.
- Team-level enrichment (venue, city, capacity, founded year) not started.