"""
Tests for scripts/run_report.py and scripts/notify.py. No real network and no
database: requests.post/get are replaced with fakes, and the "connection" is a
stand-in object. Run from the project root:

    venv/bin/python -m unittest discover -s tests -v
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

# Point logs at a throwaway folder BEFORE the scripts are imported
_tmp = tempfile.TemporaryDirectory()
os.environ["LOG_DIR"] = _tmp.name
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import logging  # noqa: E402

# No handler would make Python print every log line to the screen mid-test
logging.getLogger("sports_hub").addHandler(logging.NullHandler())

import notify  # noqa: E402
from run_report import RunReport  # noqa: E402

SECRET_TOPIC = "super-secret-topic-123"
SECRET_PING = "https://hc-ping.com/secret-uuid"


class FakeConn:
    def __init__(self):
        self.rollbacks = 0

    def rollback(self):
        self.rollbacks += 1


class RunReportTests(unittest.TestCase):
    def setUp(self):
        os.environ["NTFY_TOPIC"] = SECRET_TOPIC
        os.environ["HEALTHCHECK_URL"] = SECRET_PING
        self.post = mock.patch("notify.requests.post").start()
        self.get = mock.patch("notify.requests.get").start()
        self.addCleanup(mock.patch.stopall)

    def test_clean_run_exits_0_and_does_not_alert(self):
        report = RunReport("pipeline")
        with report.step("one"):
            pass
        report.count("games", 5)
        self.assertEqual(report.finish(), 0)
        self.post.assert_not_called()  # no phone alert when all is well
        urls = [c.args[0] for c in self.get.call_args_list]
        self.assertEqual(urls[0], SECRET_PING + "/start")
        self.assertEqual(urls[-1], SECRET_PING)  # success ping

    def test_failed_step_is_isolated_and_reported(self):
        conn = FakeConn()
        report = RunReport("pipeline", conn=conn)
        ran_after = []
        with report.step("breaks"):
            raise RuntimeError("boom")
        with report.step("still runs"):
            ran_after.append(True)
        self.assertEqual(ran_after, [True])  # one failure didn't stop the run
        self.assertEqual(conn.rollbacks, 1)  # connection reset for the next step
        self.assertEqual(report.finish(), 1)
        self.post.assert_called_once()
        self.assertIn("breaks: RuntimeError: boom", self.post.call_args.kwargs["data"].decode())
        self.assertEqual(self.get.call_args_list[-1].args[0], SECRET_PING + "/fail")

    def test_last_run_json_is_written(self):
        report = RunReport("t_json")
        with report.step("bad"):
            raise ValueError("nope")
        report.finish()
        data = json.loads((Path(_tmp.name) / "last_t_json.json").read_text())
        self.assertEqual(data["status"], "errors")
        self.assertEqual(data["errors"][0]["step"], "bad")

    def test_warning_alerts_but_exits_0(self):
        report = RunReport("t_warn")
        report.warn("Colts roster", "0 players returned (had 98)")
        self.assertEqual(report.finish(), 0)
        self.post.assert_called_once()

    def test_missing_settings_never_crash(self):
        del os.environ["NTFY_TOPIC"], os.environ["HEALTHCHECK_URL"]
        self.assertFalse(notify.send_alert("t", "m"))
        self.assertFalse(notify.ping_healthcheck("success"))
        report = RunReport("t_unset")
        with report.step("bad"):
            raise RuntimeError("x")
        self.assertEqual(report.finish(), 1)  # still returns the exit code

    def test_secrets_are_not_logged_when_sending_fails(self):
        import requests

        self.post.side_effect = requests.ConnectionError(f"failed for {SECRET_TOPIC}")
        with self.assertLogs("sports_hub.notify", level="WARNING") as logs:
            self.assertFalse(notify.send_alert("t", "m"))
        self.assertNotIn(SECRET_TOPIC, "\n".join(logs.output))

    def test_other_jobs_use_their_own_healthcheck_variable(self):
        os.environ["HEALTHCHECK_REFRESH_URL"] = "https://hc-ping.com/refresh-uuid"
        self.addCleanup(os.environ.pop, "HEALTHCHECK_REFRESH_URL", None)
        report = RunReport("refresh")
        report.finish()
        urls = [c.args[0] for c in self.get.call_args_list]
        self.assertTrue(all(u.startswith("https://hc-ping.com/refresh-uuid") for u in urls))
        self.assertNotIn(SECRET_PING, "".join(urls))  # never touches the pipeline check

    def test_job_without_its_own_url_sends_no_ping(self):
        report = RunReport("somejob")  # HEALTHCHECK_SOMEJOB_URL is not set
        report.finish()
        self.get.assert_not_called()


if __name__ == "__main__":
    unittest.main()
