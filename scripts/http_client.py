"""
One place for every outbound API call.

Why this exists: a bare requests.get() has no timeout (a stalled API can hang
the script forever), treats an HTTP error page as if it were data, and gives up
on the first hiccup. fetch_json() fixes all three:

  - timeouts: 5 s to connect, 30 s to wait for a reply
  - retries: up to 3 more tries, waiting 1 s, 2 s, 4 s between them, but only
    for problems that are usually temporary (timeouts, dropped connections,
    HTTP 429 "slow down", 5xx server errors, and 404: ESPN has been seen
    answering 404 for a valid URL that works seconds later, so one 404 proves
    nothing; a page that is really missing just costs a few extra seconds)
  - clear errors: after the last try it raises FetchError naming the URL (and
    carrying the HTTP status code, if there was one) instead of a confusing
    KeyError three lines later
  - a short pause between calls, to be polite to free public APIs
"""

import time

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

CONNECT_TIMEOUT = 5  # seconds to establish the connection
READ_TIMEOUT = 30  # seconds to wait for the response
RETRIES = 3  # extra attempts after the first one
BACKOFF = 1.0  # wait BACKOFF * 2**(n-1) seconds before retry n: 1, 2, 4
PAUSE_BETWEEN_CALLS = 0.2  # minimum gap between two calls

RETRY_STATUSES = (404, 429, 500, 502, 503, 504)


class FetchError(Exception):
    """An API call still failed after retries (or returned something unusable).
    status_code is the HTTP status of the last reply (e.g. 404), or None if there
    was no reply at all (timeout, dropped connection) or it wasn't valid JSON."""

    status_code = None


_session = None
_last_call = 0.0


def _get_session():
    """One shared Session: it reuses connections, which is faster than reconnecting
    for every call. Built on first use so tests can change the settings above."""
    global _session
    if _session is None:
        retry = Retry(
            total=RETRIES,
            backoff_factor=BACKOFF,
            status_forcelist=RETRY_STATUSES,
            allowed_methods=("GET",),
            respect_retry_after_header=True,  # obey the API's own "try again in N s"
            raise_on_status=False,  # let fetch_json() raise one clear error itself
        )
        session = requests.Session()
        session.mount("https://", HTTPAdapter(max_retries=retry))
        session.mount("http://", HTTPAdapter(max_retries=retry))
        _session = session
    return _session


def fetch_json(url, params=None, headers=None):
    """GET a URL and return its parsed JSON. Raises FetchError on any failure."""
    global _last_call
    wait = PAUSE_BETWEEN_CALLS - (time.monotonic() - _last_call)
    if wait > 0:
        time.sleep(wait)
    try:
        response = _get_session().get(
            url,
            params=params,
            headers=headers,
            timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
        )
        _last_call = time.monotonic()
        response.raise_for_status()  # turns HTTP 4xx/5xx into an exception
        return response.json()
    except (requests.RequestException, ValueError) as exc:
        # RequestException covers timeouts, connection errors and HTTP errors;
        # ValueError covers a reply that isn't valid JSON.
        error = FetchError(f"GET {url} failed: {exc}")
        error.status_code = getattr(getattr(exc, "response", None), "status_code", None)
        raise error from exc
