"""
Sports Hub dashboard — entry point.

Run from the project root:
    streamlit run dashboard/app.py

This file sets up the page menu and the filter bar (team, season,
season type). Each page lives in views/ and reads the chosen filters from
st.session_state, so every page stays in sync as you click around.
"""

import streamlit as st

import data
from components import (
    SEASON_TYPE_LABELS,
    inject_css,
    persisted_widget,
    season_label,
    team_meta,
)
from config import TEAM_ORDER

st.set_page_config(
    page_title="Sports Hub",
    page_icon=":material/sports:",
    layout="wide",
)
inject_css()

# Pages, in menu order. To add a page: create views/<name>.py and add a line.
pages = [
    st.Page("views/overview.py", title="Overview", icon=":material/dashboard:"),
    st.Page("views/team.py", title="Team", icon=":material/groups:"),
    st.Page("views/preview.py", title="Game Preview", icon=":material/event:"),
    st.Page("views/game.py", title="Game Center", icon=":material/scoreboard:"),
    st.Page("views/player.py", title="Player", icon=":material/person:"),
    st.Page("views/opponents.py", title="Opponents", icon=":material/swords:"),
]
# Menu along the top rather than in a sidebar: on a phone it folds into a
# menu button, instead of a sidebar that has to be opened and closed.
page = st.navigation(pages, position="top")


def filter_bar():
    """
    Team / season / season type pickers, drawn at the top of every page
    except the Overview. On a laptop they sit in one row; on a phone
    Streamlit stacks the three columns into three short rows.
    """
    teams = data.tracked_teams().set_index("name")
    team_names = [name for name in TEAM_ORDER if name in teams.index]
    team_col, season_col, type_col = st.columns([4, 2, 3], vertical_alignment="bottom")

    team_name = persisted_widget(
        team_col.segmented_control,
        "Team",
        team_names,
        "team",
        team_names[0],
        format_func=lambda name: team_meta(name)["short"],
        label_visibility="collapsed",
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
        season_col.caption("No games loaded for this team yet.")
        return

    seasons = sorted(games["season_year"].unique(), reverse=True)
    season_year = persisted_widget(
        season_col.selectbox,
        "Season",
        seasons,
        "season_year",
        seasons[0],
        format_func=lambda year: f"{season_label(team['league'], year)} season",
        label_visibility="collapsed",
    )

    # Start on the season type of the most recent finished game (e.g.
    # preseason in September), falling back to the regular season.
    in_season = games[games["season_year"] == season_year]
    finals = in_season[in_season["status"] == "final"]
    default_type = finals["season_type"].iloc[-1] if not finals.empty else "regular"
    season_types = [t for t in SEASON_TYPE_LABELS if t in set(in_season["season_type"])]
    persisted_widget(
        type_col.segmented_control,
        "Season type",
        season_types,
        "season_type",
        default_type,
        format_func=SEASON_TYPE_LABELS.get,
        label_visibility="collapsed",
    )


if page.title != "Overview":
    filter_bar()

page.run()

# --- Footer ------------------------------------------------------------------
st.divider()
note_col, button_col = st.columns([3, 1], vertical_alignment="center")
note_col.caption("Data updates nightly at 4 AM. Game previews come live from ESPN.")
if button_col.button("Refresh data", icon=":material/refresh:", width="stretch"):
    st.cache_data.clear()
    st.rerun()
