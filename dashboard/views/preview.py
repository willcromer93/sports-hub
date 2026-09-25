"""Game Preview — pregame matchup for an upcoming game, live from ESPN."""

import pandas as pd
import streamlit as st

import data
from components import (
    add_results,
    empty_state,
    format_date,
    format_datetime,
    format_short_date,
    matchup,
    page_header,
    persisted_widget,
    season_type_badge,
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


def team_block(col, team, fallback_name, align):
    with col:
        if team.get("logo"):
            st.image(team["logo"], width=64)
        st.markdown(
            f"<div style='text-align:{align}'>"
            f"<div style='font-size:.8rem;opacity:.6;text-transform:uppercase;"
            f"letter-spacing:.05em'>{team.get('home_away') or ''}</div>"
            f"<div style='font-size:1.2rem;font-weight:600'>"
            f"{team.get('name') or fallback_name}</div>"
            f"<div style='opacity:.7'>{team.get('record') or ''}</div></div>",
            unsafe_allow_html=True,
        )


with st.container(border=True):
    left, mid, right = st.columns(3, vertical_alignment="center")
    # Away team on the left, home on the right, like a scoreboard.
    if game["is_home"]:
        team_block(left, theirs, opp_name, "left")
        team_block(right, ours, team_name, "left")
    else:
        team_block(left, ours, team_name, "left")
        team_block(right, theirs, opp_name, "left")
    mid.markdown(
        f"<div style='text-align:center'><div style='font-size:1.3rem;"
        f"font-weight:600'>{format_datetime(game['game_time'])}</div>"
        f"<div style='opacity:.7'>{game['venue_name'] or ''}</div></div>",
        unsafe_allow_html=True,
    )
    mid.markdown(season_type_badge(game["season_type"]), text_alignment="center")

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
            with st.container(border=True):
                photo, text = st.columns([1, 4], vertical_alignment="center")
                if leader["headshot"]:
                    photo.image(leader["headshot"], width=56)
                text.caption(leader["category"])
                position = f" · {leader['position']}" if leader["position"] else ""
                text.markdown(f"**{leader['player']}**{position}  \n{leader['line']}")


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

    def open_opponent():
        st.session_state["opponent_team_id"] = int(game["opponent_id"])

    if st.button(
        f"{opp_name} players vs {short}",
        icon=":material/arrow_forward:",
        on_click=open_opponent,
    ):
        st.switch_page("views/opponents.py")
