"""Game Preview — pregame matchup for an upcoming game, live from ESPN."""

from html import escape

import pandas as pd
import streamlit as st

import data
from components import (
    add_results,
    empty_state,
    format_date,
    format_datetime,
    format_short_date,
    local_time,
    matchup,
    matchup_card,
    page_header,
    persisted_widget,
    team_meta,
)

UPCOMING_CHOICES = 5  # how many upcoming games the picker offers

team_name = st.session_state["team"]
team_id = st.session_state["team_id"]
league = st.session_state["league"]
short = team_meta(team_name)["short"]

page_header("Game Preview", team_name, team_name=team_name)

games = add_results(data.team_games(team_id))
now = pd.Timestamp.now(tz="UTC")
upcoming = games[(games["status"] == "scheduled") & (games["game_time"] >= now)]
upcoming = upcoming.sort_values("game_time").head(UPCOMING_CHOICES)
if upcoming.empty:
    empty_state("No upcoming games scheduled.")
    st.stop()

labels = {
    row.game_id: f"{format_datetime(row.game_time)} · {matchup(row._asdict())}"
    for row in upcoming.itertuples()
}
game_id = persisted_widget(
    st.selectbox,
    "Upcoming game",
    list(labels),
    "preview_game_id",
    upcoming["game_id"].iloc[0],
    format_func=labels.get,
)
game = upcoming.set_index("game_id").loc[game_id]

# --- Live preview from ESPN (nothing stored; cached for an hour) --------------
preview = data.pregame(league, game["external_id"])
our_espn_id = data.tracked_teams().set_index("name").loc[team_name, "espn_id"]
if preview:
    ours = preview.get(our_espn_id, {})
    theirs = next((t for tid, t in preview.items() if tid != our_espn_id), {})
else:
    ours, theirs = {}, {}
opp_name = theirs.get("name") or game["opponent"]
opp_short = theirs.get("short") or opp_name

# --- Matchup header ------------------------------------------------------------


def side(team, fallback_name):
    return {
        "name": team.get("short") or fallback_name,
        "logo": team.get("logo"),
        "small": team.get("record"),
    }


# Away team on the left, home on the right, like a scoreboard.
our_side, their_side = side(ours, short), side(theirs, opp_name)
matchup_card(
    away=their_side if game["is_home"] else our_side,
    home=our_side if game["is_home"] else their_side,
    center_lines=[
        format_date(game["game_time"]),
        local_time(game["game_time"]).strftime("%-I:%M %p"),
        game["venue_name"],
    ],
    season_type=game["season_type"],
)

if not preview:
    st.warning(
        "Couldn't reach ESPN for the live preview right now. "
        "Previous meetings below come from our own database.",
        icon=":material/cloud_off:",
    )

# --- Team stats side by side ---------------------------------------------------
if ours.get("team_stats") or theirs.get("team_stats"):
    st.subheader("Team stats")
    labels_in_order = list(
        dict.fromkeys(
            list(ours.get("team_stats", {})) + list(theirs.get("team_stats", {}))
        )
    )
    comparison = pd.DataFrame(
        {
            "Stat": labels_in_order,
            short: [ours.get("team_stats", {}).get(label) for label in labels_in_order],
            opp_short: [
                theirs.get("team_stats", {}).get(label) for label in labels_in_order
            ],
        }
    )
    st.dataframe(comparison, hide_index=True, width="stretch")
    st.caption("Season to date, from ESPN.")

# --- Leaders -------------------------------------------------------------------


def leaders_column(col, team, name):
    with col:
        st.markdown(f"**{name}**")
        if not team.get("leaders"):
            st.caption("No season leaders yet.")
            return
        for leader in team["leaders"]:
            # One HTML flex row per leader so the photo stays beside the
            # text on a phone (st.columns would stack them).
            photo = (
                f"<img src='{leader['headshot']}' alt='' "
                "style='width:52px;height:auto;flex:none'>"
                if leader["headshot"]
                else "<div style='width:52px;flex:none'></div>"
            )
            position = f" · {leader['position']}" if leader["position"] else ""
            st.markdown(
                f"<div class='sh-tile' style='display:flex;align-items:center;"
                f"gap:.75rem;margin-bottom:.5rem'>{photo}<div style='min-width:0'>"
                f"<div class='sh-label'>{escape(leader['category'] or '')}</div>"
                f"<div style='font-weight:600'>{escape(leader['player'] or '')}"
                f"{escape(position)}</div>"
                f"<div style='font-size:.875rem'>{escape(leader['line'] or '')}</div>"
                f"</div></div>",
                unsafe_allow_html=True,
            )


if preview:
    st.subheader("Team leaders")
    our_col, their_col = st.columns(2, gap="large")
    leaders_column(our_col, ours, short)
    leaders_column(their_col, theirs, opp_short)

# --- Injuries ------------------------------------------------------------------
if preview:
    st.subheader("Injury report")
    our_col, their_col = st.columns(2, gap="large")
    for col, team, name in [(our_col, ours, short), (their_col, theirs, opp_short)]:
        col.markdown(f"**{name}**")
        if team.get("injuries"):
            col.dataframe(
                pd.DataFrame(team["injuries"]), hide_index=True, width="stretch"
            )
        else:
            col.caption("No injuries reported.")

# --- Last five games -------------------------------------------------------------
if preview:
    st.subheader("Last five games")
    our_col, their_col = st.columns(2, gap="large")
    for col, team, name in [(our_col, ours, short), (their_col, theirs, opp_short)]:
        col.markdown(f"**{name}**")
        if not team.get("last_five"):
            col.caption("No recent games.")
            continue
        recent = pd.DataFrame(team["last_five"])
        recent["Date"] = pd.to_datetime(recent["Date"], utc=True)
        recent = recent.sort_values("Date", ascending=False)
        recent["Date"] = recent["Date"].map(format_short_date)
        col.dataframe(recent, hide_index=True, width="stretch")
    st.caption("Includes preseason and last season's games, as ESPN reports them.")

# --- Previous meetings (from our database) ----------------------------------------
st.subheader(f"Previous meetings with the {opp_name}")
meetings = games[
    (games["opponent_id"] == game["opponent_id"]) & (games["status"] == "final")
].sort_values("game_time", ascending=False)
if meetings.empty:
    st.caption("No previous meetings in our database yet.")
else:
    st.dataframe(
        meetings.assign(
            Date=meetings["game_time"].map(format_date),
            Game=meetings.apply(matchup, axis=1),
            Result=meetings["result_label"],
        )[["Date", "Game", "Result"]],
        hide_index=True,
        width="stretch",
    )

    if st.button(f"{opp_name} players vs {short}", icon=":material/arrow_forward:"):
        st.session_state["opponent_team_id"] = int(game["opponent_id"])
        st.switch_page("views/opponents.py")
