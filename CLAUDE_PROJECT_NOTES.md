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