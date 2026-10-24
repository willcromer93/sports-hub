"""
Tests for scripts/sanity_checks.py using a fake database connection that returns
canned rows, so they need no real database. Run from the project root:

    venv/bin/python -m unittest discover -s tests -v
"""

import json
import logging
import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

_tmp = tempfile.TemporaryDirectory()
os.environ.setdefault("LOG_DIR", _tmp.name)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

logging.getLogger("sports_hub").addHandler(logging.NullHandler())

import sanity_checks as sc  # noqa: E402
from run_report import RunReport  # noqa: E402


class FakeCursor:
    def __init__(self, answers):
        self.answers, self.rows = answers, []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        flat = " ".join(sql.split())
        for needle, rows in self.answers:  # first matching needle wins
            if needle in flat:
                self.rows = rows
                return
        raise AssertionError(f"FakeCursor has no answer for: {flat[:100]}")

    def fetchall(self):
        return self.rows


class FakeConn:
    """Answers each query with canned rows, picked by a snippet of the SQL."""

    def __init__(self, answers):
        self.answers = answers
        self.rollbacks = 0

    def cursor(self):
        return FakeCursor(self.answers)

    def rollback(self):
        self.rollbacks += 1


# A healthy database: every check passes
HEALTHY = [
    ("HAVING count(*) > 1", []),
    ("GROUP BY league;", [("NBA", 1), ("NCAAB", 1), ("NHL", 1), ("NFL", 1)]),
    ("WHERE is_featured", [("NBA", "11"), ("NCAAB", "2509"), ("NHL", "5"), ("NFL", "11")]),
    ("WHERE NOT EXISTS ( SELECT 1 FROM teams t", []),
    ("home_score IS NULL OR away_score IS NULL", []),
    ("FROM game_periods GROUP BY game_id", []),
    ("AND EXISTS (SELECT 1 FROM game_periods", []),
    ("FROM player_game_appearances a", []),
    ("max(last_updated)", [(False,)]),
    ("SELECT count(*) FROM", [(10,)]),
]


EXPECTED = {"NBA": 1, "NCAAB": 1, "NHL": 1, "NFL": 1}  # tracked teams per league
FEATURED = {("NBA", "11"), ("NCAAB", "2509"), ("NHL", "5"), ("NFL", "11")}


def answers_with(**overrides):
    """HEALTHY, with some answers replaced: answers_with(**{'needle': rows})."""
    changed = [(n, overrides.pop(n)) if n in overrides else (n, r) for n, r in HEALTHY]
    assert not overrides, f"unknown needle(s): {list(overrides)}"
    return changed


class IndividualCheckTests(unittest.TestCase):
    def test_tracked_team_count_must_match_per_league(self):
        conn = FakeConn(answers_with(**{"GROUP BY league;": [("NBA", 31), ("NCAAB", 1), ("NHL", 1), ("NFL", 1)]}))
        problems = sc.check_tracked_teams(conn, EXPECTED)
        self.assertEqual(problems, ["NBA: 31 tracked teams, expected 1"])

    def test_a_league_we_did_not_expect_a_count_for_is_skipped(self):
        # e.g. the NBA team list could not be fetched tonight
        conn = FakeConn(answers_with(**{"GROUP BY league;": [("NBA", 1)]}))
        self.assertEqual(sc.check_tracked_teams(conn, {"NBA": 1}), [])

    def test_a_league_with_no_tracked_teams_at_all_is_a_problem(self):
        conn = FakeConn(answers_with(**{"GROUP BY league;": []}))
        self.assertEqual(sc.check_tracked_teams(conn, {"NBA": 30}), ["NBA: 0 tracked teams, expected 30"])

    def test_featured_flags_must_match_the_config(self):
        conn = FakeConn(HEALTHY)
        self.assertEqual(sc.check_featured_teams(conn, FEATURED), [])
        extra = FakeConn(answers_with(**{"WHERE is_featured": [("NBA", "11"), ("NBA", "7")]}))
        problems = sc.check_featured_teams(extra, {("NBA", "11")})
        self.assertEqual(len(problems), 1)
        self.assertIn("NBA 7", problems[0])
        missing = sc.check_featured_teams(FakeConn(HEALTHY), FEATURED | {("MLB", "1")})
        self.assertIn("MLB 1", missing[0])

    def test_duplicate_tracked_team_is_named(self):
        conn = FakeConn(answers_with(**{"HAVING count(*) > 1": [("NFL", "Indianapolis Colts")]}))
        problems = sc.check_tracked_teams(conn, EXPECTED)
        self.assertIn("NFL Indianapolis Colts", problems[0])

    def test_healthy_data_passes_every_check(self):
        conn = FakeConn(HEALTHY)
        self.assertEqual(sc.check_tracked_teams(conn, EXPECTED), [])
        self.assertEqual(sc.check_games_have_tracked_team(conn), [])
        self.assertEqual(sc.check_final_games_have_scores(conn), [])
        self.assertEqual(sc.check_period_sums(conn), [])
        self.assertEqual(sc.check_box_scores_present(conn), [])
        self.assertEqual(sc.check_games_fresh(conn, datetime.now().astimezone()), [])

    def test_examples_are_capped(self):
        rows = [("NHL", str(i)) for i in range(10)]
        conn = FakeConn(answers_with(**{"FROM player_game_appearances a": rows}))
        problem = sc.check_box_scores_present(conn)[0]
        self.assertIn("10 final game(s)", problem)
        self.assertEqual(problem.count("NHL "), sc.MAX_EXAMPLES)

    def test_stale_games_are_flagged(self):
        conn = FakeConn(answers_with(**{"max(last_updated)": [(True,)]}))
        self.assertEqual(len(sc.check_games_fresh(conn, datetime.now().astimezone())), 1)


class AcknowledgedMismatchTests(unittest.TestCase):
    def test_acknowledged_game_is_not_reported(self):
        key = next(iter(sc.ACKNOWLEDGED_PERIOD_MISMATCHES))
        conn = FakeConn(answers_with(**{"FROM game_periods GROUP BY game_id": [key + (True,)]}))
        self.assertEqual(sc.check_period_sums(conn), [])

    def test_a_new_mismatch_is_reported_alongside_an_acknowledged_one(self):
        key = next(iter(sc.ACKNOWLEDGED_PERIOD_MISMATCHES))
        conn = FakeConn(answers_with(**{"FROM game_periods GROUP BY game_id": [key + (True,), ("NFL", "999", True)]}))
        problems = sc.check_period_sums(conn)
        self.assertEqual(len(problems), 1)
        self.assertIn("NFL 999", problems[0])
        self.assertNotIn(key[1], problems[0])

    def test_resolved_acknowledgment_prompts_cleanup(self):
        conn = FakeConn(HEALTHY)  # ESPN fixed it: the game no longer mismatches
        with self.assertLogs("sports_hub.sanity", level="INFO") as logs:
            self.assertEqual(sc.check_period_sums(conn), [])
        self.assertIn("no longer occurs", "\n".join(logs.output))


class PeriodMismatchJudgementTests(unittest.TestCase):
    """A mismatch is judged by how NEW and how COMMON it is (ESPN is occasionally wrong)."""

    def check(self, rows, totals):
        conn = FakeConn(answers_with(**{
            "FROM game_periods GROUP BY game_id": rows,
            "AND EXISTS (SELECT 1 FROM game_periods": totals,
        }))
        return sc.check_period_sums(conn)

    def test_a_new_mismatch_is_reported(self):
        problems = self.check([("NHL", "111", True)], [("NHL", 500)])
        self.assertEqual(len(problems), 1)
        self.assertIn("last 3 days", problems[0])
        self.assertIn("NHL 111", problems[0])

    def test_an_old_isolated_mismatch_stays_quiet(self):
        # Reviewed long ago and not new: no nightly alert, however long it stays
        self.assertEqual(self.check([("NHL", "111", False)], [("NHL", 500)]), [])

    def test_a_high_rate_in_one_league_is_reported_even_if_every_game_is_old(self):
        old = [("NHL", str(i), False) for i in range(11)]  # 11 of 500 = 2.2%
        problems = self.check(old, [("NHL", 500)])
        self.assertEqual(len(problems), 1)
        self.assertIn("NHL: 11 of 500", problems[0])
        self.assertIn("ESPN quirk", problems[0])

    def test_the_rate_boundary(self):
        at_limit = [("NHL", str(i), False) for i in range(10)]  # 10 of 500 = exactly 2%
        self.assertEqual(self.check(at_limit, [("NHL", 500)]), [])
        over = [("NHL", str(i), False) for i in range(11)]
        self.assertEqual(len(self.check(over, [("NHL", 500)])), 1)

    def test_a_small_league_sample_is_not_judged_by_rate(self):
        # 3 of 40 is 7.5%, but 40 games is too few to call it systemic
        few = [("NHL", str(i), False) for i in range(3)]
        self.assertEqual(self.check(few, [("NHL", 40)]), [])

    def test_acknowledged_games_do_not_count_toward_the_rate(self):
        ack = [key + (False,) for key in sc.ACKNOWLEDGED_PERIOD_MISMATCHES if key[0] == "NHL"]
        self.assertEqual(self.check(ack, [("NHL", len(ack) + 1)]), [])


class RowCountTests(unittest.TestCase):
    def test_shrinking_table_is_flagged(self):
        problems = sc.check_row_counts({"games": 90, "teams": 5}, {"games": 100, "teams": 5})
        self.assertEqual(problems, ["games shrank from 100 to 90 rows"])

    def test_growth_and_equal_are_fine(self):
        self.assertEqual(sc.check_row_counts({"games": 101, "teams": 5}, {"games": 100, "teams": 5}), [])

    def test_no_previous_counts_means_nothing_to_compare(self):
        self.assertEqual(sc.check_row_counts({"games": 1}, None), [])

    def test_loading_previous_counts(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(sc.load_previous_counts("job", d))  # no file yet
            (Path(d) / "last_job.json").write_text("not json")
            self.assertIsNone(sc.load_previous_counts("job", d))  # garbage
            (Path(d) / "last_job.json").write_text(json.dumps({"table_counts": {"games": 7}}))
            self.assertEqual(sc.load_previous_counts("job", d), {"games": 7})


class RunSanityChecksTests(unittest.TestCase):
    def setUp(self):
        for var in ("NTFY_TOPIC", "HEALTHCHECK_URL"):
            os.environ.pop(var, None)

    def test_clean_run_has_no_warnings_and_saves_counts(self):
        report = RunReport("t_sane_clean")
        sc.run_sanity_checks(FakeConn(HEALTHY), report, EXPECTED, FEATURED)
        self.assertEqual((report.errors, report.warnings), ([], []))
        self.assertEqual(report.extra["table_counts"]["games"], 10)
        self.assertEqual(report.counts["sanity problems"], 0)

    def test_each_failed_check_becomes_one_warning(self):
        answers = answers_with(**{
            "FROM game_periods GROUP BY game_id": [("NFL", "111", True)],
            "max(last_updated)": [(True,)],
        })
        report = RunReport("t_sane_bad")
        sc.run_sanity_checks(FakeConn(answers), report, EXPECTED, FEATURED)
        self.assertEqual(report.errors, [])  # warnings never fail the run
        self.assertEqual(
            sorted(label for label, _ in report.warnings),
            ["Sanity: games fresh", "Sanity: periods add up to scores"],
        )
        self.assertEqual(report.counts["sanity problems"], 2)

    def test_a_check_that_itself_breaks_is_an_error_not_silence(self):
        answers = [a for a in HEALTHY if a[0] != "max(last_updated)"]  # no answer: raises
        report = RunReport("t_sane_broken")
        sc.run_sanity_checks(FakeConn(answers), report, EXPECTED, FEATURED)
        self.assertEqual([label for label, _ in report.errors], ["Sanity check: games fresh"])

    def test_row_count_shrink_is_warned_using_the_previous_run(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "last_t_sane_shrink.json").write_text(
                json.dumps({"table_counts": {"games": 50}})
            )
            report = RunReport("t_sane_shrink")
            with mock.patch.object(sc, "LOG_DIR", d):
                sc.run_sanity_checks(FakeConn(HEALTHY), report, EXPECTED, FEATURED)
        # Yesterday's games count was 50 and today's database says 10: that's a shrink
        self.assertEqual([label for label, _ in report.warnings], ["Sanity: row counts"])
        self.assertIn("games shrank from 50 to 10 rows", report.warnings[0][1])


if __name__ == "__main__":
    unittest.main()
