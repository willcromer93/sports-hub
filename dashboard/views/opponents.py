"""Opponents — how opposing players have done against the selected team."""

import streamlit as st

import data
import stats
from components import (
    add_results,
    empty_state,
    format_date,
    matchup,
    page_header,
    persisted_widget,
    season_label,
    season_type_badge,
    stat_table,
    team_meta,
)
from config import DEFAULT_STAT_MODE, STAT_GROUPS

ALL_OPPONENTS = 0  # stand-in "team id" for the All opponents choice
THIS_SEASON = "This season"
ALL_SEASONS = "All seasons"

team_name = st.session_state["team"]
team_id = st.session_state["team_id"]
league = st.session_state["league"]
season_year = st.session_state.get("season_year")
season_type = st.session_state.get("season_type")
short = team_meta(team_name)["short"]

page_header("Opponents", f"Opposing players vs {short}", team_name=team_name)
if season_year is None:
    empty_state("No games loaded for this team yet.")
    st.stop()

# --- Controls ----------------------------------------------------------------
scope_col, opp_col, mode_col = st.columns([2, 3, 2], vertical_alignment="bottom")
scope = (
    scope_col.segmented_control(
        "Games", [THIS_SEASON, ALL_SEASONS], default=THIS_SEASON, key="opp_scope"
    )
    or THIS_SEASON
)
st.markdown(
    f"**{season_label(league, season_year) if scope == THIS_SEASON else 'All seasons'}**"
    f" &nbsp; {season_type_badge(season_type)}"
)

rows = data.player_stat_rows(
    team_id,
    season_year if scope == THIS_SEASON else None,
    season_type,
    opponents=True,
)
wide = stats.pivot_stats(rows)
if wide.empty:
    empty_state(f"No opponent box scores vs {short} for these games yet.")
    st.stop()

team_names = data.all_teams().set_index("team_id")["name"]
opponent_ids = sorted(wide["team_id"].unique(), key=lambda tid: team_names[tid])
opponent = persisted_widget(
    opp_col.selectbox,
    "Opponent",
    [ALL_OPPONENTS] + opponent_ids,
    "opponent_team_id",
    ALL_OPPONENTS,
    format_func=lambda tid: "All opponents"
    if tid == ALL_OPPONENTS
    else team_names[tid],
)
mode = (
    mode_col.segmented_control(
        "Show",
        [stats.PER_GAME, stats.TOTALS],
        default=DEFAULT_STAT_MODE["team"],
        key="opp_stat_mode",
    )
    or DEFAULT_STAT_MODE["team"]
)

if opponent != ALL_OPPONENTS:
    wide = wide[wide["team_id"] == opponent]

# --- Meetings with this opponent ---------------------------------------------
if opponent != ALL_OPPONENTS:
    games = add_results(data.team_games(team_id))
    games = games[
        games["game_id"].isin(wide["game_id"]) & (games["status"] == "final")
    ].sort_values("game_time", ascending=False)
    st.subheader(f"Games vs {short}")
    st.dataframe(
        games.assign(
            Date=games["game_time"].map(format_date),
            Game=games.apply(matchup, axis=1),
            Result=games["result_label"],
        )[["Date", "Game", "Result"]],
        hide_index=True,
        width="stretch",
    )

# --- Player stats vs our team ------------------------------------------------
players = data.all_players().set_index("player_id")
# The team each player was on in their most recent game against us.
latest_team = wide.sort_values("game_id").groupby("player_id")["team_id"].last()

st.subheader(f"Player stats vs {short}")
lead = ["Player", "Pos"] if opponent != ALL_OPPONENTS else ["Player", "Team", "Pos"]
for group in STAT_GROUPS[league]:
    table = stats.season_table(wide, group, mode)
    if table.empty:
        continue
    table = stats.sort_group_table(table, group)
    table.insert(0, "Player", table["player_id"].map(players["name"]))
    table.insert(1, "Team", table["player_id"].map(latest_team).map(team_names))
    table.insert(2, "Pos", table["player_id"].map(players["position"]))
    st.markdown(f"**{group['title']}**")
    stat_table(table, group, mode, lead_columns=lead, key=f"opp_{group['title']}")
st.caption("GP = games played against this team in the selected games.")
