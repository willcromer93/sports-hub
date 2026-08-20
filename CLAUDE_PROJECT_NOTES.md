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
- **APIs in use so far:** balldontlie.io (NBA/NCAAB, needs API key), NHL public API, ESPN public API.

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
