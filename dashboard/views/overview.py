"""Overview — all four teams at a glance: records, last result, next game."""

import pandas as pd
import streamlit as st

import data
from components import (
    SEASON_TYPE_LABELS,
    add_results,
    format_datetime,
    format_short_date,
    format_short_datetime,
    matchup,
    page_header,
    record,
    season_label,
    season_type_note,
    team_meta,
)
from config import TEAM_ORDER

UPCOMING_COUNT = 10
RESULTS_COUNT = 8

page_header("Sports Hub", "Pacers · Purdue · Red Wings · Colts")

teams = data.tracked_teams().set_index("name")
team_names = [name for name in TEAM_ORDER if name in teams.index]

# Every tracked team's games in one table, tagged with the team they belong to.
all_games = []
for name in team_names:
    games = add_results(data.team_games(int(teams.loc[name, "team_id"])))
    games["team"] = name
    all_games.append(games)
all_games = pd.concat(all_games, ignore_index=True)
now = pd.Timestamp.now(tz="UTC")


def open_team(name):
    st.session_state["team"] = name
    st.switch_page("views/team.py")


# --- Team cards -------------------------------------------------------------
for col, name in zip(st.columns(len(team_names)), team_names, strict=True):
    league = teams.loc[name, "league"]
    games = all_games[all_games["team"] == name]
    finals = games[games["status"] == "final"]
    upcoming = games[(games["status"] == "scheduled") & (games["game_time"] >= now)]
    meta = team_meta(name)

    with col.container(border=True):
        logo, title = st.columns([1, 3], vertical_alignment="center")
        logo.image(meta["logo"], width=48)
        title.markdown(f"**{meta['short']}**")
        title.caption(league)

        if finals.empty:
            season_year = games["season_year"].max()
            st.metric(f"{season_label(league, season_year)} record", "0-0")
            st.caption("No games played yet")
        else:
            last = finals.iloc[-1]
            season = finals[
                (finals["season_year"] == last["season_year"])
                & (finals["season_type"] == last["season_type"])
            ]
            st.metric(
                f"{season_label(league, last['season_year'])} "
                f"{SEASON_TYPE_LABELS[last['season_type']].lower()}",
                record(season, league),
            )
            st.caption(
                f"**Last:** {last['result_label']} {matchup(last)} · "
                f"{format_short_date(last['game_time'])}"
            )

        if upcoming.empty:
            st.caption("**Next:** nothing scheduled")
        else:
            nxt = upcoming.iloc[0]
            st.caption(
                f"**Next:** {matchup(nxt)} · {format_datetime(nxt['game_time'])}"
            )

        st.button(
            "Team page",
            key=f"open_{name}",
            on_click=open_team,
            args=(name,),
            icon=":material/arrow_forward:",
            width="stretch",
        )

# --- Upcoming games and latest results ---------------------------------------
# Fixed pixel widths for the narrow columns, so Game gets the leftover space.
table_columns = {
    "logo": st.column_config.ImageColumn("", width=40),
    "Team": st.column_config.TextColumn("Team", width=85),
    "Type": st.column_config.TextColumn("Type", width=110),
}
all_games["logo"] = all_games["team"].map(lambda name: team_meta(name)["logo"])
all_games["Team"] = all_games["team"].map(lambda name: team_meta(name)["short"])
all_games["Game"] = all_games.apply(matchup, axis=1)
# Flags preseason/postseason games so they stand out from regular season.
all_games["Type"] = all_games["season_type"].map(season_type_note)

st.subheader("Upcoming")
upcoming = all_games[
    (all_games["status"] == "scheduled") & (all_games["game_time"] >= now)
]
upcoming = upcoming.sort_values("game_time").head(UPCOMING_COUNT)
upcoming["When"] = upcoming["game_time"].map(format_short_datetime)
st.dataframe(
    upcoming[["logo", "Team", "Game", "When", "Type"]],
    column_config=table_columns,
    hide_index=True,
    width="stretch",
)

st.subheader("Latest results")
results = all_games[all_games["status"] == "final"]
results = results.sort_values("game_time", ascending=False).head(RESULTS_COUNT)
results["Date"] = results["game_time"].map(format_short_date)
results["Result"] = results["result_label"]
st.dataframe(
    results[["logo", "Team", "Game", "Result", "Date", "Type"]],
    column_config=table_columns,
    hide_index=True,
    width="stretch",
)
