"""Team — record, results, and player stats for the team/season in the sidebar."""

import streamlit as st

import charts
import data
import stats
from components import (
    add_results,
    empty_state,
    format_date,
    format_datetime,
    format_short_date,
    format_stat,
    matchup,
    page_header,
    record,
    season_label,
    season_type_badge,
    stat_header,
    stat_table,
)
from config import DEFAULT_STAT_MODE, HEADLINE_STATS, STAT_GROUPS

LEADERS_TOP_N = 10

team_name = st.session_state["team"]
team_id = st.session_state["team_id"]
league = st.session_state["league"]
season_year = st.session_state.get("season_year")
season_type = st.session_state.get("season_type")

team = data.tracked_teams().set_index("name").loc[team_name]
details = " · ".join(
    str(part)
    for part in [team["venue"], team["city"], f"Est. {team['founded_year']}"]
    if part
)
page_header(team_name, details, team_name=team_name)

if season_year is None:
    empty_state("No games loaded for this team yet.")
    st.stop()

games = add_results(data.team_games(team_id))
games = games[
    (games["season_year"] == season_year) & (games["season_type"] == season_type)
]
finals = games[games["status"] == "final"]
st.markdown(
    f"**{season_label(league, season_year)}** &nbsp; {season_type_badge(season_type)}"
)

# --- Headline numbers --------------------------------------------------------
scoring_word = {"NHL": "Goals"}.get(league, "Points")
tiles = st.columns(6)
tiles[0].metric("Record", record(finals, league), border=True)
tiles[1].metric("Home", record(finals[finals["is_home"]], league), border=True)
tiles[2].metric("Away", record(finals[~finals["is_home"]], league), border=True)
last5 = finals.tail(5)["result"]
tiles[3].metric("Last 5", "-".join(last5) if not last5.empty else "—", border=True)
avg_for = f"{finals['team_score'].mean():.1f}" if not finals.empty else "—"
avg_against = f"{finals['opp_score'].mean():.1f}" if not finals.empty else "—"
tiles[4].metric(f"{scoring_word} for (avg)", avg_for, border=True)
tiles[5].metric(f"{scoring_word} against (avg)", avg_against, border=True)

results_tab, stats_tab, leaders_tab = st.tabs(["Results", "Player stats", "Leaders"])

# --- Results -----------------------------------------------------------------
with results_tab:
    if not finals.empty:
        chart_data = finals.assign(
            margin=finals["team_score"] - finals["opp_score"],
            date=finals["game_time"].map(format_date),
            game_label=finals["game_time"].map(format_short_date),
            matchup=finals.apply(matchup, axis=1),
        )
        st.altair_chart(charts.margin_chart(chart_data), width="stretch")

    is_final = games["status"] == "final"
    schedule = games.assign(
        Date=games["game_time"]
        .map(format_date)
        .where(is_final, games["game_time"].map(format_datetime)),
        Game=games.apply(matchup, axis=1),
        # Finished games show the score; postponed/canceled games say so.
        Result=games["result_label"].where(
            is_final,
            games["status"].str.title().where(games["status"] != "scheduled", ""),
        ),
        Venue=games["venue_name"],
    )
    st.caption("Select a finished game to open its box score.")
    event = st.dataframe(
        schedule[["Date", "Game", "Result", "Venue"]],
        hide_index=True,
        width="stretch",
        on_select="rerun",
        selection_mode="single-row",
        key="schedule_table",
    )
    if event.selection.rows:
        picked = schedule.iloc[event.selection.rows[0]]
        if picked["has_box_score"]:
            st.session_state["game_id"] = int(picked["game_id"])
            st.switch_page("views/game.py")
        else:
            st.toast("No box score for that game yet.")

# --- Player stats ------------------------------------------------------------
wide = stats.pivot_stats(data.player_stat_rows(team_id, season_year, season_type))
names = data.players(team_id).set_index("player_id")["name"]
groups = STAT_GROUPS[league]

with stats_tab:
    if wide.empty:
        empty_state("No box scores for this season yet.")
    else:
        mode = (
            st.segmented_control(
                "Show",
                [stats.PER_GAME, stats.TOTALS],
                default=DEFAULT_STAT_MODE["team"],
                key="team_stat_mode",
                label_visibility="collapsed",
            )
            or DEFAULT_STAT_MODE["team"]
        )
        st.caption("Select a player to open their page.")
        for group in groups:
            table = stats.season_table(wide, group, mode)
            if table.empty:
                continue
            table = stats.sort_group_table(table, group)
            table.insert(0, "Player", table["player_id"].map(names))
            st.subheader(group["title"])
            event = stat_table(
                table,
                group,
                mode,
                lead_columns=["Player"],
                on_select="rerun",
                selection_mode="single-row",
                key=f"stats_{group['title']}",
            )
            if event.selection.rows:
                picked = table.iloc[event.selection.rows[0]]
                st.session_state["player_id"] = int(picked["player_id"])
                st.switch_page("views/player.py")

# --- Leaders -----------------------------------------------------------------
with leaders_tab:
    if wide.empty:
        empty_state("No box scores for this season yet.")
    else:
        mode = st.session_state.get("team_stat_mode") or DEFAULT_STAT_MODE["team"]
        groups_by_title = {group["title"]: group for group in groups}
        tables = {
            title: stats.season_table(wide, group, mode)
            for title, group in groups_by_title.items()
        }

        tiles = st.columns(len(HEADLINE_STATS[league]))
        for tile, (title, label) in zip(tiles, HEADLINE_STATS[league], strict=True):
            group = groups_by_title[title]
            top = stats.leader(tables[title], group, label, mode, len(finals))
            column = stats.find_column(group, label)
            with tile.container(border=True):
                st.caption(f"{title} · {stat_header(column, mode)}")
                if top is None:
                    st.markdown("**—**")
                    continue
                shown = format_stat(top[label], column, stats.is_averaged(column, mode))
                st.markdown(f"### {shown}")
                st.markdown(names.get(top["player_id"], "Unknown"))

        st.caption(
            f"{mode} · averages and rates need "
            "at least half the team's games to qualify for leader tiles."
        )

        pick_group, pick_stat = st.columns(2)
        title = pick_group.selectbox(
            "Table", [t for t in groups_by_title if not tables[t].empty]
        )
        group = groups_by_title[title]
        numeric = [col["label"] for col in group["columns"] if col["format"] != "time"]
        label = pick_stat.selectbox(
            "Stat", numeric, index=numeric.index(group["sort_by"])
        )

        column = stats.find_column(group, label)
        top = tables[title].dropna(subset=[label]).nlargest(LEADERS_TOP_N, label)
        top = top.assign(Player=top["player_id"].map(names))
        if column["format"] == "pct":
            top[label] = top[label] * 100
        elif column["format"] == "minutes":
            top[label] = top[label] / 60
        fmt = (
            ",.1f"
            if stats.is_averaged(column, mode) or column["kind"] == "ratio"
            else ",.0f"
        )
        header = stat_header(column, mode)
        top = top.rename(columns={label: header})
        st.altair_chart(charts.leaders_chart(top, header, fmt), width="stretch")
