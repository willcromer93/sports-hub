"""
RunReport: keeps one failing step from killing the whole run, and tells you
about it.

Usage:

    report = RunReport("pipeline", conn=conn)
    with report.step("Colts roster"):
        ...pull and insert...            # if this raises, it is logged and skipped
    with report.step("Rollups"):
        ...                              # ...and this still runs
    report.count("games", 224)
    sys.exit(report.finish())            # 0 if clean, 1 if any step failed

finish() writes one summary line to the log, saves logs/last_<name>.json (the
machine-readable result of the latest run), sends a phone alert if anything went
wrong, and pings healthchecks.io so a run that never happens is noticed too.
"""

import json
import logging
import os
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from log_setup import LOG_DIR
from notify import ping_healthcheck, send_alert

log = logging.getLogger("sports_hub.run_report")

MAX_ALERT_LINES = 5  # keep the phone message short


class RunReport:
    def __init__(self, name, conn=None):
        self.name = name
        self.conn = conn  # if given, rolled back after a failed step (see step())
        self.started = datetime.now()
        self.ok_steps = []
        self.errors = []  # [(step label, "ErrorType: message")]
        self.warnings = []  # [(step label, message)]: suspicious, but not a crash
        self.counts = {}
        self.extra = {}  # anything else worth saving in last_<job>.json (e.g. table counts)
        # Each job pings its own healthchecks.io check: the nightly pipeline uses
        # HEALTHCHECK_URL, others HEALTHCHECK_<NAME>_URL (unset = no ping).
        self.healthcheck_var = (
            "HEALTHCHECK_URL" if name == "pipeline" else f"HEALTHCHECK_{name.upper()}_URL"
        )
        ping_healthcheck("start", self.healthcheck_var)

    @contextmanager
    def step(self, label):
        """Run a block of work; on any error, log the traceback, record it, and
        carry on. (KeyboardInterrupt, i.e. Ctrl+C, is deliberately not caught.)"""
        log.info("START %s", label)
        try:
            yield
        except Exception as exc:
            log.exception("FAILED %s", label)
            self.errors.append((label, f"{type(exc).__name__}: {exc}"))
            if self.conn is not None:
                # A database error leaves the connection "aborted" until rolled
                # back; without this, every later step would fail too.
                try:
                    self.conn.rollback()
                except Exception:
                    log.exception("Rollback failed after %s", label)
        else:
            self.ok_steps.append(label)

    def count(self, key, value):
        """Record a number for the summary, e.g. count("games", 224)."""
        self.counts[key] = value

    def warn(self, label, message):
        """Record something suspicious that did not raise, e.g. a roster that
        came back empty when it normally has players."""
        log.warning("%s: %s", label, message)
        self.warnings.append((label, message))

    def finish(self):
        """Log the summary, save last_<name>.json, alert, and return the exit code."""
        finished = datetime.now()
        seconds = round((finished - self.started).total_seconds())
        failed = bool(self.errors)
        status = "errors" if failed else ("warnings" if self.warnings else "ok")

        log.info(
            "SUMMARY %s: %s in %ds | %d steps ok, %d failed, %d warnings | %s",
            self.name,
            status.upper(),
            seconds,
            len(self.ok_steps),
            len(self.errors),
            len(self.warnings),
            ", ".join(f"{k}={v}" for k, v in self.counts.items()) or "no counts",
        )
        self._write_json(status, finished, seconds)

        if failed or self.warnings:
            self._alert(failed)
        ping_healthcheck("fail" if failed else "success", self.healthcheck_var)
        return 1 if failed else 0

    def _alert(self, failed):
        lines = [f"{label}: {msg}" for label, msg in self.errors]
        lines += [f"{label}: {msg}" for label, msg in self.warnings]
        shown = lines[:MAX_ALERT_LINES]
        if len(lines) > MAX_ALERT_LINES:
            shown.append(f"...and {len(lines) - MAX_ALERT_LINES} more (see the log)")
        what = f"{len(self.errors)} step(s) failed" if failed else "warnings"
        send_alert(
            title=f"Sports Hub {self.name}: {what}",
            message="\n".join(shown)[:900],
            priority="high" if failed else "default",
            tags="rotating_light" if failed else "warning",
        )

    def _write_json(self, status, finished, seconds):
        """Save the result atomically (write a temp file, then rename), so a
        reader never sees a half-written file."""
        result = {
            "name": self.name,
            "status": status,
            "started": self.started.isoformat(timespec="seconds"),
            "finished": finished.isoformat(timespec="seconds"),
            "duration_seconds": seconds,
            "counts": self.counts,
            "ok_steps": len(self.ok_steps),
            "errors": [{"step": s, "error": e} for s, e in self.errors],
            "warnings": [{"step": s, "message": m} for s, m in self.warnings],
            **self.extra,
        }
        try:
            Path(LOG_DIR).mkdir(parents=True, exist_ok=True)
            path = Path(LOG_DIR) / f"last_{self.name}.json"
            tmp = path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(result, indent=2))
            os.replace(tmp, path)
        except OSError:
            log.exception("Could not write last_%s.json", self.name)
