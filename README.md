# Sports Hub

A data pipeline and dashboard for four Indiana-area sports teams (Pacers, Purdue, Red Wings, Colts). It pulls team, player, schedule and box-score data from sports APIs into PostgreSQL and shows it in a Streamlit dashboard.

## Current Status

**Production runs 24/7 on a home lab server** (HP ProDesk 600 G4, Ubuntu Server 26.04 LTS, 8 GB RAM, NVMe), independent of any laptop. It replaced the original Raspberry Pi 4 on 2026-10-19:
- PostgreSQL 18 lives on the server
- `scripts/api_pulls.py` runs automatically every night at 4:00 AM via `cron`, and
  `scripts/refresh_stats.py` every Sunday at 5:00 AM
- The Streamlit dashboard runs as a systemd service (`sports-hub-dashboard`) on port 8501
- The server is reachable remotely via [Tailscale](https://tailscale.com) for private access from anywhere (phone, work, etc.)
- The dashboard (only) is public at **https://sportshub.taildca027.ts.net** via Tailscale
  Funnel. If it ever stops resolving, it's usually Tailscale's DNS (see tailscale/tailscale#21429);
  a clean `tailscale funnel --https=443 off`, wait 20s, `tailscale funnel --bg 8501` fixed it once
- Postgres itself is **not** exposed to the public internet. It listens on `localhost` only
- The old Raspberry Pi (Tailscale name `sportshub-old`, Postgres 17) was **retired on 2026-10-19**, after the server ran its own nightly pipeline successfully once. It is powered off with its dashboard and Postgres services disabled, its cron jobs removed and its Funnel off. Its SSD is intact, so it can be booted again if ever needed. A final backup (database dump, crontab, service file, logs) is on the server in `~/pi-final-backup/`. See "Migrating to a new server" below for how the move was done.

The setup instructions below are for a **local development copy** (e.g. for testing script changes before deploying them to the server) — separate from the live production setup.

## Project Structure
SPORTS-HUB/
├── dashboard/ # Streamlit dashboard (run: streamlit run dashboard/app.py)
│ ├── app.py # Entry point: top page menu + filter bar (team, season, season type)
│ ├── config.py # EDIT THIS to change stats shown: tables, columns, leader tiles, team colors
│ ├── data.py # Every SQL query the dashboard runs (cached for 10 minutes)
│ ├── stats.py # Pivots long-format stats into the tables config.py describes (pandas only)
│ ├── components.py # Shared UI: headers, W/L records, formatted stat tables
│ ├── charts.py # Altair charts (margin, game log trend, leaders)
│ └── views/ # One file per page: overview, team, game (Game Center), preview, opponents, player
├── .streamlit/config.toml # Dashboard theme (colors, font)
├── scripts/
│ ├── api_pulls.py # Nightly: pulls teams, rosters, schedules, period scores, and box scores into Postgres
│ ├── refresh_stats.py # Weekly: re-checks recent games for ESPN stat corrections, rewrites only what changed
│ ├── espn.py # Shared ESPN game-summary helpers (fetch, parse line scores + box scores); no DB access
│ ├── db.py # Database connections (read-write + read-only for the dashboard) + insert/read functions
│ ├── http_client.py # fetch_json(): every API call goes through it (timeouts, retries, clear errors)
│ ├── log_setup.py # Logging setup: timestamped, rotating files in logs/
│ ├── run_report.py # RunReport: isolates failed steps, writes the summary + last_<job>.json, alerts
│ ├── leagues.py # The league registry (7 leagues), featured teams, and the LEAGUES_ALL setting
│ ├── team_discovery.py # Lists every team in a league from ESPN, with safety checks (floor count, no duplicates)
│ ├── check_leagues.py # Read-only: asks ESPN what each league lists (run it before enabling a league)
│ ├── league_gate.py # Read-only: judges one league's data PASS/FAIL/REVIEW before it is enabled for real
│ ├── roster_tracking.py # The rule for marking departed players (and its safety guard); no database code
│ ├── sanity_checks.py # Post-run checks on the finished data (duplicates, scores, box scores, row counts, freshness)
│ ├── notify.py # Phone alerts (ntfy) and "did it run?" pings (healthchecks.io), for Python
│ ├── notify.sh # The same two helpers for the bash scripts
│ ├── backup_db.sh # Nightly pg_dump into BACKUP_DIR, verified, old ones pruned (see Backups)
│ └── restore_test.sh # Weekly: restore the newest dump into a scratch DB and compare row counts
├── sql/
│ ├── schema.sql # Phase 1 schema — currently a Markdown snapshot, not runnable SQL (to be replaced)
│ ├── phase2_games_schema.sql # Phase 2 DDL: games, game_periods, sport_period_labels (+ seeds), game_id FKs
│ ├── teams_is_tracked.sql # Adds espn_id + is_tracked to teams so opponents can be stored
│ ├── games_season_type.sql # Adds season_type (preseason/regular/postseason) to games
│ ├── stat_rollups_season_type.sql # Adds season_type to season/career rollups; season -> season_year
│ ├── appearances_team_id.sql # Adds team_id to player_game_appearances so opponents' box scores can be stored
│ ├── players_roster_tracking.sql # Adds last_seen_at / departed_at to players (roster departure tracking)
│ ├── teams_is_featured.sql # Adds teams.is_featured: the four dashboard teams, separate from is_tracked
│ └── dashboard_ro_role.sql # Creates the SELECT-only dashboard_ro Postgres role used by the public dashboard
├── tests/ # Unit tests (run: venv/bin/python -m unittest discover -s tests)
├── requirements.txt # Exact package versions (pip freeze of the production venv)
├── venv/ # Python virtual environment (not tracked in git)
├── .env # API keys + DB credentials + backup settings (not tracked in git)
├── .env.example # The same variable names with placeholder values; safe to commit
├── Schema.md # Current database schema documentation (9 tables)
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

Install the pinned packages (the exact versions production runs):

```bash
pip install -r requirements.txt
```

To start a fresh venv first: `python3 -m venv venv && source venv/bin/activate`. On Ubuntu/Debian, `python3-venv` is a separate package (`sudo apt install python3-venv`).

### 3. Environment Variables

Create a `.env` file in the project root (if not already present) with (`.env.example` lists every setting):

DB_HOST=localhost
DB_PORT=5432
DB_NAME=sports_hub
DB_USER=your_mac_username
DB_PASSWORD=your_postgres_password


- `LEAGUES_ALL` (optional) lists the leagues where every team is collected, e.g. `LEAGUES_ALL=NBA,NFL`. Leave it out and only the four featured teams are collected. See "Leagues and teams".
- The pipeline no longer uses balldontlie.io, so a `BALLDONTLIE_KEY` left in an old `.env` is harmless and can be deleted.
- `DB_*` variables connect `scripts/db.py` to your local Postgres database.
- `DASHBOARD_DB_USER` / `DASHBOARD_DB_PASSWORD` (optional locally, **required on the server**) are the read-only role the dashboard connects with. Create the role with `sql/dashboard_ro_role.sql`. Without them the dashboard falls back to the read-write `DB_*` credentials.

### 4. Database

Requires a local Postgres instance (this project uses Postgres.app on macOS) with a `sports_hub` database and the full schema applied (see `Schema.md` for build order):

1. Phase 1 tables (`teams`, `players`, and the player game/season/career stat tables). `sql/schema.sql` doesn't yet contain runnable SQL for these, so for now copy them from an existing database with `pg_dump --schema-only`.
2. Phase 2 tables, which are safe to rerun:

```bash
psql -h localhost -d sports_hub -f sql/phase2_games_schema.sql
psql -h localhost -d sports_hub -f sql/teams_is_tracked.sql
psql -h localhost -d sports_hub -f sql/games_season_type.sql
psql -h localhost -d sports_hub -f sql/stat_rollups_season_type.sql
psql -h localhost -d sports_hub -f sql/appearances_team_id.sql
psql -h localhost -d sports_hub -f sql/players_roster_tracking.sql   # run right after a nightly pull (it refuses to run on stale data)
psql -h localhost -d sports_hub -f sql/teams_is_featured.sql
```

## Scripts

### `scripts/db.py`

Holds the database connection and insert logic, using `psycopg2` directly (not an ORM like SQLAlchemy) to keep the underlying SQL explicit.

- `get_connection()` — opens a read-write connection to the `sports_hub` Postgres database using the `DB_*` credentials in `.env`. Used by the pipeline scripts.
- `get_readonly_connection()` — used by the dashboard. Connects as the `dashboard_ro` role when `DASHBOARD_DB_USER` is set; otherwise falls back to `get_connection()`.
- `upsert_league_team(conn, league, espn_id, name, featured=False, founded_year=None)` — upserts a team we collect full data for, keyed on `league` + `espn_id`, and marks it `is_tracked`. On a conflict it keeps what is stored: `external_id` and venue are never touched, a stored `founded_year` is kept when none is given, and `is_featured` is only ever switched on. Safe to call repeatedly. The `capacity` column exists but is intentionally left unpopulated (ESPN doesn't return it reliably across sports).
- `set_team_venue(conn, team_id, venue, city)` — records a team's venue and city, keeping the stored values when given `None`, so a source without venue data (ESPN has none for college basketball) never erases it.
- `upsert_opponent_team(conn, league, espn_id, name)` — upserts an **opponent** team (keyed on `league` + `espn_id`) so games can reference it. Only updates name/timestamp, never tracked-team fields.
- `insert_player(conn, team_id, league, external_id, name, position, ...)` — upserts a row into `players`, with a large set of optional enrichment fields (height, weight, jersey number, birth info, college, contract summary, injury status, headshot URL, draft info). Safe to call repeatedly.

### `scripts/api_pulls.py`

Pulls team, player and game data and loads it into Postgres. **Safe to rerun anytime** — every insert is an upsert, so re-running won't create duplicate rows, only refresh existing ones. Which teams are collected comes from the league registry (see "Leagues and teams"): every team in the leagues named in `LEAGUES_ALL`, plus the four featured teams (Pacers, Purdue, Red Wings, Colts) in the others. Per-team work runs through `report.each(...)` and everything else as an isolated step (see "Monitoring and alerts"): if one fails, the rest still run, an alert is sent, and the script exits 1.

**What it does:**
1. Loads settings from `.env` and opens a Postgres connection (a typo in `LEAGUES_ALL` stops the run instead of guessing).
2. For each league (in registry order, which keeps database ids stable), makes sure every collected team has a row in `teams`: featured teams are refreshed from ESPN's team detail page (name, venue, city; the config's venue is used only when ESPN has none), and in a fully collected league every team ESPN lists is found by `team_discovery.discover_teams()` and upserted by `(league, espn_id)`. `founded_year` is recorded for the featured teams only, since no API provides it.
3. Pulls each team's full roster from ESPN's roster endpoint (`site.api.espn.com/apis/site/v2/sports/{sport}/{league}/teams/{espn_id}/roster`; flat or grouped by position, detected automatically) and upserts into `players`, including physical stats, birth info, college, contract summary, injury status and headshot URL, then marks departed players (see "Roster departures").
4. Pulls each team's preseason, regular-season, and postseason schedules from ESPN (`.../teams/{espn_id}/schedule?seasontype=1|2|3`) and upserts every game into `games`. Each opponent not already known is upserted into `teams` first (untracked) so the game's home/away team IDs have a row to point at. Reruns refresh status, scores, and schedule changes in place.
5. For every final game that doesn't have per-period scores yet, calls ESPN's `summary?event={id}` endpoint and fills in `game_periods` (regulation, overtime, and shootout rows). Only new finals are requested, so most nights this is a handful of calls.
6. For every final game that doesn't have a box score yet, uses the same `summary` endpoint to fill in `player_game_appearances` (did play, seconds played) and `player_game_stats` (one row per stat) for **both teams' players** — ours and the opponent's, each side filled in separately if missing.
7. Rebuilds `player_season_stats` and `player_career_stats` from `player_game_stats` (additive stats only — see `Schema.md`).
8. Closes the database connection.

**Run it manually (local dev):**

```bash
cd scripts
python api_pulls.py
```

**In production**, this runs automatically nightly at 4:00 AM via `cron` on the server — check `~/sports-hub/logs/pipeline.log` on the Pi for run history.

### `scripts/refresh_stats.py`

Weekly check for ESPN stat corrections. The nightly pull fills in each game's period scores and box score once; ESPN sometimes corrects stats days later. This script re-fetches every final game from the last 14 days (`LOOKBACK_DAYS`), compares ESPN's current numbers to what's stored, and rewrites a game's periods or box score **only if something changed**, printing exactly what changed (e.g. `Jonathan Taylor rushing.rushingYards: 90.0 -> 98.0`). If ESPN returns an empty box score or line score, the stored data is left alone. Game scores/status aren't part of this — the nightly schedule pull already refreshes them.

```bash
cd scripts
python refresh_stats.py
```

**In production**, meant to run weekly via `cron` on the server (Sundays at 5:00 AM, after the nightly run), logging to `~/sports-hub/logs/refresh.log`.

## Dashboard

A Streamlit web app over the Postgres data. From the project root, with the venv active:

```bash
streamlit run dashboard/app.py
```

It opens at http://localhost:8501. Run it from the project root, because Streamlit
reads the theme in `.streamlit/config.toml` from the folder you start it in.

**Pages:** Overview (all four teams, upcoming games, latest results) · Team (record,
results, player stats, leaders) · Game Preview (next games: team stats, leaders,
injuries, last five — live from ESPN, cached an hour, nothing stored) · Game Center
(scoreboard, line score, both teams' box scores) · Player (bio, season line, game
log, trend chart) · Opponents (opposing players' stats against your team). Team, season and season type are
picked in the filter bar at the top of each page and shared across pages. Pages are in
the top menu, which folds into a menu button on a phone. Clicking a row in the Team page's
results or stat tables opens that game or player.

**Changing what it shows:** almost everything is driven by `dashboard/config.py`:
- `STAT_GROUPS`: the stat tables for each league. Add, remove or reorder a line
  to change a column. `stat("PTS", "points")` is a counting stat;
  `ratio("FG%", "fieldGoalsMade", "fieldGoalsAttempted")` is a rate computed from
  season totals, never averaged game by game.
- `HEADLINE_STATS`: the leader tiles on the Team page.
- `DEFAULT_STAT_MODE`: whether each page opens on per-game averages or season
  totals (Team page: per game, Player page: totals). Both pages have a toggle.
- `stat(..., average=False)`: keeps a stat as a season total even in per-game
  mode (used for +/-).
- `TEAMS`: short names, accent colors, logos.

To add a page, create `dashboard/views/<name>.py` and add a line to the `pages`
list in `dashboard/app.py`.

## Leagues and teams

The project is built to collect **7 leagues**: NBA, NCAAB (men's D1 college basketball), NHL, NFL, WNBA, MLB and CFB (college football, FBS only). The registry in `scripts/leagues.py` describes each one (ESPN path, how to list its teams, and a minimum plausible team count). Which leagues have **every team** collected is the `LEAGUES_ALL` setting in `.env`:

```
LEAGUES_ALL=NBA,NFL       # collect every team in these leagues
                          # (leave it out: only the four featured teams are collected)
```

- **Featured teams** (`teams.is_featured`: Pacers, Purdue, Red Wings, Colts) are the teams the dashboard is built around. They are always collected, even in a league that isn't in `LEAGUES_ALL`.
- **Tracked teams** (`teams.is_tracked`) are the teams we collect full data for (rosters, schedules, box scores, rollups). Turning a league on never changes the dashboard: its pickers and pages read `is_featured`.
- Turning a league **off** (removing it from `LEAGUES_ALL`) stops collecting it but leaves its data and its `is_tracked` flags in place.

**Before enabling a league**, check it:

```bash
venv/bin/python scripts/check_leagues.py            # all 7 leagues
venv/bin/python scripts/check_leagues.py NBA WNBA   # just these
```

It is read-only (ESPN only, no database) and fails if a league lists fewer teams than expected. Then try the league on a copy of the database first (never first on live data): run the pipeline against it with the league enabled (`LEAGUES_ALL=NBA DB_NAME=sports_hub_staging ...`), and judge the result with the gate tool:

```bash
DB_NAME=sports_hub_staging venv/bin/python scripts/league_gate.py NBA
```

It is read-only (the database connection is opened read-only, so it cannot change anything), prints one PASS / FAIL / REVIEW line per check and exits 1 if anything fails. Add the league to `LEAGUES_ALL` on the server only when every line passes and any REVIEW line has been looked at:

1. **Team count** equals what ESPN lists.
2. **Rosters:** every team has at least the league's `min_roster` confirmed players.
3. **Box scores** exist for 99%+ of the tracked sides of final games.
4. **Period scores** exist and add up to the final score for 99%+ of final games (known ESPN errors in `ACKNOWLEDGED_PERIOD_MISMATCHES` are excluded).
5. **Rollup totals** match an independent re-addition of the box scores, per stat and season type.
6. **Stat names:** any name that is summed but looks like a rate (percentages, averages, ERA, OPS...) is listed for review; add real rates to `NON_ADDITIVE_STAT_PATTERN` in `db.py`. Note that pattern is case-sensitive (`Avg` is excluded, `avg` is not), so a league whose stats use other capitalization needs its names checked here.
7. **Last run** of the pipeline was clean (status ok, no warnings, no sanity problems) and within the time budget (default 25 minutes).
8. **Featured teams** are still exactly the four dashboard teams.

**Traps found by probing ESPN** (all defended against in `team_discovery.py` and covered by tests):
- The teams endpoint returns only the **first 50 teams** unless `limit` is passed, with no count or paging field, so a truncated list looks complete. Every list is requested with `limit=1000` and must reach the league's `min_teams` floor.
- College football's team list has **762 teams** of every level and ignores a division filter; the 138 FBS teams come from ESPN's FBS standings.
- ESPN's scoreboard rejects date ranges (HTTP 400) and **college scoreboards hide about half the games by default**, so the nightly schedule sync uses per-team schedules, which are complete by construction.
- Numeric team ids work everywhere an abbreviation does (the Colts' `ind` is not needed).

**Adding a league** means adding an entry to `LEAGUES` (and a parser if its box-score format is new: WNBA and college basketball reuse the NBA's, college football reuses the NFL's, MLB needs its own), then following the gate above. The first four leagues in the registry (NBA, NCAAB, NHL, NFL) must stay first and in that order: database rows are numbered in insertion order, so changing it would change ids.

## Running in production (home lab server)

Everything lives in `/home/<server-user>/sports-hub` on the server (Ubuntu Server 26.04 LTS,
Python 3.14, PostgreSQL 18). The Mac reaches it over Tailscale with an ed25519 key (a
`~/.ssh/config` entry named `homelab`); the retired Pi still has an entry, `pi`, that only works if it is booted again.
The server's Tailscale name is `sportshub`.

**Scheduled jobs** (`crontab -l`; the file must end with a newline or the last line is
silently skipped):
```
0 4 * * * cd /home/<server-user>/sports-hub && flock -n /tmp/sports_hub.lock venv/bin/python scripts/api_pulls.py >> logs/pipeline.cron.log 2>&1
0 5 * * 0 cd /home/<server-user>/sports-hub && flock -w 3600 /tmp/sports_hub.lock venv/bin/python scripts/refresh_stats.py >> logs/refresh.cron.log 2>&1
```
`flock` is a lock: the pipeline skips (`-n`) if another run still holds it, and the weekly refresh waits (`-w`, up to an hour) instead, so the two never overlap. The scripts write their real logs themselves (`logs/pipeline.log`, `logs/refresh.log`, rotating); the `*.cron.log` files catch only crashes that happen before logging starts.

**Dashboard service**: `/etc/systemd/system/sports-hub-dashboard.service` runs
`venv/bin/streamlit run dashboard/app.py --server.address 0.0.0.0 --server.port 8501`
from the project folder, starts at boot, and restarts if it crashes.
- Status: `systemctl status sports-hub-dashboard`
- Logs: `journalctl -u sports-hub-dashboard -n 50`
- Restart (after pulling new code): `sudo systemctl restart sports-hub-dashboard`

**Where to open it**
- Your own devices, anywhere: Tailscale on → http://sportshub.taildca027.ts.net:8501
- Anyone with the link: https://sportshub.taildca027.ts.net (Tailscale Funnel)
  - Status: `tailscale funnel status`
  - Turn off: `tailscale funnel --https=443 off` / back on: `tailscale funnel --bg 8501` (no `sudo`
    needed: the server user is set as Tailscale operator via `sudo tailscale set --operator=$USER`)
  - If a device says the link can't be found but it works elsewhere, that device cached an old
    "doesn't exist" DNS answer; on a Mac: `sudo dscacheutil -flushcache; sudo killall -HUP mDNSResponder`

**Deploying a change**
1. Mac: commit, then `git push origin main`
2. Server: `cd ~/sports-hub && git pull`
3. Server: run any new `sql/*.sql` migration (`psql -v ON_ERROR_STOP=1 -f sql/<file>.sql`) —
   before the next 4 AM run if the new code depends on it
4. Server: `sudo systemctl restart sports-hub-dashboard`

The server's GitHub access is a read-only **deploy key** (`~/.ssh/sports_hub_deploy`, used for `github.com` in `~/.ssh/config`), so it can pull but never push.

If history is ever rewritten (e.g. `git filter-repo`), a plain `git pull` will fail on the Mac and the server; use `git fetch && git reset --hard origin/main` on each instead (`.env` and `venv/` are untracked, so they survive).

Python packages are pinned in `requirements.txt` (e.g. `streamlit==1.60.0 pandas==3.0.5 altair==6.2.2`). After changing the venv, refresh it with `venv/bin/pip freeze > requirements.txt`.

## Migrating to a new server

How the Pi → home lab move was done (2026-10-15 to 2026-10-19). Reusable for the next move. Keep the old machine untouched until the new one is verified.

1. **Base setup.** Install `postgresql python3-venv python3-pip`. Ubuntu 26.04 only packages PostgreSQL 18; restoring a 17 dump into 18 is supported (older → newer). Set the timezone (`timedatectl`).
2. **Code.** Create a read-only deploy key on the new server (`ssh-keygen -t ed25519`), add the `.pub` in GitHub → repo Settings → Deploy keys with write access **unchecked**, then `git clone`.
3. **Secrets and venv.** Copy `.env` machine to machine (`scp -3 old:sports-hub/.env new:sports-hub/.env`, then `chmod 600`). Never print it. Build the venv and `pip install -r requirements.txt`.
4. **Database.**
   - Create the roles and an empty DB first (`sudo -u postgres psql`): a normal (non-superuser) owner role, the `dashboard_ro` role, and `CREATE DATABASE sports_hub OWNER <role> TEMPLATE template0 ENCODING 'UTF8'`.
   - Dump from the old server: `pg_dump -Fc` (custom format).
   - Restore as the owner role: `pg_restore --single-transaction --exit-on-error --no-owner --no-acl`. `--no-acl` is needed because the dump contains an `ALTER DEFAULT PRIVILEGES FOR ROLE postgres` entry that only a superuser can run. Re-apply the `dashboard_ro` grants afterwards (the `GRANT`/`ALTER DEFAULT PRIVILEGES` lines in `sql/dashboard_ro_role.sql`; skip its `CREATE ROLE` if the role exists).
   - Verify with per-table row counts **and** a content hash (`md5(string_agg(t::text, '|' order by t::text))`), on both sides.
5. **Run.** Run `scripts/api_pulls.py` once, run the dashboard, and test every page. Then install the systemd service and cron jobs. Reboot once to prove everything starts by itself.
6. **Soak.** Leave both servers running for a night or more so the new server's own 4 AM cron runs. Compare logs and row counts before cutting over.
7. **Cutover (keeping the public URL).** On the old server: `tailscale funnel --https=443 off`, then `tailscale set --hostname=<name>-old`. On the new one: `sudo tailscale set --hostname=sportshub` and `tailscale funnel --bg 8501`. Rename the old server **first**, or Tailscale gives the new one a `-1` suffix. Public DNS came back in under a minute this time (the record already existed); budget up to about 10 minutes.
8. **Fix SSH aliases.** `~/.ssh/config` host names must follow the rename. After the change, SSH reports "REMOTE HOST IDENTIFICATION HAS CHANGED" for the reused name; compare the fingerprint it prints with `ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub` on the new machine and, if they match, run `ssh-keygen -R <name>`.
9. **Rollback.** Rename the machines back and run `tailscale funnel --bg 8501` on the old server. Its data and services are untouched.

Gotchas from this move:
- Running a long script over `ssh host 'bash -s' <<EOF`: an inner `ssh` or `psql` can swallow the rest of the script from stdin. Add `</dev/null` to inner commands that don't need input.
- Nested quotes in an `ssh 'psql -c "..."'` one-liner broke a query. Send scripts over stdin instead.
- Postgres on the new server needs a real password login test over TCP (`psql -h localhost`), not just `sudo -u postgres`, because the app connects over TCP.

## Backups

The server keeps compressed database dumps, and a weekly test proves they can actually be restored.

| What | When | Where |
|---|---|---|
| `scripts/backup_db.sh` | Daily 3:30 AM (before the 4 AM pipeline) | `~/backups/` on the server (`BACKUP_DIR`), last 30 days kept (`BACKUP_KEEP_DAYS`), log in `logs/backup.log` |
| `scripts/restore_test.sh` | Sundays 6:00 AM | Restores the newest dump into a scratch database (`RESTORE_TEST_DB`) and compares row counts with live; log in `logs/restore_test.log` |

```
30 3 * * * /home/<server-user>/sports-hub/scripts/backup_db.sh >> /home/<server-user>/sports-hub/logs/backup.log 2>&1
0 6 * * 0 /home/<server-user>/sports-hub/scripts/restore_test.sh >> /home/<server-user>/sports-hub/logs/restore_test.log 2>&1
```

- **How it stays safe:** the dump is written to a hidden `.partial` file, checked with `pg_restore -l`, and only then renamed, so a half-written backup never looks valid. Scripts stop at the first error (`set -euo pipefail`), `umask 077` makes everything private to the server user, and the folder is mode `700`.
- **One-time setup for the restore test** (needs sudo): create the empty scratch database owned by the app role. Run on the server, as one paste:
  ```bash
  set -a; . ~/sports-hub/.env; set +a
  sudo -u postgres psql -v ON_ERROR_STOP=1 -v owner="$DB_USER" -v db="$RESTORE_TEST_DB" <<'SQL'
  CREATE DATABASE :"db" OWNER :"owner" TEMPLATE template0 ENCODING 'UTF8' LOCALE 'en_US.UTF-8';
  SQL
  ```
  The scratch database is a throwaway: the script refuses to run if `RESTORE_TEST_DB` equals the live `DB_NAME`.
- **Off-machine copy:** the same disk can't protect against its own failure, so pull the dumps to another machine. From the Mac (`--ignore-existing` means it never overwrites; the destination is outside the repo):
  ```bash
  mkdir -p ~/Documents/sports-hub-backups/homelab && chmod 700 ~/Documents/sports-hub-backups
  rsync -a --ignore-existing homelab:backups/ ~/Documents/sports-hub-backups/homelab/
  ```
- **Restoring for real:** create an empty database, then `pg_restore -d <db> --no-owner --no-acl <dump>`, and re-apply the `dashboard_ro` grants (see "Migrating to a new server"). Run the restore test first to confirm the dump is good.
- **What is kept out of git:** `.gitignore` covers `.env` and every `.env.*` (except `.env.example`, which lists variable names with placeholder values), `backups/`, `*.dump`, `*.dump.partial`, `*.sql.gz`, `*.tar.gz`, `logs/`, `*.log`, keys, and `.streamlit/secrets.toml`. Backup settings live in the server's `.env`. Check with `git check-ignore -v <path>`.

## Monitoring and alerts

Three layers, so a problem reaches your phone whether a job *fails* or *never runs*:

| Layer | Catches | How |
|---|---|---|
| **Step isolation** (`RunReport`) | One API outage or format change | Each unit of work (a league's teams, box scores, rollups) runs in its own `report.step(...)`, and per-team work (rosters, schedules) runs through `report.each(...)`. A failure is logged with its traceback and the rest still runs. `each` tolerates a few failures out of many: up to 5% of the teams failing is ONE warning naming them ("3 of 362 failed: ..."); more is ONE error. The job exits 1 if any step failed. |
| **Phone alert** (ntfy) | A failed step, or a suspicious empty result (a roster or schedule returning 0 items) | `notify.py` / `notify.sh` POST a short message to your private ntfy topic. It says *what* failed, never data. Failures only; a clean run is silent. |
| **"Did it run?" check** (healthchecks.io) | Cron not firing, the server down, the job hanging | After a good run the job pings its check. A missing ping alerts you (email and ntfy). The check's schedule is `0 4 * * *` America/Indiana/Indianapolis with a 2-hour grace time. |

**Settings** live in `.env` (see `.env.example`; none of them are ever committed): `NTFY_TOPIC` (long and random: anyone who knows it can read or send to it), `HEALTHCHECK_URL` for the nightly pipeline, and optionally `HEALTHCHECK_REFRESH_URL`, `HEALTHCHECK_BACKUP_URL`, `HEALTHCHECK_RESTORE_URL`, each pointing at its own healthchecks.io check. A job with no URL set simply doesn't ping. Subscribe your phone and Mac to the topic with the ntfy app. If the topic ever leaks (e.g. in a screenshot), generate a new one in `.env`, update the healthchecks.io ntfy integration, and re-subscribe.

**Where to look when something fails**
- `logs/pipeline.log` and `logs/refresh.log`: timestamped lines with levels (INFO/WARNING/ERROR) and full tracebacks. Rotating: 5 files of up to 5 MB each. Per-player lines are DEBUG-level and not logged.
- `logs/last_pipeline.json` and `logs/last_refresh.json`: the machine-readable result of the latest run (status, duration, per-step counts, errors). The dashboard or a script can read these.
- `logs/*.cron.log`: only crashes that happen before logging starts (e.g. an import error).
- `journalctl -u sports-hub-dashboard`: the dashboard.

**Roster departures.** Each nightly roster pull marks players who were on a team's roster but are missing tonight as departed (`players.departed_at`), instead of leaving them looking current forever. Rows are never deleted. A safety rule (`roster_tracking.py`) refuses to record anything when ESPN returns an empty roster or one under 50% of the previous size, and raises a warning, so a bad response can't wipe a roster. A real mass cutdown (about 90 to 53 players) goes through, with an informational alert if more than 25% leave at once. A player who reappears is automatically marked back on the roster. A player known only from a box score (never on a roster pull) is neither on the roster nor "departed". The dashboard treats a player as "on the roster" only if `last_seen_at IS NOT NULL AND departed_at IS NULL`.

**Sanity checks** run at the end of every nightly run (`sanity_checks.py`) and look at the finished data, not at the steps: exactly the expected number of tracked teams with no duplicates; every game involves a tracked team; every final game has both scores; per-period scores add up to the final score; final games older than 36 h have a box score; the schedule pull touched at least one game during this run; and no append-only table has fewer rows than after the previous run. A failure becomes a warning (phone alert) and does not fail the run. Known upstream errors that can't be fixed (e.g. an ESPN line score that contradicts its own final score) go in `ACKNOWLEDGED_PERIOD_MISMATCHES` with the reason, so they don't alert every night; the check logs a note if ESPN later fixes one so the entry can be removed.

**API calls** all go through `http_client.fetch_json()`: 5 s connect and 30 s read timeouts, up to 3 retries (waits of 1, 2, 4 s, honoring `Retry-After`) for timeouts, dropped connections, HTTP 429 and 5xx, a 0.2 s pause between calls, and a clear `FetchError` naming the URL if it still fails. A 404 isn't retried.

**Tests:** `venv/bin/python -m unittest discover -s tests -v` (96 tests, about 3 seconds). They run a throwaway local web server that returns 500s, 404s, garbage JSON and slow replies, and check the retry, timeout and alert logic without touching any real API.

**Failure drill** (run after changing this machinery): on a throwaway copy, break something on purpose (an unreachable API URL, a wrong database name, a bad `.env` password) and confirm that the run exits 1, the other steps still run, a message reaches your phone, and the healthchecks.io check goes red. Never test against the live `.env` values without telling yourself first, since the alerts are real.

## Security

The dashboard is public (Tailscale Funnel, no login), so it is set up to do as little damage as possible if something goes wrong.

- **Read-only database role.** The dashboard connects as `dashboard_ro`, which has `SELECT` only (`sql/dashboard_ro_role.sql`). The pipeline cron jobs use the read-write `DB_*` role, which on the home lab server is a normal (non-superuser) role that owns the database. Set it up once on the server:
  1. `sudo -u postgres psql -d sports_hub` and run the `CREATE ROLE` / `GRANT` statements from `sql/dashboard_ro_role.sql` with a password of your choice (letters and numbers avoid quoting problems).
  2. Add `DASHBOARD_DB_USER=dashboard_ro` and `DASHBOARD_DB_PASSWORD=...` to the server's `.env` (no quotes, no spaces around `=`).
  3. `sudo systemctl restart sports-hub-dashboard`.
  4. Verify it can't write: `PGPASSWORD=... psql -h localhost -U dashboard_ro -d sports_hub -c "DELETE FROM teams WHERE false;"` should fail with `permission denied`.
  - Gotcha: Postgres reports "password authentication failed" even when the role doesn't exist, so check `SELECT rolname FROM pg_roles;` before debugging the password.
- **Error details are hidden.** `.streamlit/config.toml` sets `showErrorDetails = "none"`, so visitors see a generic message. The real traceback is in `journalctl -u sports-hub-dashboard`.
- **Secrets stay out of git.** `.env` is gitignored and `chmod 600` (Mac and server). The repo is public and was scanned with gitleaks (full history, no findings).
- **Keep host details out of the docs.** This repo is public, so use placeholders (`<server-user>`, `<pi-hostname>`, `<server-lan-ip>`) rather than the real username, hostname or LAN IP. Git history was rewritten on 2026-09-30 to remove them.
- **Backups stay out of the repo.** `.gitignore` covers `*backup*.sql`, `*.dump` and `.DS_Store`. Keep database dumps outside the project folder (e.g. `~/Documents/sports-hub-backups/`).

## API Notes

- **balldontlie.io** — no longer used. The pipeline used to take the Pacers' and Purdue's team identity from it (their `external_id` values still come from it); teams are now matched by ESPN id, so `BALLDONTLIE_KEY` is not needed. Its `/players` endpoint returned historically-associated players rather than the current roster, and its `/players/active` endpoint needs a paid tier, which is why rosters come from ESPN.
- **NHL API** (`api-web.nhle.com`) — public, no auth required. No longer called: the pipeline used to fetch the Red Wings schedule from it but never used the result, and removing the call means an NHL API outage can't break the nightly run.
- **ESPN API** (`site.api.espn.com`) — public, no auth required, unofficial (may change without notice). Primary source for player rosters across all sports, and for venue/city team enrichment (pro leagues only). Response shape varies noticeably by sport:
  - NBA/WNBA/college basketball rosters are a flat player list; NFL/NHL/MLB/college football rosters are grouped by position category, requiring a nested loop (detected automatically).
  - Venue data lives at `team.franchise.venue` for NBA/NHL/NFL; the college basketball team endpoint doesn't return venue data at all.

**Team identity:** teams are matched by `(league, espn_id)`, which is unique and is the key the nightly run uses, so `external_id` is never written by it. The four featured teams keep their original `external_id` values (Pacers 12, Purdue 125, Red Wings `DET`, Colts 11), and ESPN's team ids collide with them across leagues (ESPN NBA 12 is the Clippers while 12 is the Pacers' `external_id`), so never match on `external_id` with an ESPN id. A duplicate tracked team (this happened once with the Colts, 2026-08-30) is caught by the nightly sanity checks.

## Roadmap / Ideas

- [x] Store pulled data in Postgres rather than just printing
- [x] Pull full player rosters for all four teams (Pacers, Purdue, Red Wings, Colts)
- [x] Refresh `SCHEMA.md` to match the current `players` table
- [x] Add team-level enrichment: venue, city, founded year (`capacity` added to schema but intentionally left unpopulated)
- [x] Move to 24/7 infrastructure (Raspberry Pi) independent of a laptop
- [x] Migrate from the Raspberry Pi to a home lab server (Ubuntu, PostgreSQL 18), keeping the public URL (2026-10-19)
- [x] Retire the Raspberry Pi (2026-10-19; powered off, disk kept intact)
- [x] Add scheduling (`cron`) to pull data on a regular interval
- [x] Populate `games` (regular-season schedules + final scores, all four teams)
- [x] Add `season_type` to `games` and load preseason/postseason games
- [x] Populate `game_periods` (per-period scores, including OT and shootouts)
- [x] Populate `player_game_appearances` and `player_game_stats` (both teams' box scores)
- [x] Populate `player_season_stats` / `player_career_stats` rollups
- [x] Add error handling for failed requests (timeouts, retries, non-200 responses, isolated steps, alerts)
- [x] Add logging instead of print statements (rotating timestamped logs)
- [x] Nightly verified backups, a weekly restore test, and "did it run?" monitoring
- [ ] Add a mechanism to detect players who've left a team's roster (current upsert-only pattern can't remove/flag departed players)
- [x] Weekly re-check of recent games for ESPN stat corrections (`refresh_stats.py`)
- [x] Build the Streamlit dashboard (first version)
- [x] Make the dashboard publicly reachable (Tailscale Funnel, free; no custom domain)
- [x] Phase D1: league registry, automatic team discovery, `is_featured`, per-team failure tolerance (no new leagues; output proven identical)
- [ ] Phase D2-D6: collect every team: NBA/NFL/NHL, then WNBA, college basketball, college football (FBS), MLB (needs a new box-score parser)
- [ ] Phase E: dashboard league and team pickers for hundreds of teams
- [ ] Cloudflare Tunnel + own domain, if a nicer URL or login-protected access is ever wanted

## Dev Tools

This project uses:
- **Black** — code formatting
- **Ruff** — linting (including pandas-specific checks)
- **SQLTools** (VS Code) — Postgres connection and query runner. F5 is bound to run the current query (`sqltools.executeQuery`), scoped to `.sql` files so it doesn't conflict with VS Code's default Python debugging shortcut.

Config lives in `pyproject.toml` and `.vscode/settings.json` at the project root.