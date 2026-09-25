"""Player — bio, season line, game log, and a per-game trend chart."""

from datetime import date

import pandas as pd
import streamlit as st

import charts
import data
import stats
from components import (
    add_results,
    empty_state,
    format_date,
    format_short_date,
    format_stat,
    matchup,
    page_header,
    persisted_widget,
    stat_table,
)
from config import DEFAULT_STAT_MODE, STAT_GROUPS

# How many stats to show as tiles in the season line (first N columns).
SEASON_TILES = 6

team_name = st.session_state["team"]
team_id = st.session_state["team_id"]
league = st.session_state["league"]
season_year = st.session_state.get("season_year")
season_type = st.session_state.get("season_type")

roster = data.players(team_id).set_index("player_id")
wide = stats.pivot_stats(data.player_stat_rows(team_id, season_year, season_type))

page_header("Player", team_name, team_name=team_name)
if roster.empty:
    empty_state("No players loaded for this team yet.")
    st.stop()


def option_label(player_id):
    player = roster.loc[player_id]
    number = f" #{player['jersey_number']}" if pd.notna(player["jersey_number"]) else ""
    position = player["position"] if pd.notna(player["position"]) else "—"
    return f"{player['name']} · {position}{number}"


# Players with stats this season first (busiest first), then the rest A-Z.
played = wide["player_id"].value_counts().index.tolist() if not wide.empty else []
others = [pid for pid in roster.index if pid not in played]
options = [pid for pid in played if pid in roster.index] + others
player_id = persisted_widget(
    st.selectbox, "Player", options, "player_id", options[0], format_func=option_label
)
player = roster.loc[player_id]

# --- Bio card ----------------------------------------------------------------


def height_text(inches):
    if pd.isna(inches):
        return None
    feet, rest = divmod(int(inches), 12)
    return f"{feet}'{rest}\""


def age_text(birth_date):
    if pd.isna(birth_date):
        return None
    today = date.today()
    had_birthday = (today.month, today.day) >= (birth_date.month, birth_date.day)
    return str(today.year - birth_date.year - (0 if had_birthday else 1))


def place_text(p):
    region = p["birth_state"] if pd.notna(p["birth_state"]) else p["birth_country"]
    parts = [p["birth_city"], region]
    return ", ".join(part for part in parts if pd.notna(part)) or None


def contract_text(p):
    if pd.isna(p["contract_salary"]):
        return None
    through = (
        f" through {p['contract_expires']:%Y}"
        if pd.notna(p["contract_expires"])
        else ""
    )
    return f"${float(p['contract_salary']) / 1e6:,.2f}M{through}"


bio = {
    "Position": player["position"],
    "Number": player["jersey_number"],
    "Height": height_text(player["height_inches"]),
    "Weight": f"{player['weight_lbs']:.0f} lbs"
    if pd.notna(player["weight_lbs"])
    else None,
    "Age": age_text(player["birth_date"]),
    "Experience": (
        None
        if pd.isna(player["experience_years"])
        else "Rookie"
        if player["experience_years"] == 0
        else f"{player['experience_years']} yrs"
    ),
    "Shoots": player["shoots_catches"] if league == "NHL" else None,
    "College": player["college"],
    "Born": place_text(player),
    "Salary": contract_text(player),
}
# Drop anything blank (None from Python, NaN from a NULL database value).
bio = {label: value for label, value in bio.items() if pd.notna(value) and value != ""}

with st.container(border=True):
    photo_col, info_col = st.columns([1, 5], vertical_alignment="center")
    if pd.notna(player["headshot_url"]):
        photo_col.image(player["headshot_url"], width=140)
    info_col.markdown(f"### {player['name']}")
    if pd.notna(player["injury_status"]):
        info_col.badge(
            player["injury_status"], icon=":material/healing:", color="orange"
        )
    if not player["on_roster"]:
        info_col.caption("No longer on the current roster")
    cells = info_col.columns(5)
    for i, (label, value) in enumerate(bio.items()):
        cells[i % 5].caption(label)
        cells[i % 5].markdown(f"**{value}**")

# --- Stats -------------------------------------------------------------------
player_rows = wide[wide["player_id"] == player_id] if not wide.empty else wide
if player_rows.empty:
    empty_state("No stats for this player in the selected season.")
    st.stop()

games = add_results(data.team_games(team_id)).set_index("game_id")

# Per game / Totals toggle for the season tiles. Opens on the "player"
# default in config.py; the game log below is always one row per game.
mode = (
    st.segmented_control(
        "Show",
        [stats.PER_GAME, stats.TOTALS],
        default=DEFAULT_STAT_MODE["player"],
        key="player_stat_mode",
        label_visibility="collapsed",
    )
    or DEFAULT_STAT_MODE["player"]
)

for group in STAT_GROUPS[league]:
    log = stats.per_game_table(player_rows, group)
    if log.empty:
        continue
    st.subheader(group["title"])

    # Season line as tiles: the first SEASON_TILES columns from config.py.
    # The big number follows the Per game / Totals toggle; the small line
    # under it shows the other one.
    per_game = stats.season_table(player_rows, group, stats.PER_GAME).iloc[0]
    totals = stats.season_table(player_rows, group, stats.TOTALS).iloc[0]
    tile_columns = group["columns"][:SEASON_TILES]
    tiles = st.columns(len(tile_columns) + 1)
    with tiles[0].container(border=True):
        st.metric("Games", int(totals["GP"]))
        st.caption("played")
    for tile, column in zip(tiles[1:], tile_columns, strict=True):
        label = column["label"]
        with tile.container(border=True):
            if column["kind"] == "ratio":
                # A rate is already "per attempt", so it's the same either way.
                st.metric(label, format_stat(totals[label], column))
                st.caption("season")
            elif not column["average"]:
                # Marked average=False in config.py (e.g. +/-): total only.
                st.metric(label, format_stat(totals[label], column))
                st.caption("season total")
            elif mode == stats.PER_GAME:
                st.metric(f"{label}/G", format_stat(per_game[label], column, True))
                st.caption(f"{format_stat(totals[label], column)} total")
            else:
                st.metric(label, format_stat(totals[label], column))
                st.caption(f"{format_stat(per_game[label], column, True)} per game")
    st.caption("/G = per game · rates are computed from season totals")

    # Game log, oldest to newest, with the opponent and result.
    # Look up each game's details, lined up row-for-row with the log.
    game_info = games.loc[log["game_id"]].set_index(log.index)
    log = log.assign(
        game_time=game_info["game_time"],
        Date=game_info["game_time"].map(format_date),
        Game=game_info.apply(matchup, axis=1),
        Result=game_info["result_label"],
    ).sort_values("game_time")

    chart_col, _ = st.columns([1, 2])
    numeric = [col["label"] for col in group["columns"] if col["format"] != "time"]
    label = chart_col.selectbox(
        "Chart stat",
        numeric,
        index=numeric.index(group["sort_by"]),
        key=f"chart_{group['title']}",
    )
    column = stats.find_column(group, label)
    scale = {"pct": 100, "minutes": 1 / 60}.get(column["format"], 1)
    chart_data = log.assign(
        date=log["Date"],
        matchup=log["Game"],
        game_label=log["game_time"].map(format_short_date),
    )
    chart_data[label] = chart_data[label] * scale
    # Dashed line: the season rate for ratios, the per-game average otherwise.
    if column["kind"] == "ratio":
        average = season[label] * scale
    else:
        average = chart_data[label].mean()
    average = None if pd.isna(average) else average
    whole_numbers = column["format"] == "count"
    st.altair_chart(
        charts.game_log_chart(chart_data, label, average, whole_numbers),
        width="stretch",
    )

    stat_table(
        log.iloc[::-1],  # newest game first
        group,
        lead_columns=["Date", "Game", "Result"],
        key=f"log_{group['title']}",
    )
