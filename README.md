# Sports Hub

A data pipeline project that pulls team and player data for four Indiana-area sports teams (Pacers, Purdue, Red Wings, Colts) from various sports APIs and loads it into a local PostgreSQL database, with plans to feed into a Streamlit dashboard.

## Project Structure

```
SPORTS-HUB/
├── dashboard/          # Dashboard/visualization layer (not started yet)
├── scripts/
│   ├── api_pulls.py    # Pulls team + player data from external sports APIs, inserts into Postgres
│   └── db.py            # Database connection + insert functions (get_connection, insert_team, insert_player)
├── sql/
│   └── schema.sql       # Full Postgres schema (7 tables)
├── venv/                 # Python virtual environment (not tracked in git)
├── .env                  # API keys + DB credentials (not tracked in git)
└── .gitignore
```

## Setup

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

```
BALLDONTLIE_KEY=your_api_key_here

DB_HOST=localhost
DB_PORT=5432
DB_NAME=sports_hub
DB_USER=your_mac_username
DB_PASSWORD=your_postgres_password
```

- `BALLDONTLIE_KEY` is required for [balldontlie.io](https://www.balldontlie.io/) API calls (used for NBA/NCAAB team info).
- `DB_*` variables connect `scripts/db.py` to your local Postgres database.

### 4. Database

Requires a local Postgres instance (this project uses Postgres.app on macOS) with a `sports_hub` database and the schema in `sql/schema.sql` already applied.

## Scripts

### `scripts/db.py`

Holds the database connection and insert logic, using `psycopg2` directly (not an ORM like SQLAlchemy) to keep the underlying SQL explicit.

- `get_connection()` — opens a connection to the `sports_hub` Postgres database using the credentials in `.env`.
- `insert_team(conn, league, external_id, name)` — upserts a row into `teams`. Safe to call repeatedly; updates existing rows instead of erroring on duplicates.
- `insert_player(conn, team_id, league, external_id, name, position, ...)` — upserts a row into `players`, with a large set of optional enrichment fields (height, weight, jersey number, birth info, college, contract summary, injury status, headshot URL, draft info). Safe to call repeatedly.

### `scripts/api_pulls.py`

Pulls team and player data for all four teams and loads it into Postgres. **Safe to rerun anytime** — every insert is an upsert, so re-running won't create duplicate rows, only refresh existing ones.

| Team | League | Team Info Source | Player Roster Source |
|------|--------|-------------------|------------------------|
| Indiana Pacers | NBA | balldontlie.io | ESPN roster API |
| Purdue | NCAAB | balldontlie.io | *(not yet built)* |
| Detroit Red Wings | NHL | NHL Web API (`api-web.nhle.com`) | *(not yet built)* |
| Indianapolis Colts | NFL | ESPN Site API | ESPN roster API |

**What it does:**
1. Loads API keys/DB credentials from `.env` and opens a Postgres connection.
2. Pulls team info for all four teams from their respective sources and upserts into `teams`.
3. Pulls full player rosters for the Pacers and Colts from ESPN's roster endpoint (`site.api.espn.com/apis/site/v2/sports/{sport}/{league}/teams/{team_id}/roster`) and upserts into `players`, including physical stats, birth info, college, contract summary (current season + total value/years/expiration), injury status, and headshot URL.
4. Closes the database connection.

**Run it:**

```bash
cd scripts
python api_pulls.py
```

## API Notes

- **balldontlie.io** — requires an `Authorization` header with your API key. Used for NBA/NCAAB *team* info. Its `/players` endpoint returns historically-associated players rather than current roster, and its `/players/active` endpoint (which would fix that) requires a paid tier — so player rosters are pulled from ESPN instead.
- **NHL API** (`api-web.nhle.com`) — public, no auth required. Currently used for Red Wings team info only. A dedicated current-roster endpoint exists (`/v1/roster/{team}/current`) but isn't wired in yet.
- **ESPN API** (`site.api.espn.com`) — public, no auth required, unofficial (may change without notice). Used for Colts team info and is now the primary source for player rosters across all sports. Response shape varies by sport — NBA/NCAAB rosters are a flat player list; NFL rosters are grouped by position category (offense/defense/special teams/etc.), requiring a nested loop.

## Roadmap / Ideas

- [x] Store pulled data in Postgres rather than just printing
- [x] Pull full player rosters (not just team info) — done for Pacers, Colts
- [ ] Pull player rosters for Purdue and Red Wings
- [ ] Refresh `SCHEMA.md` to match the current `players` table (several columns added since it was last written)
- [ ] Add team-level enrichment: venue, city, capacity (founded year likely needs manual hardcoding — no API provides it)
- [ ] Populate `games`, `player_game_stats`, and related tables
- [ ] Add error handling for failed requests (non-200 responses, timeouts)
- [ ] Add scheduling (cron / task scheduler) to pull data on a regular interval
- [ ] Add logging instead of print statements
- [ ] Build the Streamlit dashboard

## Dev Tools

This project uses:
- **Black** — code formatting
- **Ruff** — linting (including pandas-specific checks)
- **SQLTools** (VS Code) — Postgres connection and query runner. F5 is bound to run the current query (`sqltools.executeQuery`), scoped to `.sql` files so it doesn't conflict with VS Code's default Python debugging shortcut.

Config lives in `pyproject.toml` and `.vscode/settings.json` at the project root.