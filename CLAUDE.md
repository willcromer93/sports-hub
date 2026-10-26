# Sports Hub: instructions for Claude

**Read `NEXT_SESSION.md` first**: it says where the project stands, what to do next, the proven procedure for
enabling a league, and how Will wants to work. Then read only the last 2-3 entries of `CLAUDE_PROJECT_NOTES.md`
(a long dated log; do not read it top to bottom). `README.md` is the operating manual and `Schema.md` the database reference.

## Working rules

- Will is a data engineer learning Python and SQL by building this. Go slowly, define new terms the first time,
  explain the why, and prefer teaching over speed.
- **Ask before:** anything on the live database or server that is hard to undo, any push to the public repo, and any step
  that needs `sudo` (give the exact command, explain each part, wait for confirmation). Never type passwords.
- Test every new league on `sports_hub_staging` first, judge it with `scripts/league_gate.py`, and get Will's approval before
  enabling it on live. Apply database migrations on live BEFORE deploying the code that needs them.
- This repo is **public**: never put real usernames, IP addresses, host names, the ntfy topic, healthchecks URLs or any secret
  in a file; never print `.env` values. `.env` is git-ignored; `.env.example` documents the settings.
- Prove claims with a before/after check on a database copy; report failures and surprises plainly; fix root causes.
- Commit locally with a clear message and a leak scan of the diff; ask before pushing.
- Run the tests before committing: `venv/bin/python -m unittest discover -s tests`.
