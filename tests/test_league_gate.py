"""
Tests for scripts/league_gate.py with a fake database connection returning canned rows.
Run from the project root:

    venv/bin/python -m unittest discover -s tests -v
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

_tmp = tempfile.TemporaryDirectory()
os.environ.setdefault("LOG_DIR", _tmp.name)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import league_gate as gate  # noqa: E402
from leagues import LEAGUES  # noqa: E402

NBA, NHL = LEAGUES["NBA"], LEAGUES["NHL"]


class FakeCursor:
    def __init__(self, answers):
        self.answers, self.rows = answers, []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        flat = " ".join(sql.split())
        for needle, rows in self.answers:
            if needle in flat:
                self.rows = rows
                return
        raise AssertionError(f"no canned answer for: {flat[:90]}")

    def fetchall(self):
        return self.rows


class FakeConn:
    def __init__(self, *answers):
        self.answers = list(answers)

    def cursor(self):
        return FakeCursor(self.answers)


class TeamCountTests(unittest.TestCase):
    def test_matches_espn(self):
        conn = FakeConn(("count(*) FROM teams", [(30,)]))
        self.assertEqual(gate.gate_team_count(conn, NBA, 30).status, "PASS")

    def test_a_different_count_fails_and_says_both_numbers(self):
        conn = FakeConn(("count(*) FROM teams", [(29,)]))
        r = gate.gate_team_count(conn, NBA, 30)
        self.assertEqual(r.status, "FAIL")
        self.assertIn("29", r.detail)
        self.assertIn("30", r.detail)


class RosterTests(unittest.TestCase):
    def test_no_short_rosters_passes(self):
        self.assertEqual(gate.gate_rosters(FakeConn(("HAVING", [])), NBA).status, "PASS")

    def test_short_rosters_fail_and_name_the_teams(self):
        r = gate.gate_rosters(FakeConn(("HAVING", [("Utah Jazz", 3), ("Miami Heat", 7)])), NBA)
        self.assertEqual(r.status, "FAIL")
        self.assertIn("Utah Jazz (3)", r.detail)
        self.assertIn("2 team(s)", r.detail)


class BoxScoreTests(unittest.TestCase):
    def check(self, total, missing, flagged=0):
        return gate.gate_box_scores(FakeConn(("FROM games g JOIN teams t", [(total, missing, flagged)])), NBA)

    def test_full_coverage_passes(self):
        self.assertEqual(self.check(200, 0).status, "PASS")

    def test_exactly_99_percent_passes_below_fails(self):
        self.assertEqual(self.check(100, 1).status, "PASS")
        self.assertEqual(self.check(100, 2).status, "FAIL")

    def test_no_games_yet_is_a_review_not_a_pass(self):
        self.assertEqual(self.check(0, 0).status, "REVIEW")

    def test_games_espn_has_no_summary_for_do_not_count_against_coverage(self):
        r = self.check(200, 0, flagged=4)  # 4 of 204 sides = 2%
        self.assertEqual(r.status, "PASS")
        self.assertIn("4 side(s)", r.detail)

    def test_too_many_flagged_sides_is_a_review(self):
        self.assertEqual(self.check(180, 0, flagged=20).status, "REVIEW")  # 10% of the sides

    def test_missing_box_scores_still_fail_even_with_flagged_games_around(self):
        self.assertEqual(self.check(100, 5, flagged=2).status, "FAIL")


class PeriodScoreTests(unittest.TestCase):
    def check(self, league, finals, with_periods, mismatched):
        return gate.gate_period_scores(
            FakeConn(("LEFT JOIN", [(finals, with_periods, mismatched)])), league
        )

    def test_everything_adds_up(self):
        self.assertEqual(self.check(NBA, 100, 100, 0).status, "PASS")

    def test_missing_periods_fail(self):
        self.assertEqual(self.check(NBA, 100, 90, 0).status, "FAIL")

    def test_real_mismatches_fail(self):
        self.assertEqual(self.check(NBA, 100, 100, 5).status, "FAIL")

    def test_an_acknowledged_espn_error_is_excluded(self):
        # NHL 401892450 is acknowledged in sanity_checks, so 1 mismatch in the NHL is fine...
        r = self.check(NHL, 100, 100, 1)
        self.assertEqual(r.status, "PASS")
        self.assertIn("acknowledged", r.detail)
        # ...but the same single mismatch in the NBA is real
        self.assertEqual(self.check(NBA, 100, 100, 1).status, "PASS")  # 99% still passes
        self.assertEqual(self.check(NBA, 50, 50, 1).status, "FAIL")  # 98% does not

    def test_no_games_yet_is_a_review(self):
        self.assertEqual(self.check(NBA, 0, 0, 0).status, "REVIEW")


class RollupTests(unittest.TestCase):
    def test_matching_totals_pass(self):
        self.assertEqual(gate.gate_rollups(FakeConn(("WITH direct", [])), NBA).status, "PASS")

    def test_differences_fail_and_are_shown(self):
        conn = FakeConn(("WITH direct", [("points", "regular", 100, 99)]))
        r = gate.gate_rollups(conn, NBA)
        self.assertEqual(r.status, "FAIL")
        self.assertIn("points/regular: direct 100 vs rollup 99", r.detail)


class StatNameTests(unittest.TestCase):
    def test_rates_that_would_be_summed_are_flagged(self):
        names = ["points", "assists", "AVG", "ERA", "OPS", "shotsPerGame", "rushing.rushingYards"]
        self.assertEqual(gate.suspicious_stat_names(names), ["AVG", "ERA", "OPS", "shotsPerGame"])

    def test_names_already_excluded_as_non_additive_are_not_flagged(self):
        names = ["fieldGoalPct", "passing.QBRating", "passing.yardsPerAttempt", "rushing.longRushing"]
        self.assertEqual(gate.suspicious_stat_names(names), [])

    def test_the_production_pattern_is_case_sensitive_and_the_gate_catches_that(self):
        # NON_ADDITIVE_STAT_PATTERN matches "Avg" but not "avg", so a stat named
        # "avgGain" would be SUMMED by the rollups. The gate flags it for review.
        self.assertEqual(gate.suspicious_stat_names(["avgGain", "AVG"]), ["AVG", "avgGain"])

    def test_review_lists_the_suspects_and_says_where_to_fix_them(self):
        r = gate.review_stat_names(FakeConn(("SELECT DISTINCT", [("points",), ("ERA",)])), NBA)
        self.assertEqual(r.status, "REVIEW")
        self.assertIn("ERA", r.detail)
        self.assertIn("NON_ADDITIVE_STAT_PATTERN", r.detail)

    def test_clean_names_pass_and_no_names_is_a_review(self):
        self.assertEqual(gate.review_stat_names(FakeConn(("SELECT DISTINCT", [("points",), ("assists",)])), NBA).status, "PASS")
        self.assertEqual(gate.review_stat_names(FakeConn(("SELECT DISTINCT", [])), NBA).status, "REVIEW")


class LastRunTests(unittest.TestCase):
    def run_with(self, **overrides):
        run = {"status": "ok", "errors": [], "warnings": [], "counts": {"sanity problems": 0}, "duration_seconds": 300, "started": "2026-10-24T04:00:00"}
        run.update(overrides)
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "last_pipeline.json"
            path.write_text(json.dumps(run))
            return gate.gate_last_run(path, budget_minutes=25)

    def test_a_clean_fast_run_passes(self):
        self.assertEqual(self.run_with().status, "PASS")

    def test_each_kind_of_problem_fails(self):
        for overrides in (
            {"status": "errors", "errors": [{"step": "x", "error": "y"}]},
            {"warnings": [{"step": "x", "message": "y"}]},
            {"counts": {"sanity problems": 2}},
            {"duration_seconds": 26 * 60},
        ):
            with self.subTest(overrides=overrides):
                self.assertEqual(self.run_with(**overrides).status, "FAIL")

    def test_exactly_on_budget_passes(self):
        self.assertEqual(self.run_with(duration_seconds=25 * 60).status, "PASS")

    def test_a_missing_file_is_a_review(self):
        self.assertEqual(gate.gate_last_run("/nonexistent/last_pipeline.json", 25).status, "REVIEW")


class FeaturedTests(unittest.TestCase):
    def test_exactly_the_configured_four_passes(self):
        rows = [("NBA", "11"), ("NCAAB", "2509"), ("NHL", "5"), ("NFL", "11")]
        self.assertEqual(gate.gate_featured(FakeConn(("WHERE is_featured", rows))).status, "PASS")

    def test_an_extra_featured_team_fails(self):
        rows = [("NBA", "11"), ("NCAAB", "2509"), ("NHL", "5"), ("NFL", "11"), ("NBA", "7")]
        self.assertEqual(gate.gate_featured(FakeConn(("WHERE is_featured", rows))).status, "FAIL")


class UsageTests(unittest.TestCase):
    def test_bad_arguments_exit_2_without_touching_anything(self):
        self.assertEqual(gate.main([]), 2)  # no league
        self.assertEqual(gate.main(["NBA", "NFL"]), 2)  # more than one
        self.assertEqual(gate.main(["XYZ"]), 2)  # unknown


if __name__ == "__main__":
    unittest.main()
