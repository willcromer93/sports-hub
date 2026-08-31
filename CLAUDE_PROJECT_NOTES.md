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
  ├── sql/             # SQL scripts/queries (schema.sql lives here)
  ├── venv/            # virtual environment
  ├── .env             # API keys + DB credentials (not shared/committed)
  ├── .gitignore
  ├── pyproject.toml   # Black/Ruff config
  └── .vscode/
      └── settings.json
  ```
- **Database:** PostgreSQL (Postgres.app on macOS), database name `sports_hub`, connected via SQLTools in VS Code. Full 7-table schema applied — see `SCHEMA.md` for table layout and reasoning.
- **Tools already set up:** Python, Pylance, Black (formatter), Ruff (linter), SQLTools + Postgres driver, python-dotenv for API keys.
- **APIs in use:**
  - **ESPN hidden API** (`site.api.espn.com`) — used for Colts team info, and now the primary source for *all* player roster data (Pacers, Purdue, Red Wings, Colts — all four teams complete as of 2026-08-29).
## A standing ask

Since the goal is for me to learn, please:
- Point out when something is a common Python/SQL pattern I should recognize in the future (e.g., "this is called list comprehension — you'll see this pattern a lot").
- Flag when there's a "beginner mistake" I should watch out for, even if my code technically works.
- Feel free to suggest small practice exercises related to what we just built, if it seems useful — but only suggest, don't assume I want extra work every time.

## Progress Log

*(Newest entries at the bottom. This is a running diary of what was done and why — for full schema reasoning, see `SCHEMA.md`, which stays updated to reflect current structure rather than history.)*

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