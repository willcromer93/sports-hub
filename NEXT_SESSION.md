# Start here: handoff for a new Claude session

*Last updated 2026-10-25, late evening. Read this file first, then only the LAST 2-3 entries of
`CLAUDE_PROJECT_NOTES.md` (it is a long dated log; do not read it top to bottom).*

## What this project is

Sports Hub: a pipeline plus a public Streamlit dashboard. Goal (confirmed by Will): collect **7 leagues, every
team** (NFL, NHL, NBA, WNBA, MLB, college basketball men's D1 = code `NCAAB`, college football FBS = `CFB`),
current season only, from ESPN's unofficial API. It runs 24/7 on a home-lab server (Ubuntu, PostgreSQL 18),
reached over Tailscale. The Raspberry Pi it replaced was retired 2026-10-19.

## Where things stand

| Phase | Status |
|---|---|
| Migration Pi to home lab, backups, restore test, alerts (ntfy + healthchecks.io), logging, roster departures, sanity checks | **done and live** |
| D1 engine (league registry, automatic team discovery, `teams.is_featured`, per-team failure tolerance) | **done and live** |
| D2 NBA + NFL + NHL, every team | **live** since 2026-10-25 |
| D3 WNBA, every team | **live** since 2026-10-25 |
| D4 college basketball (362 teams) | next; prerequisite below |
| D5 college football (FBS, 138 teams), D6 MLB (needs a new box-score parser) | after D4 |
| Phase E: **full redesign of the website and its tabs** (Will's request: look AND navigation, for ~640 teams) | after the leagues are loading; design first, then build |

`LEAGUES_ALL=NBA,NFL,NHL,WNBA` is set in the server's `.env`: 109 teams collected nightly (plus the four
featured teams: Pacers, Purdue, Red Wings, Colts). The dashboard still shows only the four featured teams.

## Quick health check (do this before anything else)

On the Mac the SSH alias `homelab` reaches the server (`ssh homelab`; check `hostname` prints `homelab`).
- `~/sports-hub/logs/last_pipeline.json`: the last nightly run (04:00); expect `status: ok`, 0 warnings.
- `crontab -l` shows the nightly pipeline (04:00), weekly refresh (Sunday 05:00), backup (03:30), restore test (Sunday 06:00).
- The public site `https://sportshub.taildca027.ts.net` returns 200; the healthchecks.io check is green.

## Next task: D4 preparation, then college basketball

1. **Merge the period-score and box-score steps** in `scripts/api_pulls.py` so each finished game's ESPN summary is
   fetched ONCE (today both steps fetch the same page: 1,186 calls for 368 WNBA games on a first load). At college
   scale that doubles ESPN's load. Prove the data is identical with an A/B on a database copy (compare ignoring
   auto-numbered ids, since processing order may change them).
2. Decide the `summary gaps` threshold for college (small-school games often have no ESPN summary at all; the check
   currently warns above 5% of a league's finals), add weekly college roster refresh and season-aware schedule fetching.
3. Then follow the league procedure below for `NCAAB`.

## The procedure for enabling any league (proven three times; do not skip steps)

1. `scripts/check_leagues.py LEAGUE` (read-only: does ESPN list the expected number of teams?).
2. Fresh backup, restore it into **`sports_hub_staging`** (permanent practice database), re-apply the read-only
   grants (the GRANT lines of `sql/dashboard_ro_role.sql`).
3. Trial run with `LEAGUES_ALL=...` and `DB_NAME=sports_hub_staging`, **alerts blanked as EMPTY strings**
   (`NTFY_TOPIC="" HEALTHCHECK_URL=""`; unsetting them is not enough because `load_dotenv()` puts them back), isolated `LOG_DIR`.
4. Judge it: `DB_NAME=sports_hub_staging python scripts/league_gate.py LEAGUE` (8 checks, PASS/FAIL/REVIEW), then test all
   24 dashboard pages as the read-only role. Run the trial twice (second run must change nothing).
5. **Ask Will before touching live.** On approval: fresh backup; apply any new migration on live BEFORE pushing the code; push and
   pull; edit `LEAGUES_ALL`; first load by hand in the background (same command as cron, with its lock); gate on live; 24 pages;
   second run. Rollback = remove the league from `LEAGUES_ALL` (data stays).
6. Update README, `Schema.md`, a dated entry in `CLAUDE_PROJECT_NOTES.md`, and the memory status; commit locally; ask before pushing.

## How Will wants to work (also in `CLAUDE.md`)

- Will is a data engineer learning Python and SQL by building this: go slowly, define new terms, explain the why.
- **Ask before** anything on the live database or server that is hard to undo, any push to the public repo, and any step
  needing `sudo` (give the exact command, explain it, wait for confirmation). Never enter passwords.
- Never print `.env` values, the ntfy topic or the healthchecks URL; the repo is public, so keep real usernames, IPs and secrets out of it.
- Prove claims: a before/after comparison on a database copy beats "should be fine". Report failures plainly.

## Things learned the hard way (details in the notes)

- ESPN's teams endpoint returns only 50 teams without `limit`, with no count field; the `groups=` filter is ignored; the CFB
  team list has 762 teams (FBS comes from the FBS standings, 138); scoreboard date ranges return 400; college scoreboards hide
  about half the games, so schedules are fetched per team.
- ESPN returns **transient 404s** for valid URLs (retried), and some finished games have **no summary at all** (flagged in
  `games.summary_unavailable_at`, skipped, rechecked after 3 days).
- A league with no row in the `sport_period_labels` table silently gets NO period scores, so every new league needs a row there
  (WNBA, CFB and MLB rows exist now).
- `NON_ADDITIVE_STAT_PATTERN` in `scripts/db.py` is case-sensitive and written for football/basketball names: baseball's
  `AVG`, `OBP`, `SLG`, `ERA`, `OPS`, `WHIP` would be summed in rollups; extend it before MLB (the gate flags such names).
- ESPN's own data is occasionally inconsistent (3 NHL games whose home line score is one goal short); acknowledged in
  `ACKNOWLEDGED_PERIOD_MISMATCHES` in `scripts/sanity_checks.py`.
- A long-running Streamlit service keeps the code it started with: dashboard changes need `sudo systemctl restart sports-hub-dashboard`.

## Open housekeeping

Rotate the ntfy topic (it appeared once in a screenshot): new value in the server `.env`, update the healthchecks.io ntfy
integration, re-subscribe phone and Mac. Optional: extra healthchecks.io checks for backup/refresh/restore test, a UPS for the server.

## Key files

`scripts/api_pulls.py` (nightly pipeline) · `leagues.py` (registry) · `team_discovery.py` · `league_gate.py` · `sanity_checks.py` ·
`run_report.py` · `http_client.py` · `db.py` · `sql/` (migrations) · `tests/` (run: `venv/bin/python -m unittest discover -s tests`, 118 tests) ·
`README.md` (full operating manual) · `Schema.md` · `CLAUDE_PROJECT_NOTES.md` (dated log).
