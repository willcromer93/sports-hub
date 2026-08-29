# Sports Hub — Database Schema

*Last verified against live database: 2026-08-29*

## teams
Core reference table — one row per team, across all 4 leagues.

| Column | Type | Nullable | Notes |
|---|---|---|---|
| team_id | integer | NO | Primary key |
| league | text | NO | e.g. 'NBA', 'NCAAB', 'NHL', 'NFL' |
| external_id | text | NO | ID/abbreviation from the source API (e.g. ESPNs `ind` for Colts) |
| name | text | NO | |
| updated_at | timestamptz | NO | Set on insert/upsert |

## players
One row per player, shared across all leagues (not per-team tables — filtered by `team_id`).

| Column | Type | Nullable | Notes |
|---|---|---|---|
| player_id | integer | NO | Primary key |
| team_id | integer | YES | FK to teams |
| league | text | NO | |
| external_id | text | NO | ESPN athlete ID |
| name | text | NO | |
| position | text | YES | Free-text; holds both ball-sport positions (PG, WR) and hockey codes (C, LW) |
| height_inches | numeric | YES | |
| weight_lbs | numeric | YES | |
| jersey_number | text | YES | Text, not integer — some jerseys have letters/suffixes |
| birth_date | date | YES | |
| birth_city | text | YES | |
| birth_state | text | YES | |
| birth_country | text | YES | |
| experience_years | integer | YES | |
| status | text | YES | Active/injured/etc. |
| college | text | YES | |
| headshot_url | text | YES | |
| contract_salary | numeric | YES | |
| contract_season | integer | YES | |
| contract_total_value | numeric | YES | |
| contract_years | integer | YES | |
| contract_expires | date | YES | |
| injury_status | text | YES | Cleaned status text (fixed from earlier raw-dict bug) |
| draft_year | integer | YES | Always NULL currently — ESPN roster endpoint doesn't return draft info |
| draft_round | integer | YES | Same as above |
| draft_pick | integer | YES | Same as above |
| shoots_catches | text | YES | 'L'/'R' — hockey-specific (shoots for skaters, catches for goalies) |
| updated_at | timestamptz | NO | |

## games
Structure exists; **not yet populated** — this is the Phase 2 target.

| Column | Type | Nullable | Notes |
|---|---|---|---|
| game_id | integer | NO | Primary key |
| team_id | integer | NO | FK to teams |
| external_id | text | NO | Source API's game ID |
| game_date | date | NO | |
| season | text | YES | |
| opponent | text | YES | |
| is_home | boolean | YES | |
| venue | text | YES | |
| attendance | integer | YES | |
| team_score | integer | YES | |
| opponent_score | integer | YES | |
| status | text | YES | e.g. scheduled/final/in-progress |
| raw_data | jsonb | YES | Full raw API response, kept for reprocessing without re-fetching |
| inserted_at | timestamptz | NO | |

## player_game_appearances
Distinguishes "didn't play" from "played, stat untracked" from "played, recorded zero."

| Column | Type | Nullable | Notes |
|---|---|---|---|
| appearance_id | integer | NO | Primary key |
| game_id | integer | NO | FK to games |
| player_id | integer | NO | FK to players |
| did_play | boolean | NO | |
| seconds_played | integer | YES | Raw seconds; MM:SS formatting deferred to dashboard layer |

## player_game_stats
Long-format: one row per player/game/stat name (not wide columns), since stat categories differ wildly by sport.

| Column | Type | Nullable | Notes |
|---|---|---|---|
| stat_id | integer | NO | Primary key |
| game_id | integer | NO | FK to games |
| player_id | integer | NO | FK to players |
| stat_name | text | NO | e.g. 'points', 'goals', 'passing_yards' |
| stat_value | numeric | NO | |

## player_season_stats
Aggregated per player/team/season/stat.

| Column | Type | Nullable | Notes |
|---|---|---|---|
| season_stat_id | integer | NO | Primary key |
| player_id | integer | NO | FK to players |
| team_id | integer | NO | FK to teams |
| season | text | NO | |
| stat_name | text | NO | |
| games_played | integer | NO | |
| total_value | numeric | NO | |
| avg_value | numeric | NO | |
| max_value | numeric | NO | |
| updated_at | timestamptz | NO | |

## player_career_stats
Same shape as season stats, but career-wide (no season/team dimension).

| Column | Type | Nullable | Notes |
|---|---|---|---|
| career_stat_id | integer | NO | Primary key |
| player_id | integer | NO | FK to players |
| stat_name | text | NO | |
| games_played | integer | NO | |
| total_value | numeric | NO | |
| avg_value | numeric | NO | |
| max_value | numeric | NO | |
| updated_at | timestamptz | NO | |

## Design principles
- **Shared tables, not per-team tables** — filter by `team_id`/`league` instead of duplicating table structure 4x.
- **Long-format stats** — one row per stat rather than one wide column per stat, since NBA/NFL/NHL/NCAAB stat categories dont overlap.
- **Upsert pattern** — `INSERT ... ON CONFLICT ... DO UPDATE` throughout, so reruns are safe.
- **`player_game_appearances` exists separately from `player_game_stats`** to avoid "missing row = zero" ambiguity.