"""
The rule for "should tonight's roster pull mark missing players as departed?".

Kept free of database and network code so it can be tested exhaustively
(tests/test_roster_tracking.py).

The danger this guards against: a bad ESPN reply (a roster of 2 players instead
of 77) must never wipe a whole team's roster. But real mass departures happen
(the NFL cuts from about 90 to 53 players on one day), and those must go through.
So the rule is relative: record departures unless the roster shrank to under half.
"""

from typing import NamedTuple, Optional

# If ESPN returns fewer than this fraction of the players we had on the roster,
# treat it as a bad response and record nothing.
MIN_FRACTION = 0.5

# If more than this fraction of the roster departs in one night, still record it,
# but send an informational alert (cutdown day? a trade spree?).
BIG_CHANGE_FRACTION = 0.25


class Decision(NamedTuple):
    record: bool  # True: go ahead and mark the departing players
    warning: Optional[str]  # set when we refuse to record (this becomes an alert)
    heads_up: Optional[str]  # set when it's recorded but unusually large


def decide_departures(previous_on_roster, fetched, departing):
    """previous_on_roster: players marked on the roster before tonight's pull.
    fetched: players ESPN's roster listed tonight.
    departing: players who were on the roster but are missing tonight."""
    if fetched == 0:
        return Decision(False, "ESPN returned an empty roster; departures not recorded", None)

    if previous_on_roster > 0 and fetched < MIN_FRACTION * previous_on_roster:
        return Decision(
            False,
            f"roster shrank from {previous_on_roster} to {fetched} players "
            f"(under {MIN_FRACTION:.0%}); looks like a bad response, "
            f"departures not recorded",
            None,
        )

    heads_up = None
    if previous_on_roster > 0 and departing > BIG_CHANGE_FRACTION * previous_on_roster:
        heads_up = (
            f"{departing} of {previous_on_roster} players left the roster at once "
            f"(cutdown day or a trade spree?)"
        )
    return Decision(True, None, heads_up)
