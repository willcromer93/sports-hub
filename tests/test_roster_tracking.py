"""
Tests for the departure rule in scripts/roster_tracking.py. Run from the project root:

    venv/bin/python -m unittest discover -s tests -v
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from roster_tracking import decide_departures  # noqa: E402


class DecideDeparturesTests(unittest.TestCase):
    def test_normal_night_with_no_departures_is_quiet(self):
        d = decide_departures(previous_on_roster=77, fetched=77, departing=0)
        self.assertEqual((d.record, d.warning, d.heads_up), (True, None, None))

    def test_a_few_departures_are_recorded_quietly(self):
        d = decide_departures(77, 75, 3)
        self.assertTrue(d.record)
        self.assertIsNone(d.warning)
        self.assertIsNone(d.heads_up)

    def test_empty_roster_is_never_recorded(self):
        d = decide_departures(77, 0, 77)
        self.assertFalse(d.record)
        self.assertIn("empty", d.warning)

    def test_glitch_response_is_refused(self):
        d = decide_departures(77, 2, 75)
        self.assertFalse(d.record)
        self.assertIn("77 to 2", d.warning)

    def test_exactly_half_is_allowed(self):
        # The boundary: under 50% is refused, 50% itself goes through
        self.assertTrue(decide_departures(80, 40, 40).record)
        self.assertFalse(decide_departures(80, 39, 41).record)

    def test_real_nfl_cutdown_goes_through_with_a_heads_up(self):
        # About 90 -> 53 players: 41% shrink, 37 departures. Recorded, and flagged.
        d = decide_departures(90, 53, 37)
        self.assertTrue(d.record)
        self.assertIsNone(d.warning)
        self.assertIn("37 of 90", d.heads_up)

    def test_big_change_boundary(self):
        self.assertIsNone(decide_departures(100, 75, 25).heads_up)  # exactly 25%: quiet
        self.assertIsNotNone(decide_departures(100, 74, 26).heads_up)  # over: heads-up

    def test_brand_new_team_with_no_history_is_fine(self):
        d = decide_departures(previous_on_roster=0, fetched=25, departing=0)
        self.assertEqual((d.record, d.warning, d.heads_up), (True, None, None))

    def test_new_team_but_empty_response_still_warns(self):
        self.assertFalse(decide_departures(0, 0, 0).record)


if __name__ == "__main__":
    unittest.main()
