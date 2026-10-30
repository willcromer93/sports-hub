"""
Tests for the summary parsers in scripts/espn.py (no network, no database): the per-game
player details, attendance, officials and the cache trimming. Run from the project root:

    venv/bin/python -m unittest discover -s tests -v
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import espn  # noqa: E402


def box(group_keys, athletes, group_name="players"):
    return {"statistics": [{"name": group_name, "keys": group_keys, "athletes": athletes}]}


class PlayerDetailsTests(unittest.TestCase):
    def test_basketball_starter_with_position_and_jersey(self):
        entry = {
            "athlete": {"id": "1", "displayName": "A", "jersey": "00",
                        "position": {"abbreviation": "G"}},
            "starter": True, "didNotPlay": False, "ejected": False, "reason": "COACH'S DECISION",
            "stats": ["30"],
        }
        player = espn.parse_box_score(box(["minutes"], [entry]), "NBA")["1"]
        self.assertEqual(player["details"], {
            "is_starter": True, "was_ejected": False,
            "dnp_reason": None,  # ESPN fills `reason` for players who played; ignore it
            "is_active": None, "was_scratched": None, "jersey": "00", "position": "G",
        })
        self.assertTrue(player["did_play"])

    def test_basketball_dnp_keeps_its_reason(self):
        entry = {"athlete": {"id": "2", "displayName": "B"}, "starter": False,
                 "didNotPlay": True, "reason": "COACH'S DECISION", "ejected": False, "stats": []}
        player = espn.parse_box_score(box(["minutes"], [entry]), "WNBA")["2"]
        self.assertFalse(player["did_play"])
        self.assertEqual(player["details"]["dnp_reason"], "COACH'S DECISION")
        self.assertIs(player["details"]["is_starter"], False)

    def test_nhl_has_active_and_scratched_but_no_starter(self):
        entry = {"athlete": {"id": "3", "displayName": "C", "jersey": "9", "active": True,
                             "scratched": False, "position": {"abbreviation": "C", "name": "Center"}},
                 "stats": ["1"]}
        details = espn.parse_box_score(box(["goals"], [entry], "forwards"), "NHL")["3"]["details"]
        self.assertEqual((details["is_active"], details["was_scratched"]), (True, False))
        self.assertIsNone(details["is_starter"])
        self.assertIsNone(details["was_ejected"])
        self.assertEqual((details["jersey"], details["position"]), ("9", "C"))

    def test_nfl_has_a_jersey_but_no_position(self):
        entry = {"athlete": {"id": "4", "displayName": "D", "jersey": "15"}, "stats": ["1"]}
        details = espn.parse_box_score(box(["rushingYards"], [entry], "rushing"), "NFL")["4"]["details"]
        self.assertEqual(details["jersey"], "15")
        self.assertIsNone(details["position"])
        self.assertIsNone(details["is_starter"])

    def test_a_player_in_two_groups_keeps_one_entry_with_details(self):
        athlete = {"id": "5", "displayName": "E", "jersey": "22"}
        summary_box = {"statistics": [
            {"name": "rushing", "keys": ["rushingYards"], "athletes": [{"athlete": athlete, "stats": ["10"]}]},
            {"name": "receiving", "keys": ["receivingYards"], "athletes": [{"athlete": athlete, "stats": ["5"]}]},
        ]}
        players = espn.parse_box_score(summary_box, "NFL")
        self.assertEqual(len(players), 1)
        self.assertEqual(players["5"]["details"]["jersey"], "22")
        self.assertEqual(players["5"]["stats"], {"rushing.rushingYards": 10.0, "receiving.receivingYards": 5.0})


class GameInfoTests(unittest.TestCase):
    def test_attendance_and_officials(self):
        summary = {"gameInfo": {"attendance": 17867, "officials": [
            {"fullName": "Mark Lindsay", "displayName": "Mark Lindsay",
             "position": {"displayName": "Referee"}, "order": 1},
            {"fullName": "J.B. DeRosa", "displayName": "J.B. DeRosa",
             "position": {"displayName": "Referee"}, "order": 2},
        ]}}
        attendance, officials = espn.parse_game_info(summary)
        self.assertEqual(attendance, 17867)
        self.assertEqual(officials, [("Mark Lindsay", "Referee", 1), ("J.B. DeRosa", "Referee", 2)])

    def test_nhl_officials_all_have_order_zero_and_duplicates_are_dropped(self):
        official = {"displayName": "Jon McIsaac", "position": {"displayName": "Referee"}, "order": 0}
        _, officials = espn.parse_game_info({"gameInfo": {"officials": [official, dict(official)]}})
        self.assertEqual(officials, [("Jon McIsaac", "Referee", 0)])

    def test_missing_or_zero_attendance_is_none_and_missing_info_is_fine(self):
        self.assertEqual(espn.parse_game_info({"gameInfo": {"attendance": 0}}), (None, []))
        self.assertEqual(espn.parse_game_info({}), (None, []))
        self.assertEqual(espn.parse_game_info({"gameInfo": {"officials": None}}), (None, []))

    def test_an_official_without_a_name_or_role_is_skipped(self):
        _, officials = espn.parse_game_info({"gameInfo": {"officials": [
            {"position": {"displayName": "Referee"}}, {"displayName": "X"}]}})
        self.assertEqual(officials, [])


class CacheTrimTests(unittest.TestCase):
    def test_only_the_parser_inputs_are_kept(self):
        summary = {"boxscore": {"a": 1}, "gameInfo": {"b": 2}, "header": {"c": 3},
                   "plays": [1] * 500, "videos": [1], "news": [1]}
        self.assertEqual(espn.trim_summary_for_cache(summary),
                         {"boxscore": {"a": 1}, "gameInfo": {"b": 2}, "header": {"c": 3}})

    def test_a_summary_missing_a_part_is_trimmed_without_error(self):
        self.assertEqual(espn.trim_summary_for_cache({"header": {}, "plays": []}), {"header": {}})


if __name__ == "__main__":
    unittest.main()
