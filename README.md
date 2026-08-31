# Sports Hub

A data pipeline project that pulls team and player data for four Indiana-area sports teams (Pacers, Purdue, Red Wings, Colts) from various sports APIs and loads it into PostgreSQL, with plans to feed into a Streamlit dashboard.

## Current Status

**Production runs 24/7 on a dedicated Raspberry Pi 4**, independent of any laptop:
- PostgreSQL lives on the Pi
- `scripts/api_pulls.py` runs automatically every night at 4:00 AM via `cron`
- The Pi is reachable remotely via [Tailscale](https://tailscale.com) for private access from anywhere (phone, work, etc.)
- Postgres itself is **not** exposed to the public internet — reachable only via Tailscale or from the Pi itself

The setup instructions below are for a **local development copy** (e.g. for testing script changes before deploying them to the Pi) — separate from the live production setup running on the Pi.

## Project Structure
SPORTS-HUB/
├── dashboard/ # Dashboard/visualization layer (not started yet — blocked on games table)
├── scripts/
│ ├── api_pulls.py # Pulls team + player data from external sports APIs, upserts into Postgres
│ └── db.py # Database connection + insert functions (get_connection, insert_team, insert_player)
├── sql/
│ └── schema.sql # Full Postgres schema (7 tables)
├── venv/ # Python virtual environment (not tracked in git)
├── .env # API keys + DB credentials (not tracked in git)
├── SCHEMA.md # Current database schema documentation
├── CLAUDE_PROJECT_NOTES.md # Dated running log of project progress/decisions
└── .gitignore


## Setup (Local Development)

### 1. Virtual Environment

Activate the existing virtual environment:

```bash
# macOS/Linux
source venv/bin/activate

# Windows
venv\Scripts\activate
```

### 2. Dependencies

Install required packages:

```bash
pip install requests python-dotenv psycopg2-binary
```

### 3. Environment Variables

Create a `.env` file in the project root (if not already present) with:

BALLDONTLIE_KEY=your_api_key_here

DB_HOST=localhost
DB_PORT=5432
DB_NAME=sports_hub
DB_USER=your_mac_username
DB_PASSWORD=your_postgres_password


- `BALLDONTLIE_KEY` is required for [balldontlie.io](https://www.balldontlie.io/) API calls (used for NBA/NCAAB team identity).
- `DB_*` variables connect `scripts/db.py` to your local Postgres database.

### 4. Database

Requires a local Postgres instance (this project uses Postgres.app on macOS) with a `sports_hub` database and the schema in `sql/schema.sql` already applied.

## Scripts

### `scripts/db.py`

Holds the database connection and insert logic, using `psycopg2` directly (not an ORM like SQLAlchemy) to keep the underlying SQL explicit.

- `get_connection()` — opens a connection to the `sports_hub` Postgres database using the credentials in `.env`.
- `insert_team(conn, league, external_id, name, venue=None, city=None, capacity=None, founded_year=None)` — upserts a row into `teams`. Safe to call repeatedly; updates existing rows instead of erroring on duplicates. `capacity` exists as a column but is intentionally left unpopulated (ESPN doesn't return it reliably across sports).
- `insert_player(conn, team_id, league, external_id, name, position, ...)` — upserts a row into `players`, with a large set of optional enrichment fields (height, weight, jersey number, birth info, college, contract summary, injury status, headshot URL, draft info). Safe to call repeatedly.

### `scripts/api_pulls.py`

Pulls team and player data for all four teams and loads it into Postgres. **Safe to rerun anytime** — every insert is an upsert, so re-running won't create duplicate rows, only refresh existing ones.

| Team | League | Team Identity Source | Player Roster Source |
|------|--------|-------------------|------------------------|
| Indiana Pacers | NBA | balldontlie.io | ESPN roster API |
| Purdue | NCAAB | balldontlie.io | ESPN roster API |
| Detroit Red Wings | NHL | NHL Web API (`api-web.nhle.com`) | ESPN roster API |
| Indianapolis Colts | NFL | ESPN Site API | ESPN roster API |

**What it does:**
1. Loads API keys/DB credentials from `.env` and opens a Postgres connection.
2. Pulls team identity for all four teams from their respective sources and upserts into `teams`, along with venue/city/founded_year enrichment (venue/city sourced from ESPN's team endpoint for NBA/NHL/NFL; hardcoded for Purdue, since ESPN's college basketball endpoint doesn't return venue data. `founded_year` is hardcoded for all four teams — no API provides it).
3. Pulls full player rosters for all four teams from ESPN's roster endpoint (`site.api.espn.com/apis/site/v2/sports/{sport}/{league}/teams/{team_id}/roster`) and upserts into `players`, including physical stats, birth info, college, contract summary (current season + total value/years/expiration), injury status, and headshot URL.
4. Closes the database connection.

**Run it manually (local dev):**

```bash
cd scripts
python api_pulls.py
```

**In production**, this runs automatically nightly at 4:00 AM via `cron` on the Pi — check `~/sports-hub/logs/pipeline.log` on the Pi for run history.

## API Notes

- **balldontlie.io** — requires an `Authorization` header with your API key. Used for NBA/NCAAB team identity only (kept stable/unchanged from original inserts — see note below). Its `/players` endpoint returns historically-associated players rather than current roster, and its `/players/active` endpoint (which would fix that) requires a paid tier — so player rosters are pulled from ESPN instead.
- **NHL API** (`api-web.nhle.com`) — public, no auth required. Used for Red Wings team identity/schedule only; rosters come from ESPN.
- **ESPN API** (`site.api.espn.com`) — public, no auth required, unofficial (may change without notice). Primary source for player rosters across all sports, and for venue/city team enrichment (pro leagues only). Response shape varies noticeably by sport:
  - NBA/NCAAB rosters are a flat player list; NFL/NHL rosters are grouped by position category, requiring a nested loop.
  - Venue data lives at `team.franchise.venue` for NBA/NHL/NFL; the college basketball team endpoint doesn't return venue data at all.

**Important — team `external_id` stability:** Pacers/Purdue keep their original balldontlie-sourced `external_id` values, and Red Wings keeps `"DET"`. These are never changed to an ESPN ID, even though ESPN is used for enrichment — changing a team's `external_id` would break the `ON CONFLICT (league, external_id)` upsert match and create a duplicate row rather than updating the existing team. (This exact bug happened once with the Colts during Pi migration and was manually cleaned up — see `CLAUDE_PROJECT_NOTES.md`, 2026-08-30.)

## Roadmap / Ideas

- [x] Store pulled data in Postgres rather than just printing
- [x] Pull full player rosters for all four teams (Pacers, Purdue, Red Wings, Colts)
- [x] Refresh `SCHEMA.md` to match the current `players` table
- [x] Add team-level enrichment: venue, city, founded year (`capacity` added to schema but intentionally left unpopulated)
- [x] Move to 24/7 infrastructure (Raspberry Pi) independent of a laptop
- [x] Add scheduling (`cron`) to pull data on a regular interval
- [ ] Populate `games`, `player_game_stats`, and related tables — currently empty, blocking dashboard work
- [ ] Add error handling for failed requests (non-200 responses, timeouts)
- [ ] Add logging instead of print statements
- [ ] Add a mechanism to detect players who've left a team's roster (current upsert-only pattern can't remove/flag departed players)
- [ ] Build the Streamlit dashboard (blocked on `games` table)
- [ ] Cloudflare Tunnel to make the dashboard publicly reachable

## Dev Tools

This project uses:
- **Black** — code formatting
- **Ruff** — linting (including pandas-specific checks)
- **SQLTools** (VS Code) — Postgres connection and query runner. F5 is bound to run the current query (`sqltools.executeQuery`), scoped to `.sql` files so it doesn't conflict with VS Code's default Python debugging shortcut.

Config lives in `pyproject.toml` and `.vscode/settings.json` at the project root.