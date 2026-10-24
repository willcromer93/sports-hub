"""
Tests for the league registry in scripts/leagues.py. Run from the project root:

    venv/bin/python -m unittest discover -s tests -v
"""

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import leagues  # noqa: E402


class RegistryTests(unittest.TestCase):
    def test_all_seven_leagues_are_defined(self):
        self.assertEqual(
            sorted(leagues.LEAGUES), ["CFB", "MLB", "NBA", "NCAAB", "NFL", "NHL", "WNBA"]
        )

    def test_the_four_original_leagues_come_first_in_their_original_order(self):
        # Row ids are assigned in insertion order, so this order must not change
        self.assertEqual(list(leagues.LEAGUES)[:4], ["NBA", "NCAAB", "NHL", "NFL"])

    def test_each_league_is_internally_consistent(self):
        for code, league in leagues.LEAGUES.items():
            with self.subTest(code):
                self.assertEqual(league.code, code)
                self.assertIn("/", league.sport_path)
                self.assertIn(league.team_source, ("teams_list", "fbs_standings"))
                # the floor must sit below what ESPN lists, or a healthy reply would fail
                self.assertLess(league.min_teams, league.expected_teams)
                self.assertGreater(league.min_roster, 0)
                # ...but above 50, the silent truncation size, for the big college lists
                if league.expected_teams > 50:
                    self.assertGreater(league.min_teams, 50)

    def test_featured_teams_belong_to_known_leagues_and_are_unique(self):
        seen = set()
        for team in leagues.FEATURED_TEAMS:
            self.assertIn(team.league, leagues.LEAGUES)
            self.assertNotIn((team.league, team.espn_id), seen)
            seen.add((team.league, team.espn_id))
        self.assertEqual(len(leagues.FEATURED_TEAMS), 4)

    def test_featured_teams_lookup(self):
        self.assertEqual([t.label for t in leagues.featured_teams("NFL")], ["Colts"])
        self.assertEqual(leagues.featured_teams("MLB"), [])


class ParseLeagueCodesTests(unittest.TestCase):
    def test_empty_and_none_mean_no_leagues(self):
        self.assertEqual(leagues.parse_league_codes(""), [])
        self.assertEqual(leagues.parse_league_codes(None), [])
        self.assertEqual(leagues.parse_league_codes(" , "), [])

    def test_normalizes_case_spaces_duplicates_and_order(self):
        self.assertEqual(leagues.parse_league_codes("nhl, NBA ,nba"), ["NBA", "NHL"])
        # registry order, not the order typed
        self.assertEqual(leagues.parse_league_codes("NFL,NBA"), ["NBA", "NFL"])

    def test_unknown_code_is_an_error_that_names_it(self):
        with self.assertRaises(ValueError) as ctx:
            leagues.parse_league_codes("NBA,CBB,XFL")
        self.assertIn("CBB", str(ctx.exception))
        self.assertIn("XFL", str(ctx.exception))

    def test_reads_the_environment_setting(self):
        with mock.patch.dict(os.environ, {"LEAGUES_ALL": "nba,wnba"}):
            self.assertEqual(leagues.leagues_all(), ["NBA", "WNBA"])
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("LEAGUES_ALL", None)
            self.assertEqual(leagues.leagues_all(), [])


if __name__ == "__main__":
    unittest.main()
