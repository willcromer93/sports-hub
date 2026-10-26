"""
Tests for the per-game pulls in scripts/api_pulls.py: how a missing ESPN summary (404) is
handled, and that one bad game never blocks the others. The database and ESPN are mocked.
Run from the project root:

    venv/bin/python -m unittest discover -s tests -v
"""

import logging
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_tmp = tempfile.TemporaryDirectory()
os.environ.setdefault("LOG_DIR", _tmp.name)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
logging.getLogger("sports_hub").addHandler(logging.NullHandler())

import api_pulls  # noqa: E402
from http_client import FetchError  # noqa: E402
from run_report import RunReport  # noqa: E402


def fetch_error(status):
    error = FetchError(f"GET x failed (status {status})")
    error.status_code = status
    return error


class FetchGameSummaryTests(unittest.TestCase):
    def setUp(self):
        self.mark = mock.patch.object(api_pulls, "mark_summary_unavailable").start()
        self.clear = mock.patch.object(api_pulls, "clear_summary_unavailable").start()
        self.addCleanup(mock.patch.stopall)

    def test_a_summary_that_arrives_is_returned_and_clears_any_flag(self):
        with mock.patch.object(api_pulls, "fetch_summary", return_value={"ok": 1}):
            self.assertEqual(api_pulls.fetch_game_summary("conn", 7, "WNBA", "4018"), {"ok": 1})
        self.clear.assert_called_once_with("conn", 7)
        self.mark.assert_not_called()

    def test_a_404_that_survived_the_retries_flags_the_game_and_returns_none(self):
        with mock.patch.object(api_pulls, "fetch_summary", side_effect=fetch_error(404)):
            self.assertIsNone(api_pulls.fetch_game_summary("conn", 7, "WNBA", "4018"))
        self.mark.assert_called_once_with("conn", 7)
        self.clear.assert_not_called()

    def test_any_other_failure_is_not_a_gap_it_propagates_and_flags_nothing(self):
        for status in (500, 429, None):  # None = timeout or no reply at all
            with self.subTest(status=status):
                with mock.patch.object(api_pulls, "fetch_summary", side_effect=fetch_error(status)):
                    with self.assertRaises(FetchError):
                        api_pulls.fetch_game_summary("conn", 7, "NBA", "1")
        self.mark.assert_not_called()


class PerGameIsolationTests(unittest.TestCase):
    def setUp(self):
        for var in ("NTFY_TOPIC", "HEALTHCHECK_URL"):
            os.environ.pop(var, None)
        self.addCleanup(mock.patch.stopall)

    def test_one_bad_game_among_forty_is_one_warning_and_the_rest_are_filled(self):
        games = [(i, "NBA", str(i), 4) for i in range(40)]

        def summary(conn, game_id, league, external_id):
            if game_id == 7:
                raise fetch_error(500)
            return {"game": game_id}

        mock.patch.object(api_pulls, "get_games_missing_periods", return_value=games).start()
        mock.patch.object(api_pulls, "fetch_game_summary", side_effect=summary).start()
        mock.patch.object(api_pulls, "parse_periods", return_value=[(1, "regulation", 1, 0)]).start()
        insert = mock.patch.object(api_pulls, "insert_game_periods").start()

        report = RunReport("t_pull_periods")
        filled = api_pulls.pull_game_periods("conn", report)
        self.assertEqual(filled, 39)
        self.assertEqual(insert.call_count, 39)
        self.assertEqual(report.errors, [])
        self.assertEqual(len(report.warnings), 1)
        self.assertIn("NBA 7", report.warnings[0][1])

    def test_a_game_with_no_summary_is_skipped_quietly(self):
        mock.patch.object(api_pulls, "get_games_missing_periods", return_value=[(1, "WNBA", "9", 4)]).start()
        mock.patch.object(api_pulls, "fetch_game_summary", return_value=None).start()
        insert = mock.patch.object(api_pulls, "insert_game_periods").start()
        report = RunReport("t_pull_gap")
        self.assertEqual(api_pulls.pull_game_periods("conn", report), 0)
        insert.assert_not_called()
        self.assertEqual((report.errors, report.warnings), ([], []))

    def test_both_sides_of_a_game_share_one_request(self):
        # (game_id, league, external_id, team_id, espn_id): two sides of game 5, one of game 6
        sides = [(5, "NBA", "50", 1, "11"), (5, "NBA", "50", 2, "12"), (6, "NBA", "60", 3, "13")]
        mock.patch.object(api_pulls, "get_games_missing_box_scores", return_value=sides).start()
        fetch = mock.patch.object(api_pulls, "fetch_game_summary", return_value={"s": 1}).start()
        mock.patch.object(api_pulls, "parse_team_box_score", return_value={"p": 1}).start()
        mock.patch.object(api_pulls, "box_score_rows", return_value=[]).start()
        insert = mock.patch.object(api_pulls, "insert_box_score").start()

        report = RunReport("t_pull_box")
        filled = api_pulls.pull_box_scores("conn", report)
        self.assertEqual(filled, 3)  # three sides
        self.assertEqual(fetch.call_count, 2)  # but only two requests (one per game)
        self.assertEqual(insert.call_count, 3)

    def test_a_failing_game_does_not_stop_the_other_games_box_scores(self):
        sides = [(i, "NBA", str(i), i, "1") for i in range(40)]
        mock.patch.object(api_pulls, "get_games_missing_box_scores", return_value=sides).start()

        def summary(conn, game_id, league, external_id):
            if game_id == 3:
                raise fetch_error(503)
            return {"s": 1}

        mock.patch.object(api_pulls, "fetch_game_summary", side_effect=summary).start()
        mock.patch.object(api_pulls, "parse_team_box_score", return_value={"p": 1}).start()
        mock.patch.object(api_pulls, "box_score_rows", return_value=[]).start()
        mock.patch.object(api_pulls, "insert_box_score").start()
        report = RunReport("t_pull_box2")
        self.assertEqual(api_pulls.pull_box_scores("conn", report), 39)
        self.assertEqual(report.errors, [])
        self.assertEqual(len(report.warnings), 1)


if __name__ == "__main__":
    unittest.main()
