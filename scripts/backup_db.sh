#!/usr/bin/env bash
# Nightly database backup: writes a compressed pg_dump into BACKUP_DIR and prunes old ones.
# Settings (all optional) come from .env: BACKUP_DIR, BACKUP_KEEP_DAYS. See .env.example.
# Stops at the first error (set -e), so a failure never leaves a "good-looking" bad backup.
set -euo pipefail
umask 077   # every file/folder created below is readable by this user only

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
set -a; . "$PROJECT_DIR/.env"; set +a
export PGPASSWORD="$DB_PASSWORD"

BACKUP_DIR="${BACKUP_DIR:-$HOME/backups}"
KEEP_DAYS="${BACKUP_KEEP_DAYS:-30}"

mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"

STAMP="$(date +%Y-%m-%d_%H%M)"
PARTIAL="$BACKUP_DIR/.sports_hub_$STAMP.dump.partial"
FINAL="$BACKUP_DIR/sports_hub_$STAMP.dump"

# 1. Dump to a hidden .partial file (-Fc = compressed custom format, restorable with pg_restore).
pg_dump -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -Fc -f "$PARTIAL"

# 2. Prove the archive is readable (lists its contents; fails if it is truncated or corrupt).
pg_restore -l "$PARTIAL" > /dev/null

# 3. Only now give it its real name. A rename is instant, so a half-written file can't pass as a backup.
mv "$PARTIAL" "$FINAL"

# 4. Delete dumps older than KEEP_DAYS. The name pattern means nothing else can be touched.
find "$BACKUP_DIR" -maxdepth 1 -name 'sports_hub_*.dump' -mtime +"$KEEP_DAYS" -delete

echo "$(date -Is) backup ok: $FINAL ($(du -h "$FINAL" | cut -f1))"
