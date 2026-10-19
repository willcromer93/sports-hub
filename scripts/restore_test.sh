#!/usr/bin/env bash
# Restore test: loads the newest backup into a SCRATCH database and compares row counts
# with the live one. Never touches the live database. A backup you have never restored
# is only a hope; run this weekly.
#
# One-time setup (needs sudo): create the empty scratch database owned by the app role.
# See the README ("Backups") for the exact command.
# Settings (optional) come from .env: BACKUP_DIR, RESTORE_TEST_DB. See .env.example.
set -euo pipefail
umask 077

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
set -a; . "$PROJECT_DIR/.env"; set +a
export PGPASSWORD="$DB_PASSWORD"

BACKUP_DIR="${BACKUP_DIR:-$HOME/backups}"
SCRATCH_DB="${RESTORE_TEST_DB:-sports_hub_restore_test}"

# Safety: refuse to run if the scratch name is the live database.
if [ "$SCRATCH_DB" = "$DB_NAME" ]; then
  echo "FAIL: RESTORE_TEST_DB must not be the live database ($DB_NAME)"; exit 1
fi

# -A -t = plain unaligned output with no headers, so results are easy to compare.
PSQL="psql -h $DB_HOST -p $DB_PORT -U $DB_USER -X -A -t -v ON_ERROR_STOP=1"

# Newest backup (sed -n 1p, not head, so the pipe can't trip pipefail).
LATEST="$(ls -1t "$BACKUP_DIR"/sports_hub_*.dump 2>/dev/null | sed -n 1p || true)"
if [ -z "$LATEST" ]; then echo "FAIL: no backups found in $BACKUP_DIR"; exit 1; fi
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
    echo "FAIL: $t restored empty but live has $live rows"; exit 1
  fi
done

echo "$(date -Is) restore test ok"
