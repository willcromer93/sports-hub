"""
Sports Hub dashboard — entry point.

Run from the project root:
    streamlit run dashboard/app.py

This file sets up the page list and the sidebar filters (team, season,
season type). Each page lives in views/ and reads the chosen filters from
st.session_state, so every page stays in sync as you click around.
"""

import streamlit as st

import data
from components import SEASON_TYPE_LABELS, persisted_widget, season_label, team_meta
from config import TEAM_ORDER

st.set_page_config(
    page_title="Sports Hub",
    page_icon=":material/sports:",
    layout="wide",
)

# Pages, in sidebar order. To add a page: create views/<name>.py and add a line.
pages = [
    st.Page("views/overview.py", title="Overview", icon=":material/dashboard:"),
    st.Page("views/team.py", title="Team", icon=":material/groups:"),
    st.Page("views/preview.py", title="Game Preview", icon=":material/event:"),
    st.Page("views/game.py", title="Game Center", icon=":material/scoreboard:"),
    st.Page("views/player.py", title="Player", icon=":material/person:"),
    st.Page("views/opponents.py", title="Opponents", icon=":material/swords:"),
]
page = st.navigation(pages)


def sidebar_filters():
    teams = data.tracked_teams().set_index("name")
    team_names = [name for name in TEAM_ORDER if name in teams.index]
    team_name = persisted_widget(
        st.sidebar.radio,
        "Team",
        team_names,
        "team",
        team_names[0],
        format_func=lambda name: team_meta(name)["short"],
    )
    team = teams.loc[team_name]
    st.session_state["team_id"] = int(team["team_id"])
    st.session_state["league"] = team["league"]

    # A different team has different seasons, so start it fresh on its own
    # defaults rather than carrying over the last team's season picks.
    if st.session_state.get("_filters_team") != team_name:
        st.session_state["_filters_team"] = team_name
        st.session_state.pop("season_year", None)
        st.session_state.pop("season_type", None)

    games = data.team_games(int(team["team_id"]))
    if games.empty:
        st.sidebar.caption("No games loaded for this team yet.")
        return

    seasons = sorted(games["season_year"].unique(), reverse=True)
    season_year = persisted_widget(
        st.sidebar.selectbox,
        "Season",
        seasons,
        "season_year",
        seasons[0],
        format_func=lambda year: season_label(team["league"], year),
    )

    # Start on the season type of the most recent finished game (e.g.
    # preseason in September), falling back to the regular season.
    in_season = games[games["season_year"] == season_year]
    finals = in_season[in_season["status"] == "final"]
    default_type = finals["season_type"].iloc[-1] if not finals.empty else "regular"
    season_types = [t for t in SEASON_TYPE_LABELS if t in set(in_season["season_type"])]
    persisted_widget(
        st.sidebar.radio,
        "Season type",
        season_types,
        "season_type",
        default_type,
        format_func=SEASON_TYPE_LABELS.get,
    )


if page.title != "Overview":
    sidebar_filters()

st.sidebar.divider()
if st.sidebar.button("Refresh data", icon=":material/refresh:", width="stretch"):
    st.cache_data.clear()
    st.rerun()
st.sidebar.caption("Data updates nightly at 4 AM.")

page.run()
