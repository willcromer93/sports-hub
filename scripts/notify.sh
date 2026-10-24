#!/usr/bin/env bash
# Shared helpers for the bash scripts (backup_db.sh, restore_test.sh): a phone alert via
# ntfy and a "did it run?" ping to healthchecks.io. Load with:  . "$(dirname "$0")/notify.sh"
# The Python equivalent is scripts/notify.py. Settings come from .env (see .env.example).
#
# Both helpers never fail the calling script: if a setting is missing or the network is
# down they just return. Nothing here prints the ntfy topic or a ping URL.

# ntfy_alert TITLE MESSAGE [PRIORITY] [TAGS]
# Titles must be plain ASCII (HTTP headers). Messages say what failed, never data.
ntfy_alert() {
  if [ -z "${NTFY_TOPIC:-}" ]; then
    echo "NTFY_TOPIC is not set; alert not sent: $1" >&2
    return 0
  fi
  curl -fsS -m 10 -o /dev/null \
    -H "Title: $1" -H "Priority: ${3:-high}" -H "Tags: ${4:-warning}" \
    -d "$2" "${NTFY_URL:-https://ntfy.sh}/$NTFY_TOPIC" 2>/dev/null \
    || echo "could not send alert: $1" >&2
  return 0
}

# hc_ping URL [start|fail]    (no second argument = success). An empty URL is skipped.
hc_ping() {
  [ -n "${1:-}" ] || return 0
  curl -fsS -m 10 -o /dev/null "${1%/}${2:+/$2}" 2>/dev/null || true
  return 0
}
