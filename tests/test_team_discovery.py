"""
Tests for scripts/team_discovery.py using small synthetic ESPN-shaped replies (no network,
no real ESPN data in this public repo). Run from the project root:

    venv/bin/python -m unittest discover -s tests -v
"""

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import team_discovery as td  # noqa: E402
from leagues import LEAGUES  # noqa: E402


def teams_reply(n, start=1):
    """An ESPN-shaped /teams reply with n teams."""
    return {
        "sports": [
            {
                "leagues": [
                    {
                        "teams": [
                            {"team": {"id": str(i), "displayName": f"Team {i}", "abbreviation": f"T{i}"}}
                            for i in range(start, start + n)
                        ]
                    }
                ]
            }
        ]
    }


def standings_reply(*conferences):
    """An ESPN-shaped standings reply: each conference is a list of team ids."""
    return {
        "children": [
            {
                "name": f"Conference {c}",
                "standings": {
                    "entries": [{"team": {"id": str(i), "displayName": f"Team {i}"}} for i in ids]
                },
            }
            for c, ids in enumerate(conferences)
        ]
    }


class ParseTests(unittest.TestCase):
    def test_teams_list_is_parsed(self):
        teams = td.parse_teams_list(teams_reply(3))
        self.assertEqual([t.espn_id for t in teams], ["1", "2", "3"])
        self.assertEqual(teams[0].name, "Team 1")
        self.assertEqual(teams[0].abbreviation, "T1")

    def test_numeric_ids_become_strings(self):
        reply = teams_reply(1)
        reply["sports"][0]["leagues"][0]["teams"][0]["team"]["id"] = 22
        self.assertEqual(td.parse_teams_list(reply)[0].espn_id, "22")

    def test_wrong_shape_raises_a_clear_error_not_a_keyerror(self):
        for bad in ({}, {"sports": []}, {"sports": [{"leagues": [{}]}]}, None):
            with self.subTest(bad=bad):
                with self.assertRaises(td.DiscoveryError):
                    td.parse_teams_list(bad)

    def test_fbs_standings_walks_nested_conferences(self):
        nested = {"children": [standings_reply([1, 2], [3]), standings_reply([4])]}
        self.assertEqual(sorted(t.espn_id for t in td.parse_fbs_standings(nested)), ["1", "2", "3", "4"])

    def test_malformed_standings_raise_a_clear_error(self):
        bad = {"standings": {"entries": [{"no_team_here": 1}]}}
        with self.assertRaises(td.DiscoveryError):
            td.parse_fbs_standings(bad)


class SafetyCheckTests(unittest.TestCase):
    def test_a_truncated_list_is_rejected_with_a_helpful_message(self):
        # The real trap: ESPN returns 50 college basketball teams when asked without limit=
        teams = td.parse_teams_list(teams_reply(50))
        with self.assertRaises(td.DiscoveryError) as ctx:
            td.check_team_list(LEAGUES["NCAAB"], teams)
        message = str(ctx.exception)
        self.assertIn("50 teams", message)
        self.assertIn("limit", message)

    def test_a_full_list_passes(self):
        td.check_team_list(LEAGUES["NBA"], td.parse_teams_list(teams_reply(30)))

    def test_exactly_the_floor_passes_one_below_fails(self):
        floor = LEAGUES["NBA"].min_teams
        td.check_team_list(LEAGUES["NBA"], td.parse_teams_list(teams_reply(floor)))
        with self.assertRaises(td.DiscoveryError):
            td.check_team_list(LEAGUES["NBA"], td.parse_teams_list(teams_reply(floor - 1)))

    def test_duplicate_ids_are_rejected(self):
        teams = td.parse_teams_list(teams_reply(30)) + td.parse_teams_list(teams_reply(1))
        with self.assertRaises(td.DiscoveryError) as ctx:
            td.check_team_list(LEAGUES["NBA"], teams)
        self.assertIn("duplicate", str(ctx.exception))


class DiscoverTeamsTests(unittest.TestCase):
    def test_teams_list_league_always_asks_for_a_big_limit(self):
        with mock.patch.object(td, "fetch_json", return_value=teams_reply(30)) as fetch:
            teams = td.discover_teams(LEAGUES["NBA"])
        self.assertEqual(len(teams), 30)
        url = fetch.call_args.args[0]
        self.assertTrue(url.endswith("/basketball/nba/teams"))
        self.assertEqual(fetch.call_args.kwargs["params"]["limit"], 1000)

    def test_cfb_uses_the_fbs_standings_not_the_team_list(self):
        reply = standings_reply(list(range(1, 70)), list(range(70, 140)))  # 139 teams
        with mock.patch.object(td, "fetch_json", return_value=reply) as fetch:
            teams = td.discover_teams(LEAGUES["CFB"])
        self.assertEqual(len(teams), 139)
        self.assertIn("/standings", fetch.call_args.args[0])
        self.assertEqual(fetch.call_args.kwargs["params"]["group"], td.FBS_GROUP)

    def test_a_short_reply_from_the_network_raises(self):
        with mock.patch.object(td, "fetch_json", return_value=teams_reply(50)):
            with self.assertRaises(td.DiscoveryError):
                td.discover_teams(LEAGUES["NCAAB"])


if __name__ == "__main__":
    unittest.main()
