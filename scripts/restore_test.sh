#!/usr/bin/env bash
# Restore test: loads the newest backup into a SCRATCH database and compares row counts
# with the live one. Never touches the live database. A backup you have never restored
# is only a hope; run this weekly.
#
# One-time setup (needs sudo): create the empty scratch database owned by the app role.
# See the README ("Backups") for the exact command.
# Settings (optional) come from .env: BACKUP_DIR, RESTORE_TEST_DB. See .env.example.
set -Eeuo pipefail   # -E makes the ERR trap below also fire inside functions
umask 077

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
set -a; . "$PROJECT_DIR/.env"; set +a
export PGPASSWORD="$DB_PASSWORD"
. "$PROJECT_DIR/scripts/notify.sh"

# fail MESSAGE: print it, alert your phone, tell healthchecks.io, and stop.
fail() {
  echo "FAIL: $1"
  ntfy_alert "Sports Hub restore test FAILED" "$1"
  hc_ping "${HEALTHCHECK_RESTORE_URL:-}" fail
  exit 1
}
# Unexpected errors (a missing table, pg_restore refusing a corrupt file) end up here too.
trap 'fail "restore_test.sh stopped unexpectedly at line $LINENO. See logs/restore_test.log"' ERR
hc_ping "${HEALTHCHECK_RESTORE_URL:-}" start

BACKUP_DIR="${BACKUP_DIR:-$HOME/backups}"
SCRATCH_DB="${RESTORE_TEST_DB:-sports_hub_restore_test}"

# Safety: refuse to run if the scratch name is the live database.
if [ "$SCRATCH_DB" = "$DB_NAME" ]; then
  fail "RESTORE_TEST_DB must not be the live database ($DB_NAME)"
fi

# -A -t = plain unaligned output with no headers, so results are easy to compare.
PSQL="psql -h $DB_HOST -p $DB_PORT -U $DB_USER -X -A -t -v ON_ERROR_STOP=1"

# Newest backup (sed -n 1p, not head, so the pipe can't trip pipefail).
LATEST="$(ls -1t "$BACKUP_DIR"/sports_hub_*.dump 2>/dev/null | sed -n 1p || true)"
if [ -z "$LATEST" ]; then fail "no backups found in $BACKUP_DIR"; fi
echo "Restoring $LATEST into $SCRATCH_DB"

# --clean --if-exists empties the scratch DB first, so this can be re-run safely.
# --no-owner --no-acl skip ownership/permission entries (a non-superuser can't restore those).
pg_restore -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$SCRATCH_DB" \
  --clean --if-exists --no-owner --no-acl "$LATEST"

# Compare every live table with its restored copy. The backup runs before the 4 AM pipeline,
# so restored counts can be a bit lower than live; that's fine. Empty restores are not.
for t in $($PSQL -d "$DB_NAME" -c "select tablename from pg_tables where schemaname='public' order by 1"); do
  live="$($PSQL -d "$DB_NAME" -c "select count(*) from $t")"
  copy="$($PSQL -d "$SCRATCH_DB" -c "select count(*) from $t")"   # fails the script if the table is missing
  printf '%-26s live=%-8s restored=%s\n' "$t" "$live" "$copy"
  if [ "$copy" -eq 0 ] && [ "$live" -gt 0 ]; then
    fail "$t restored empty but live has $live rows"
  fi
done

echo "$(date -Is) restore test ok"
hc_ping "${HEALTHCHECK_RESTORE_URL:-}"
