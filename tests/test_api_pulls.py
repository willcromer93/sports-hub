"""
Tests for the per-game summary step in scripts/api_pulls.py: how a missing ESPN summary (404) is
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


def game(game_id, needs_periods=True, sides=((1, "11", True), (2, "12", True)), backfill=False):
    """A get_games_needing_summary row."""
    return (game_id, "NBA", str(game_id), 4, needs_periods, list(sides), backfill)


class SummaryStepTests(unittest.TestCase):
    """pull_game_summaries / process_game_summary with the database and ESPN mocked."""

    def setUp(self):
        for var in ("NTFY_TOPIC", "HEALTHCHECK_URL"):
            os.environ.pop(var, None)
        self.addCleanup(mock.patch.stopall)
        self.fetch = mock.patch.object(api_pulls, "fetch_game_summary", return_value={"s": 1}).start()
        mock.patch.object(api_pulls, "parse_periods", return_value=[(1, "regulation", 1, 0)]).start()
        mock.patch.object(api_pulls, "parse_team_box_score", return_value={"p": 1}).start()
        mock.patch.object(api_pulls, "box_score_rows", return_value=[]).start()
        mock.patch.object(api_pulls, "parse_game_info", return_value=(1000, [("A", "Referee", 0)])).start()
        mock.patch.object(api_pulls, "trim_summary_for_cache", return_value={"t": 1}).start()
        self.periods = mock.patch.object(api_pulls, "insert_game_periods").start()
        self.box = mock.patch.object(api_pulls, "insert_box_score").start()
        self.info = mock.patch.object(api_pulls, "save_game_info").start()
        self.cache = mock.patch.object(api_pulls, "cache_summary").start()
        self.parsed = mock.patch.object(api_pulls, "mark_summary_parsed").start()
        self.prune = mock.patch.object(api_pulls, "prune_summary_cache").start()

    def run_step(self, games):
        mock.patch.object(api_pulls, "get_games_needing_summary", return_value=games).start()
        report = RunReport("t_summaries")
        return api_pulls.pull_game_summaries("conn", report), report

    def test_one_request_fills_periods_both_sides_details_and_the_cache(self):
        (counts, report) = self.run_step([game(5)])
        self.assertEqual(counts, (1, 2, 0))
        self.assertEqual(self.fetch.call_count, 1)  # the whole point: one fetch per game
        self.periods.assert_called_once()
        self.assertEqual(self.box.call_count, 2)
        self.info.assert_called_once_with("conn", 5, 1000, [("A", "Referee", 0)])
        self.cache.assert_called_once_with("conn", 5, {"t": 1})
        self.parsed.assert_called_once_with("conn", 5, api_pulls.SUMMARY_PARSER_VERSION)
        self.prune.assert_called_once()
        self.assertEqual((report.errors, report.warnings), ([], []))

    def test_only_what_is_missing_is_written(self):
        sides = [(1, "11", False), (2, "12", True)]  # home side already stored
        (counts, _) = self.run_step([game(5, needs_periods=False, sides=sides)])
        self.assertEqual(counts, (0, 1, 0))
        self.periods.assert_not_called()
        self.assertEqual(self.box.call_count, 1)

    def test_a_backfill_game_rewrites_stored_sides_but_counts_no_new_ones(self):
        sides = [(1, "11", False), (2, "12", False)]
        (counts, _) = self.run_step([game(5, needs_periods=False, sides=sides, backfill=True)])
        self.assertEqual(counts, (0, 0, 1))
        self.assertEqual(self.box.call_count, 2)  # rewritten with the new fields
        self.parsed.assert_called_once()

    def test_one_bad_game_among_forty_is_one_warning_and_the_rest_are_filled(self):
        def summary(conn, game_id, league, external_id):
            if game_id == 7:
                raise fetch_error(500)
            return {"s": 1}

        self.fetch.side_effect = summary
        (counts, report) = self.run_step([game(i) for i in range(40)])
        self.assertEqual(counts, (39, 78, 0))
        self.assertEqual(report.errors, [])
        self.assertEqual(len(report.warnings), 1)
        self.assertIn("NBA 7", report.warnings[0][1])
        self.assertEqual(self.parsed.call_count, 39)  # the failed game is retried tomorrow

    def test_a_game_with_no_summary_is_skipped_quietly(self):
        self.fetch.return_value = None
        (counts, report) = self.run_step([game(1)])
        self.assertEqual(counts, (0, 0, 0))
        for mocked in (self.periods, self.box, self.info, self.cache, self.parsed):
            mocked.assert_not_called()
        self.assertEqual((report.errors, report.warnings), ([], []))

    def test_unusable_period_scores_do_not_stop_the_box_score(self):
        mock.patch.object(api_pulls, "parse_periods", return_value=None).start()
        (counts, _) = self.run_step([game(1)])
        self.assertEqual(counts, (0, 2, 0))
        self.periods.assert_not_called()

    def test_a_side_without_a_box_score_is_skipped_with_a_log_warning(self):
        mock.patch.object(api_pulls, "parse_team_box_score", return_value={}).start()
        (counts, _) = self.run_step([game(1)])
        self.assertEqual(counts, (1, 0, 0))
        self.box.assert_not_called()


if __name__ == "__main__":
    unittest.main()
