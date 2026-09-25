# Working With Claude on Sports Hub — Notes for Claude

This file exists so that any Claude conversation about this project starts with the same context, instead of me re-explaining it every time. If you're Claude reading this: please follow these preferences for the rest of the conversation.

## Who I am

- I'm a data engineer by trade, so I understand data concepts, pipelines, and how to spot trends once data is in front of me.
- I have **very limited hands-on experience with Python and SQL specifically**. Assume I know almost nothing about syntax, tooling, or conventions in these languages.
- I'm comfortable with the *data visualization* side — reading trends, interpreting results, deciding what a dashboard should show.
- This is a **passion project**, and the main goal is for me to actually **learn Python and SQL** by building it, not just to get a working app as fast as possible.

## How I want you to explain things

- **Go slow.** Don't assume I know what a term means just because it's common in Python/SQL — define it briefly the first time it comes up (e.g., "a virtual environment is basically an isolated copy of Python for this project so packages don't conflict with other projects").
- **Explain the "why," not just the "what."** I want to understand the reasoning behind a piece of code or a decision, not just copy-paste it.
- **Step-by-step, one thing at a time.** When giving instructions (especially for setup, file placement, or running something), number the steps and don't skip steps that seem "obvious" — they may not be obvious to me yet.
- If I ask a clarifying question, assume I need it broken down further, not less. Err on the side of over-explaining rather than under-explaining.

## How I want file changes handled

- It depends on the complexity:
  - **Simple stuff** (small edits, one file, low risk): just make the change directly and tell me what you changed and why.
  - **Bigger or more complex changes** (new files, structural changes, anything touching config or credentials): walk me through it — show me the code, tell me exactly where the file goes, and let me create/save it myself so I understand the mechanics.
- When in doubt, ask me which I'd prefer for that specific change rather than assuming.

## Project context (as of now)

- **Project:** Sports Hub — pulling data on Indiana-area teams (Pacers, Purdue, Red Wings, Colts) from various sports APIs, storing/processing it, and eventually visualizing it in a dashboard.
- **Structure:**
  ```
  SPORTS-HUB/
  ├── dashboard/       # visualization layer
  ├── scripts/         # Python scripts (e.g. api_pulls.py)
  ├── sql/             # SQL scripts (schema.sql, phase2_games_schema.sql)
  ├── venv/            # virtual environment
  ├── .env             # API keys + DB credentials (not shared/committed)
  ├── .gitignore
  ├── pyproject.toml   # Black/Ruff config
  └── .vscode/
      └── settings.json
  ```
- **Database:** PostgreSQL (Postgres.app on macOS), database name `sports_hub`, connected via SQLTools in VS Code. Production database lives on the Pi (see README); the Mac holds a local dev copy. 9 tables — see `Schema.md` for table layout, reasoning, and build order.
- **Tools already set up:** Python, Pylance, Black (formatter), Ruff (linter), SQLTools + Postgres driver, python-dotenv for API keys.
- **APIs in use:**
  - **ESPN hidden API** (`site.api.espn.com`) — used for Colts team info, and now the primary source for *all* player roster data (Pacers, Purdue, Red Wings, Colts — all four teams complete as of 2026-08-29).
  - **balldontlie.io** — team identity for Pacers and Purdue.
  - **NHL Web API** (`api-web.nhle.com`) — team identity for the Red Wings.

## A standing ask

Since the goal is for me to learn, please:
- Point out when something is a common Python/SQL pattern I should recognize in the future (e.g., "this is called list comprehension — you'll see this pattern a lot").
- Flag when there's a "beginner mistake" I should watch out for, even if my code technically works.
- Feel free to suggest small practice exercises related to what we just built, if it seems useful — but only suggest, don't assume I want extra work every time.

## Progress Log

*(Newest entries at the bottom. This is a running diary of what was done and why — for full schema reasoning, see `Schema.md`, which stays updated to reflect current structure rather than history.)*

### 2026-07-29
- Installed Postgres (Postgres.app on macOS). Located `psql` at
  `/Applications/Postgres.app/Contents/Versions/18/bin/psql`, added to PATH via `~/.zshrc`.
- Created `sports_hub` database. Connects via Mac username; local socket (`psql postgres`)
  needs no password, but SQLTools (TCP, `localhost:5432`) required setting one via
  `ALTER USER ... WITH PASSWORD ...`.
- Designed and applied full schema (`sql/schema.sql`) — 7 tables:
  `teams`, `players`, `games`, `player_game_appearances`, `player_game_stats`,
  `player_season_stats`, `player_career_stats`. Full reasoning in `SCHEMA.md`.
- Verified all 7 tables visible and connected in SQLTools.

**Next up:** install `psycopg2-binary`, add DB connection details to `.env`, write
`insert_team()` and wire it into `scripts/api_pulls.py`, starting with the `teams` table
(no dependencies on other tables, good first target).


### 2026-08-29
- Verified current database state directly via SQLTools rather than trusting these notes, since the file had drifted out of sync with reality. Query used:
```sql
  SELECT t.name AS team_name, t.league, COUNT(p.player_id) AS player_count
  FROM teams t
  LEFT JOIN players p ON p.team_id = t.team_id
  GROUP BY t.name, t.league
  ORDER BY t.league;
```
- **Confirmed all four player pulls are complete and working:**
  - Indiana Pacers (NBA): 18 players
  - Purdue Boilermakers (NCAAB): 12 players
  - Indianapolis Colts (NFL): 98 players
  - Detroit Red Wings (NHL): 32 players
- **Confirmed several previously-open bugs are already resolved** (not caught in notes at the time they were fixed):
  - `shoots_catches` column exists on `players` and is populated correctly (`L`/`R`) for Red Wings players.
  - `injury_status` is storing clean status text (e.g. `Out`, `NULL`) — the earlier issue of it storing a raw stringified dict is fixed.
  - `colts_id` NameError no longer applies — Colts are inserting fine (98 players).
  - `position` column holds sensible free-text values across sports (confirmed hockey codes like `C`, `LW` alongside NBA/NFL positions).
- **Lesson learned:** these notes can drift out of sync with the actual database state when work happens across sessions without a note update at the end. Going forward, when picking back up after a gap, verify current state directly against the database (via `information_schema.columns` for schema, `COUNT()` queries for row counts) rather than trusting the notes as ground truth.
- Also confirmed real table structure while debugging the above: `teams` primary key is `team_id` (not `id`), `players` primary key is `player_id` — worth remembering for future joins.

**Next up:**
- Refresh `SCHEMA.md` — confirm it matches the current `players` table (it was already known to be behind as of the last entry).
- Team-level enrichment (venue, city, capacity, founded year) — still not started.
- Move to Phase 2: `games` table population, then eventually the Streamlit dashboard.

### 2026-08-29 (continued) — Schema refresh, team enrichment, Pi setup begins

**Schema documentation:**
- Refreshed `SCHEMA.md` in full against live `information_schema.columns` output — now accurately reflects all 7 tables, including every column added to `players` since the doc was last updated.

**Team-level enrichment:**
- Added `venue`, `city`, `capacity`, `founded_year` columns to `teams` via `ALTER TABLE`. `capacity` added but intentionally left unused/NULL — decided not to populate it (ESPN doesn't return it reliably across sports); candidate for a future `DROP COLUMN` cleanup, not urgent.
- Updated `insert_team()` in `db.py` to thread the three used fields (`venue`, `city`, `founded_year`) through all four upsert locations, same pattern as the earlier `shoots_catches` fix.
- Updated `api_pulls.py`: added `extract_team_venue_fields()` helper. Pacers/Purdue/Red Wings keep their original balldontlie/NHL team-identity calls unchanged (critical: changing `external_id` source would break `ON CONFLICT` matching and create duplicate rows) — an extra ESPN request was added per team purely for venue/city enrichment.
- **Per-sport quirk discovered:** ESPN's pro-sport team endpoints (NBA, NHL, NFL) nest venue at `team.franchise.venue`; the college basketball endpoint (`mens-college-basketball`) doesn't return venue data at all. Purdue's venue/city (`Mackey Arena`, `West Lafayette`) ended up hardcoded instead, same as `founded_year` for all four teams.
- **Founded years used:** Pacers 1967, Purdue 1896 (first basketball season), Red Wings 1926, Colts 1984 (Indianapolis relocation, not the 1953 Baltimore founding — deliberate choice).
- **Verified all four teams enriched correctly** via live pipeline run: Pacers/Gainbridge Fieldhouse/Indianapolis, Purdue/Mackey Arena/West Lafayette, Red Wings/Little Caesars Arena/Detroit, Colts/Lucas Oil Stadium/Indianapolis.
- Noted (not a bug): `team_id` sequence values are "gappy" (e.g. Colts = 66) due to repeated test reruns during development — `SERIAL` sequences advance on every `INSERT` attempt, even ones that resolve via `ON CONFLICT` into an update rather than a true insert. Cosmetic only; left as-is rather than risking a renumber against the FK in `players.team_id`.

**Raspberry Pi setup — Phase 1 complete (headless OS + connectivity):**
- Goal: move the DB, pipeline, and eventual dashboard onto a Raspberry Pi 4 (1GB RAM) + 256GB USB SSD, running 24/7 independent of the laptop. Website will be public-facing eventually (Colts stadium ethernet planned); DB will stay private, accessible only via Tailscale — never exposed directly to the internet.
- Flashed Raspberry Pi OS Lite (64-bit) to the SSD via Raspberry Pi Imager, headless (no monitor/keyboard) — hostname `sportshub`, user `wcromer`, WiFi + SSH pre-configured through Imager's Customisation step.
- **Bug hit and resolved:** Pi (4 years old) had firmware predating reliable USB-boot support — powered on with solid red (power) LED but no green (activity) LED at all, meaning it couldn't find anything bootable on the SSD. Fixed using the 128GB SD card: flashed Raspberry Pi Imager's "Misc utility images → Bootloader → USB Boot" image (a small one-time firmware updater, not a full OS) to the SD card, booted from it once to update the Pi's EEPROM, then swapped back to the SSD. Confirmed working via SSH afterward.
- SSH connection confirmed working: `ssh wcromer@sportshub.local`. Ran `sudo apt update && sudo apt upgrade -y` to bring the fresh OS current.
- **Roadmap reminder (from earlier in session):**
  1. ~~Flash OS, get SSH working~~ ✅ done today
  2. Install Postgres on the Pi, migrate the database over
  3. Move `api_pulls.py`/`db.py` onto the Pi, get cron running the pipeline nightly
  4. Set up Tailscale for private remote access (to Pi/DB)
  5. Build the Streamlit dashboard
  6. Cloudflare Tunnel to make just the dashboard publicly reachable

**Next up:**
- Phase 2: install Postgres on the Pi, figure out how to migrate the existing database over from the Mac (likely `pg_dump`/`pg_restore`, not yet discussed in detail).
- Revisit `capacity` column on `teams` — either populate manually or drop it.

### 2026-08-30 — Postgres on the Pi, migration, deployment, cron, Tailscale

**Postgres installed on the Pi:**
- Installed via `apt`, running as Postgres 17 (matches Mac's version — no compatibility concerns).
- Created matching `willcromer` role and `sports_hub` database on the Pi, mirroring the Mac setup so no application code needed to change.
- Verified connectivity the same way the app will connect (`psql -h localhost`, not a shortcut/socket connection).

**Database migrated from Mac to Pi:**
- Used `pg_dump` (Mac) → `scp` → `psql` import (Pi). Straightforward plain-SQL dump/restore, no `pg_restore`/custom format needed at this data size.
- **Bug found and fixed during verification:** row counts came back as 5 teams / 162 players instead of expected 4 / 160. Root cause: an orphaned duplicate Colts row (`external_id` of `'ind'` vs `'11'` from two different script versions over time) that `ON CONFLICT` never recognized as the same team, so it silently kept creating a second one instead of updating. Fixed by repointing the 4 players that had drifted onto the orphaned `team_id`, then deleting the orphaned team row. Final verified counts: 4 teams / 162 players (the +2 players vs. the last known-good count is legitimate roster churn, not a bug).
- **Design gap surfaced, not yet solved:** the pipeline only ever adds/updates players via upsert — it has no mechanism to detect or flag a player who's left a team's roster entirely. Worth a future fix (e.g. a "seen in this run" flag or a periodic true reconciliation pass).

**Pipeline code deployed to the Pi:**
- Installed Python tooling (`python3-pip`, `python3-venv`) on the Pi.
- Set up a GitHub **deploy key** (SSH, read-only) specifically for the Pi rather than reusing the Mac's PAT — avoids any interactive-auth dependency for a headless machine.
- Cloned the repo, recreated `.env` (copied via `scp`, then edited DB host values to `localhost` since the pipeline now runs on the same machine as its database) and the `venv` with `psycopg2-binary` (binary build specifically — plain `psycopg2` risks failing to compile on the Pi's ARM chip).
- Manually ran `api_pulls.py` on the Pi successfully — fast, no issues from the 1GB RAM ceiling on this workload.

**Cron automation set up — hit and fixed two real bugs:**
- Scheduled `api_pulls.py` to run nightly at 4:00 AM via `crontab -e`, output redirected to `~/sports-hub/logs/pipeline.log`.
- **Bug 1 — silent cron failure:** first night's job never ran at all, with zero error anywhere. Root cause: a missing trailing newline after the crontab entry — a well-known cron gotcha where the last line silently gets ignored if the file doesn't end cleanly. Confirmed via a live near-term test (scheduled a job a few minutes out, watched it fail identically) before fixing by rewriting the crontab cleanly with a proper trailing newline. Re-tested and confirmed firing correctly afterward.
- **Bug 2 — stale code on the Pi:** the first successful cron run used an old version of `api_pulls.py`/`db.py`, missing the venue/city/founded_year enrichment work — because that commit was made locally on the Mac but never `git push`ed before the Pi was cloned. No data was lost (confirmed via direct query — the old code's default-`None` arguments never overwrote the existing values), but it's a good reminder: **local commits don't help other machines until pushed.** Fixed via `git push` (Mac) → `git pull` (Pi), re-verified with a manual run showing correct enrichment output again.
- Cron is now confirmed working end-to-end and trusted for tonight's real 4 AM run.

**Tailscale set up for private remote access:**
- Installed on both the Pi and the Mac, signed into the same account, verified SSH reachable via the Pi's Tailscale IP (`100.x.x.x`) instead of `.local`/local-WiFi-only addressing.
- This is the access method intended for reaching the Pi/database from anywhere going forward — Postgres itself still isn't exposed to the public internet.

**Roadmap status:**
1. ~~Flash OS, get SSH working~~ ✅
2. ~~Install Postgres on the Pi, migrate the database~~ ✅
3. ~~Move pipeline onto the Pi, get cron running nightly~~ ✅
4. ~~Set up Tailscale~~ ✅
5. Build the Streamlit dashboard — **paused**: `games` table is still empty, so there's no game/score data to actually show yet. Decided to build out Phase 2 of the data pipeline (games table population) before returning to the dashboard.
6. Cloudflare Tunnel to make the dashboard public — not started.

**Next up:** back to data pipeline work — populating the `games` table (schedules, scores) across all four sports, likely the next full session's focus.

### 2026-09-24 — Schema audit, Phase 2 games DDL captured

**Schema audit (local Mac database — the Pi was off, not re-verified):**
- Compared `information_schema` against the docs. The database has **9 tables**, not 7: `game_periods` (per-period box-score line) and `sport_period_labels` (4 seed rows: NBA Quarter/4, NCAAB Half/2, NHL Period/3, NFL Quarter/4) had been added without being documented.
- `games` had already been redesigned to a home/away layout (`home_team_id`/`away_team_id` both referencing `teams`, `season_year`, `game_time` timestamptz, `status` limited to scheduled/in_progress/final/postponed/canceled, unique on `(league, external_id)`). No doc described it, and the SQL that created it wasn't saved anywhere.
- Other drift fixed in `Schema.md`: `teams` enrichment columns were missing; `height_inches`/`weight_lbs` are `numeric`, not integer.
- Found that `sql/schema.sql` is a Markdown copy of the schema docs, not runnable SQL — still to be fixed.
- Found that the **local** database still has the orphaned duplicate Colts row (`team_id` 4, `external_id` `'ind'`, 4 players) that was cleaned up only on the Pi on 2026-08-30. Local is 5 teams / 162 players; the Pi should be 4 / 162. Local Postgres is 18.6 (the Pi is 17).

**Phase 2 DDL captured:**
- Wrote `sql/phase2_games_schema.sql`: creates `games` → `game_periods` → `sport_period_labels` (+ seeds), then adds the `game_id` foreign keys on `player_game_stats`/`player_game_appearances`. Idempotent (`IF NOT EXISTS`, `ON CONFLICT DO NOTHING`, a `DO` block checking `pg_constraint` for the FKs) and wrapped in one transaction.
- Tested on throwaway databases: a fresh build (run twice) matches the local schema line-for-line apart from one cosmetic NOT NULL constraint name (`games_id_not_null`, left over from the `id` → `game_id` rename). Running it against a copy of the existing schema changes nothing.
- Refreshed `Schema.md` and the README to match.

**Open design question:** `games.home_team_id`/`away_team_id` must both reference `teams`, which only holds our 4 teams, so opponents need rows in `teams` before any game can load.

**Next up:**
- Decide how to store opponents, then build the games pull.
- When the Pi is back on: run the same `information_schema` check there, and apply `phase2_games_schema.sql` if `games` is still the old design.
- Turn `sql/schema.sql` into real Phase 1 DDL.
- Clean up the orphaned Colts row in the local database.

### 2026-09-24 (continued) — Opponents support in `teams` (espn_id + is_tracked)

- **Problem:** `games.home_team_id`/`away_team_id` must both reference `teams`, which only held our 4 teams.
- **Catch:** ESPN's team IDs collide with existing `external_id` values — ESPN NBA 12 = LA Clippers (Pacers' balldontlie `external_id` is `12`), ESPN NCAAB 125 = Grand Valley State (Purdue's is `125`). Storing opponents with ESPN IDs as `external_id` would have made the upsert overwrite the Pacers row with the Clippers.
- **Fix — `sql/teams_is_tracked.sql`** (applied to the local DB): new `espn_id` column, unique per league; new `is_tracked` boolean (default false); `external_id` made nullable (NULLs don't clash in a UNIQUE constraint); backfilled the 4 tracked teams (Pacers 11, Purdue 2509, Red Wings 5, Colts 11).
- **`db.py`:** `insert_team()` now takes `espn_id` (kept via `COALESCE` if omitted) and sets `is_tracked = true`. New `upsert_opponent_team()` keyed on `(league, espn_id)`, for the games pull to call for each game's non-tracked team.
- **`api_pulls.py`:** passes `espn_id` in all 4 `insert_team()` calls.
- Opponents will be added **as they appear in schedules** rather than by pre-loading every team in each league — this also covers Purdue's non-D1 opponents.
- Verified: tested on a throwaway copy first (reruns safe; the Clippers upsert made a new untracked row and didn't touch the Pacers). Then ran the full pipeline locally — exit 0, all 4 teams updated in place with no new team rows.
- Local player count went from 162 → 192. That's roster churn since the last local run (Red Wings camp roster alone is 51), and departed players are never removed — the known roster-departure gap.

**Next up:**
- Build the games pull: `insert_game()` in `db.py` + schedule pull in `api_pulls.py`. ESPN `teams/{id}/schedule` defaults to the current phase (preseason right now), so pass `seasontype=2` for the regular season.
- On the Pi: `git pull`, then run `phase2_games_schema.sql` (if needed) and `teams_is_tracked.sql` **before** the next 4 AM cron run — the new code will fail without the columns.

### 2026-09-24 (continued) — Games pull built

- **`db.py`:** added `insert_game()`, an upsert on `(league, external_id)` (ESPN event ID). Reruns refresh status, scores, times, and venue.
- **`api_pulls.py`:** added `pull_games()` plus two helpers, `map_espn_status()` and `extract_score()`. It runs after all four teams are inserted, loops over the tracked teams, calls `upsert_opponent_team()` for the non-tracked side of each game, then `insert_game()`.
- **ESPN quirks found:**
  - `/schedule` defaults to the current phase (preseason right now) — `seasontype=2` selects the regular season.
  - Scores come as `{"value": 23.0, ...}` and are missing until a game starts.
  - ESPN has many status names (e.g. `STATUS_HALFTIME`), but each also has a simple state (`pre`/`in`/`post`), which is what gets mapped to our 5 allowed values.
  - `season.year` is the end year for NBA/NHL/NCAAB (2027) but the start year for the NFL (2026).
  - 25 of Purdue's 28 games have `timeValid=False` (start time TBD).
  - The schedule has no per-period scores; ESPN's `summary?event={id}` endpoint does.
- **Verified locally:** ran the pipeline twice (exit 0 both times). Loaded 209 games (NBA 80, NCAAB 28, NHL 84, NFL 17) and 99 opponents (104 teams total, 4 tracked); the second run didn't change any counts. Colts' two final scores are correct (Ravens 41–23 at home, 30–33 at Chiefs). Neutral-site games are flagged (London, Mexico City, Las Vegas). Every game has exactly one tracked team.

**Next up:**
- `game_periods`: call `summary` only for final games that don't have period rows yet.
- Decide on preseason/postseason — needs a `season_type` column on `games` first.
- Maybe a `time_tbd` flag for unannounced start times.
- Pi deploy: `git pull`, then the two migrations, before the next 4 AM run.

### 2026-09-24 (continued) — season_type + game_periods pull

**`season_type`:**
- `sql/games_season_type.sql` adds `games.season_type` (`preseason`/`regular`/`postseason`). It's added with `DEFAULT 'regular'` to fill in the 209 existing rows, then the default is dropped, so forgetting to set it fails loudly instead of mislabeling a playoff game.
- `pull_games()` now loops over ESPN season types 1/2/3 (`ESPN_SEASON_TYPES`), and `insert_game()` takes `season_type`.

**`game_periods`:**
- `db.py`: `get_games_missing_periods()` (the first read-only query function) finds final games with no period rows. `insert_game_periods()` writes all of a game's periods with a single commit, so a game can't end up half-filled and then be skipped forever by the "missing periods" check.
- `api_pulls.py`: `pull_game_periods()` calls ESPN `summary?event={id}` only for those games. `build_periods()` labels ESPN's unlabeled list: the first N entries (from `sport_period_labels.regulation_periods`) are regulation, then overtime, and the last entry is the shootout when the status is `Final/SO`. Numbering restarts for each type.
- ESPN facts: in NHL shootouts the winner's shootout entry is `1`, so periods always sum to the final score. NCAAB overtime works like the NBA (2 halves + OT).
- Tested `build_periods()` first against 8 of last season's games (regular finishes, NBA OT and 2OT, NCAAB OT, NHL OT and shootout, NFL OT) — all 8 summed to their final scores.

**Verified locally:** migration applied, then 2 pipeline runs (exit 0 both). 220 games (+11 preseason), 107 teams, 8 finals → 33 period rows. Every game's periods match its final score, including Colts at Chiefs (OT) and a Red Wings preseason shootout at Columbus. The second run filled 0 games (nothing re-fetched).

**Pi deploy now needs 3 migrations, in order:** `phase2_games_schema.sql` → `teams_is_tracked.sql` → `games_season_type.sql`, then `git pull` + a manual run, before a 4 AM cron run.

**Next up:** player box scores (`player_game_appearances`/`player_game_stats`) — the same `summary` response has a `boxscore` section.

### 2026-09-24 (continued) — Player box scores

- **`db.py`:**
  - `get_games_missing_box_scores()` finds final games with no appearance rows, plus the tracked team in each.
  - `upsert_box_score_player()` gets a `player_id`, adding a minimal row for anyone not already in `players`. It uses the `ON CONFLICT DO UPDATE SET name = players.name` trick, because `DO NOTHING` doesn't return the id.
  - `insert_box_score()` writes appearances and stats with a single commit per game.
- **`api_pulls.py`:** `parse_box_score()` flattens ESPN's box score, and `pull_box_scores()` covers only our team's side of each game.
- **ESPN box score quirks:**
  - Basketball has one stat group per team; NHL groups by position (forwards/defenses/goalies); NFL groups by stat category (passing/rushing/defensive/...).
  - Paired stats are strings like `"6-10"` / `"19/31"`.
  - NBA minutes are whole numbers (`"17"`) and NHL time on ice is `"12:50"`.
  - Only basketball lists DNPs (`didNotPlay`).
  - NFL reuses key names across categories — `interceptions` (thrown vs. caught), `sacks` (taken vs. made) — hence the `category.` prefix for NFL.
- **Tested the parser first** on 7 of last season's games:
  - NBA and NCAAB player points summed to the final score. Minutes summed to exactly 240 (regulation), 290 (NBA 2OT) and 225 (NCAAB OT).
  - NFL rushing yards matched ESPN's team totals.
  - NHL player goals matched in an OT game; in a shootout win they're 1 short, because the shootout goal isn't credited to a player.
- **Verified locally:** 2 pipeline runs (exit 0 both). 8 final games → 265 appearances and 2,725 stat rows. The second run added nothing. Every box score player was already in `players` (the upsert-only roster pull had kept the preseason cuts), so there were 0 new player rows. Red Wings player goals match their final scores in all 3 preseason games.

**Next up:** season/career rollups from `player_game_stats` (a SQL `INSERT ... SELECT ... GROUP BY`) — sum counting stats, but recompute rates/percentages rather than summing them.

### 2026-09-24 (continued) — Weekly stat-correction refresh

- **Goal:** pick up ESPN stat corrections after a game, but only write to the database when something actually changed.
- **Refactor:** moved the ESPN summary parsing (`build_periods`, `parse_box_score`, etc.) out of `api_pulls.py` into a new `scripts/espn.py`, plus `fetch_summary()`, `parse_periods()`, `parse_team_box_score()` and a single `SPORT_PATHS` map. Reason: `api_pulls.py` runs top to bottom on import, so another script couldn't reuse its functions without re-running the whole nightly pull.
- **`db.py`:**
  - Read functions `get_recent_final_games()`, `get_game_periods()` and `get_box_score()`. They return the same shapes the ESPN parsers produce, so stored and fresh data compare directly.
  - `insert_game_periods()` / `insert_box_score()` gained `replace=True`, which deletes the game's rows and reinserts them in the same transaction, so a stat ESPN removed doesn't linger.
  - New `box_score_rows()` (shared player-id lookup).
- **`scripts/refresh_stats.py`:**
  - Re-fetches final games from the last 14 days (`LOOKBACK_DAYS`; a weekly run checks each game twice).
  - Compares ESPN's periods and box score to what's stored, and rewrites only on a difference, logging each change.
  - Skips (never writes) if ESPN returns empty data, so an ESPN glitch can't wipe good rows.
- **Verified locally:**
  - The nightly pipeline after the refactor made identical data (same row counts and checksum; 0 new periods/box scores).
  - The refresh on untouched data found 0 changes across 5 games.
  - Simulated corrections: changed a rushing total, added a fake stat, deleted a player's whole box score line, and changed an NHL period score. The refresh caught all 4, restored the data to an exact checksum match, and the next run found 0 changes.

**Pi cron — add when the Pi is back** (`crontab -e`). Mirror the existing nightly line's paths, run Sundays at 5 AM, and **keep a trailing newline** (the silent-failure gotcha from 2026-08-30):
```
0 5 * * 0 cd ~/sports-hub/scripts && ~/sports-hub/venv/bin/python refresh_stats.py >> ~/sports-hub/logs/refresh.log 2>&1
```

### 2026-09-24 (continued) — Season and career totals

- **Schema problem found:** the rollup tables predated the games redesign. They had no `season_type`, so preseason, regular-season and playoff numbers would have been mixed together, and `player_season_stats.season` was text while `games.season_year` is an integer.
- **Fix — `sql/stat_rollups_season_type.sql`:** adds `season_type` to both tables, renames and retypes `season` → `season_year integer`, and swaps the unique keys to include `season_type`. Tested twice on a throwaway schema copy before applying locally.
- **`db.py` → `rebuild_stat_rollups()`:**
  - Two `INSERT ... SELECT ... GROUP BY` queries (SUM / AVG / MAX / COUNT).
  - Full rebuild inside one transaction rather than an upsert, so a corrected or removed stat can't leave a stale total.
  - The season `team_id` comes from the tracked team in each game, not `players.team_id` (which can be stale).
- **Additive stats only:**
  - `NON_ADDITIVE_STAT_PATTERN` excludes percentages, per-attempt averages, QB ratings and "long" plays. Checked against every stat name from all 4 sports: 17 excluded, 99 kept.
  - Season rates should be recomputed from totals (e.g. save % = saves / shotsAgainst). QBR can't be.
- **Called from:** the end of `api_pulls.py` (nightly), and `refresh_stats.py` whenever a box score changed.
- **Verified locally:**
  - 1,436 season and career rows.
  - All 1,436 season totals, game counts and maxes match a direct re-aggregation of the box scores (0 mismatches), and none are missing.
  - 0 non-additive stats in the rollups. Career totals = season totals (only one season of data so far).
  - Reruns give the same counts.
  - Sample: Jonathan Taylor — 2 games, 190 rushing yards, 95.0/game, best game 98.

**Pi deploy now needs 4 migrations, in order:** `phase2_games_schema.sql` → `teams_is_tracked.sql` → `games_season_type.sql` → `stat_rollups_season_type.sql`.


### 2026-09-25 — Streamlit dashboard, first version

- **Layout (`dashboard/`):**
  - `app.py` sets up navigation and the sidebar filters.
  - `config.py` holds every "what to show" choice.
  - `data.py` has all the SQL.
  - `stats.py` does the pandas reshaping.
  - `components.py` / `charts.py` hold shared UI and charts.
  - `views/` has one file per page.
  - The theme is in `.streamlit/config.toml` at the project root.
- **Pages:** Overview, Team (Results / Player stats / Leaders tabs), Game Center, Player.
- **Config-driven stats:** tables are defined per league in `STAT_GROUPS` using two builders:
  - `stat()` for counting stats, which can add several keys together, e.g. NHL PTS = goals + assists.
  - `ratio()` for rates, which are always recomputed from summed totals.
  - A group's `requires` key decides who appears, e.g. only goalies have `saves`.
- **Why not the rollup tables:** the dashboard aggregates straight from
  `player_game_stats` rather than reading `player_season_stats`. This is so rates like FG% and SV%
  can be recomputed from totals, and so a game log and a season line always come from the same numbers.
  - Playing time is unioned in from `player_game_appearances` as a pseudo-stat (`seconds_played`).
- **Streamlit gotchas hit:**
  - Values pulled out of pandas are `numpy.int64`, which psycopg2 can't send. `run_query()` converts them with `.item()`.
  - NULLs come back as `NaN` (a float), so bio fields are checked with `pd.notna()`, not truthiness.
  - `.values` drops a timestamp's timezone.
  - Streamlit forgets a widget's value on pages that don't draw it. `persisted_widget()` keeps the real value in `st.session_state`.
- **Verified:**
  - Every page ran for all four teams against the local DB with no errors (Streamlit's `AppTest`).
  - Screenshots were checked in headless Chrome.
  - The Colts box score (Sep 20 @ KC, 30–33 OT) matches the stored line score, and Red Wings preseason leaders render.
  - The Pacers and Purdue pages show empty states until their games start.

**Next up:**
- Deploy to the Pi (install streamlit/pandas/altair in the Pi venv; keep it on Tailscale only until the Cloudflare Tunnel step).
- Blank cells in stat tables show as a grey "None" (Streamlit's default). Could be swapped for "—".

### 2026-09-25 (continued) — Per-game averages, season-type labels

- **Per-game averages everywhere:**
  - `DEFAULT_STAT_MODE` is now "Per game" for all four leagues. The Team page's Per game / Totals toggle is still there.
  - Averaged columns are relabelled `PTS/G` (via `stat_header()` in `components.py`) so an average is never mistaken for a total. Rates like FG% keep their name.
  - Player page tiles show the per-game average, with the season total underneath.
- **Preseason vs. regular season vs. postseason:**
  - The sidebar's Season type filter was already there. Now it's also visible on the pages:
    - Team page: a colored badge next to the season (grey Preseason / blue Regular season / violet Postseason).
    - Game Center: the same badge under the score.
    - Overview: a "Type" column that flags preseason/postseason games and stays blank for regular season.
  - Overview's Upcoming and Latest results tables are now stacked full-width. Side by side, the extra column got cut off.

### 2026-09-25 (continued) — Per-page stat defaults, +/- as a total

- `stat()` in `config.py` takes `average=False` for stats that should always show as a season total. +/- uses it, because a per-game plus/minus isn't a useful number.
  - `stats.is_averaged()` is the one place that decides whether a column is averaged. Tables, "/G" labels, number formats and leader rules all ask it.
- `DEFAULT_STAT_MODE` is now per page instead of per league:
  - Team page opens on **Per game**.
  - Player page opens on **Totals**.
  - Both pages have a Per game / Totals toggle, and each opens back on its default when you return to it.
- Player tiles show the selected mode as the big number and the other mode underneath ("0.3 per game" or "1 total").

### 2026-09-25 (continued) — Opponent box scores + Game Preview

**Decisions (asked, then built):**
- The pregame preview comes **live from ESPN** when the page opens, cached for an hour. No tables, so nothing to wipe after the game.
- **Full opponent box scores are stored permanently**, the same way as our own teams'.

**Schema — `sql/appearances_team_id.sql`:**
- Adds `player_game_appearances.team_id`: which side the player was on *in that game*.
- Backfilled from the tracked team, since every earlier row was ours. Then set NOT NULL, with an index on (team_id, game_id).
- `player_game_stats` gets its side by joining on (game_id, player_id). I checked first that no stat row lacks an appearance (0 found).
- Tested twice on a throwaway copy (`createdb -T`) before applying locally.

**Pipeline:**
- `get_games_missing_box_scores()` works per side, not per game. The 8 existing finals got just their opponent side filled in.
- `insert_box_score()` takes `team_id`, and `replace=True` only deletes that side.
- `get_box_score()` and `get_recent_final_games()` are per side.
- `refresh_stats.py` checks both sides and fetches each ESPN summary once per game.
- `fetch_summary()` now has a 30-second timeout.
- Rollups take the team from `a.team_id` and stay limited to tracked teams, so their meaning is unchanged.

**Verified locally:**
- Our own box scores and both rollup tables have **identical md5 checksums** before and after.
- 8 opponent sides were added: 265 → 511 appearances, 192 → 436 players.
- Opponent NHL player goals match final scores (Columbus shows 0 for its 1-0 shootout win, as expected).
- A pipeline rerun added 0 sides.
- The weekly refresh caught a real ESPN correction (Daniel Jones adjQBR 73.0 → 73.8). A second run found 0 changes.

**Dashboard:**
- Every "our players" query filters on `a.team_id`. Before this, a Colts page would have included the opponents' players from the same game.
- New **Game Preview** page: team stats side by side, leaders with headshots, injuries, last five games, and previous meetings from our DB.
- New **Opponents** page: this season or all seasons, all opponents or one, per game or totals.
- Game Center shows both box scores in tabs.
- Blank cells show "—" (`st.dataframe(placeholder=...)`), and an all-blank Pos column is hidden. ESPN box scores don't include positions, so opponents have none.
- ESPN writes the winner's score first ("33-30 OT"). The last-five table flips losses to our-score-first and keeps the OT/SO suffix.

**Pi deploy (in order):** `git pull` → `psql -d sports_hub -f sql/appearances_team_id.sql` → manual `api_pulls.py` run. It **must** happen before the next 4 AM cron run, because the new `insert_box_score()` writes `team_id` and will fail without the column.
