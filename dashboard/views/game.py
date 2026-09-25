"""Game Center — scoreboard, line score, and box score for one finished game."""

import pandas as pd
import streamlit as st

import data
import stats
from components import (
    add_results,
    empty_state,
    format_date,
    format_datetime,
    matchup,
    page_header,
    matchup_card,
    persisted_widget,
    stat_table,
    team_meta,
)
from config import STAT_GROUPS

team_name = st.session_state["team"]
team_id = st.session_state["team_id"]
league = st.session_state["league"]
season_year = st.session_state.get("season_year")
season_type = st.session_state.get("season_type")

page_header("Game Center", team_name, team_name=team_name)

games = add_results(data.team_games(team_id))
games = games[
    (games["season_year"] == season_year)
    & (games["season_type"] == season_type)
    & games["has_box_score"]
].sort_values("game_time", ascending=False)

if games.empty:
    empty_state("No finished games with box scores for this season yet.")
    st.stop()

labels = {
    row.game_id: f"{format_date(row.game_time)} · {matchup(row._asdict())} · "
    f"{row.result_label}"
    for row in games.itertuples()
}
game_id = persisted_widget(
    st.selectbox,
    "Game",
    list(labels),
    "game_id",
    games["game_id"].iloc[0],
    format_func=labels.get,
)

# --- Scoreboard --------------------------------------------------------------
game = data.game_header(game_id).iloc[0]
periods = data.game_periods(game_id)
status = "Final"
if (periods["period_type"] == "shootout").any():
    status = "Final/SO"
elif (periods["period_type"] == "overtime").any():
    status = "Final/OT"


matchup_card(
    away={"name": game["away_team"], "big": f"{game['away_score']:.0f}"},
    home={"name": game["home_team"], "big": f"{game['home_score']:.0f}"},
    center_lines=[status, format_datetime(game["game_time"]), game["venue_name"]],
    season_type=game["season_type"],
)

# --- Line score --------------------------------------------------------------
if not periods.empty:
    short = periods["period_label"].iloc[0][0]  # "Quarter" -> "Q", "Half" -> "H"

    def period_name(row):
        if row["period_type"] == "regulation":
            return f"{short}{row['period_number']}"
        if row["period_type"] == "shootout":
            return "SO"
        return "OT" if row["period_number"] == 1 else f"{row['period_number']}OT"

    columns = periods.apply(period_name, axis=1).tolist()
    line = pd.DataFrame(
        [periods["away_score"].tolist(), periods["home_score"].tolist()],
        columns=columns,
    )
    line.insert(
        0,
        "Team",
        [team_meta(game["away_team"])["short"], team_meta(game["home_team"])["short"]],
    )
    line["T"] = [game["away_score"], game["home_score"]]
    st.subheader("Line score")
    st.dataframe(line, hide_index=True)

# --- Box scores: our team, then the opponent ---------------------------------


def box_score(side_team_id):
    """Every stat table for one team's side of this game."""
    wide = stats.pivot_stats(data.player_stat_rows(side_team_id, game_id=game_id))
    if wide.empty:
        empty_state("No box score stored for this team.")
        return
    names = data.players(side_team_id).set_index("player_id")
    for group in STAT_GROUPS[league]:
        table = stats.per_game_table(wide, group)
        if table.empty:
            continue
        table = stats.sort_group_table(table, group)
        table.insert(0, "Player", table["player_id"].map(names["name"]))
        table.insert(1, "Pos", table["player_id"].map(names["position"]))
        st.markdown(f"**{group['title']}**")
        stat_table(
            table,
            group,
            lead_columns=["Player", "Pos"],
            key=f"box_{side_team_id}_{group['title']}",
        )


if game["home_team_id"] == team_id:
    opp_team_id, opp_name = game["away_team_id"], game["away_team"]
else:
    opp_team_id, opp_name = game["home_team_id"], game["home_team"]

st.subheader("Box score")
our_tab, opp_tab = st.tabs([team_meta(team_name)["short"], opp_name])
with our_tab:
    box_score(team_id)
with opp_tab:
    box_score(int(opp_team_id))
