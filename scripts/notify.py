"""
Outbound notifications: phone alerts (ntfy) and the "did it run?" check
(healthchecks.io).

Both are configured in .env and both are optional. If a setting is missing the
function logs a warning and returns False, so alerting can never crash the
pipeline it is watching.

  NTFY_TOPIC        the ntfy.sh topic your phone subscribes to. Anyone who knows
                    it can read or send messages, so make it long and random.
  NTFY_URL          (optional) default https://ntfy.sh
  HEALTHCHECK_URL   the ping URL from healthchecks.io for the nightly pipeline
                    (other jobs use HEALTHCHECK_<NAME>_URL, e.g. HEALTHCHECK_REFRESH_URL)

Never put data in a message, only what failed. And never log the topic or the
ping URL: exceptions from `requests` include the URL, so only the exception's
type name is logged here.
"""

import logging
import os

import requests

log = logging.getLogger("sports_hub.notify")

TIMEOUT = 10  # seconds


def send_alert(title, message, priority="high", tags="warning"):
    """Send a push notification via ntfy. Returns True if it was sent."""
    topic = os.getenv("NTFY_TOPIC")
    if not topic:
        log.warning("NTFY_TOPIC is not set; alert not sent: %s", title)
        return False
    base_url = os.getenv("NTFY_URL", "https://ntfy.sh").rstrip("/")
    try:
        response = requests.post(
            f"{base_url}/{topic}",
            data=message.encode("utf-8"),
            # HTTP headers must be plain ASCII, so keep titles simple
            headers={
                "Title": title.encode("ascii", "replace").decode(),
                "Priority": priority,
                "Tags": tags,
            },
            timeout=TIMEOUT,
        )
        response.raise_for_status()
        return True
    except requests.RequestException as exc:
        log.warning("Could not send alert (%s)", type(exc).__name__)
        return False


def ping_healthcheck(status="success", env_var="HEALTHCHECK_URL"):
    """Tell healthchecks.io how a run went: "start", "success" or "fail".
    A missing "success" ping is what makes healthchecks.io alert you.
    env_var names the .env setting that holds this job's ping URL, so each job
    (nightly pipeline, weekly refresh, backup) can have its own check."""
    url = os.getenv(env_var)
    if not url:
        log.info("%s is not set; skipping the %s ping", env_var, status)
        return False
    suffix = {"success": "", "start": "/start", "fail": "/fail"}[status]
    try:
        response = requests.get(url.rstrip("/") + suffix, timeout=TIMEOUT)
        response.raise_for_status()
        return True
    except requests.RequestException as exc:
        log.warning("Healthcheck %s ping failed (%s)", status, type(exc).__name__)
        return False
