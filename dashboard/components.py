"""
Reusable building blocks shared by the pages in views/: formatting helpers,
the page header, W/L records, and stat tables styled from config.py.
"""

import pandas as pd
import streamlit as st

from config import DISPLAY_TIMEZONE, TEAMS
from stats import is_averaged

SEASON_TYPE_LABELS = {
    "preseason": "Preseason",
    "regular": "Regular season",
    "postseason": "Postseason",
}

# Badge color per season type (Streamlit's built-in badge colors). Preseason
# is grey on purpose: those games don't count, so they should look quieter.
SEASON_TYPE_COLORS = {
    "preseason": "gray",
    "regular": "blue",
    "postseason": "violet",
}


def season_type_badge(season_type):
    """Markdown for a colored pill like "Preseason", for use in st.markdown()."""
    color = SEASON_TYPE_COLORS[season_type]
    return f":{color}-badge[{SEASON_TYPE_LABELS[season_type]}]"


def season_type_note(season_type):
    """Text for tables: flags preseason/postseason, blank for regular season."""
    return "" if season_type == "regular" else SEASON_TYPE_LABELS[season_type]


# ---------------------------------------------------------------------------
# Small formatting helpers
# ---------------------------------------------------------------------------


def team_meta(name):
    """Config details for a tracked team, with safe fallbacks for opponents."""
    return TEAMS.get(name, {"short": name, "color": "#52514e", "logo": None})


def season_label(league, season_year):
    """ESPN's season_year -> how fans say it: NBA 2027 -> '2026-27', NFL 2026 -> '2026'."""
    if league == "NFL":
        return str(season_year)
    return f"{season_year - 1}-{str(season_year)[2:]}"


def local_time(ts):
    return pd.Timestamp(ts).tz_convert(DISPLAY_TIMEZONE)


def format_date(ts):
    return local_time(ts).strftime("%a, %b %-d")


def format_datetime(ts):
    return local_time(ts).strftime("%a, %b %-d · %-I:%M %p")


def format_short_date(ts):
    return local_time(ts).strftime("%b %-d")


def format_short_datetime(ts):
    return local_time(ts).strftime("%b %-d, %-I:%M %p")


def format_seconds(seconds):
    """Seconds -> 'MM:SS' (zero-padded so the column still sorts correctly)."""
    if pd.isna(seconds):
        return None
    minutes, secs = divmod(round(seconds), 60)
    return f"{minutes:02d}:{secs:02d}"


def format_stat(value, column, averaged=False):
    """One stat value as text, using the column's fmt from config.py."""
    if pd.isna(value):
        return "—"
    fmt = column["format"]
    if fmt == "pct":
        return f"{value * 100:.1f}%"
    if fmt == "time":
        return format_seconds(value)
    if fmt == "minutes":
        value = value / 60
    if fmt == "decimal" or averaged:
        return f"{value:.1f}"
    return f"{value:,.0f}"


def matchup(row):
    """'vs Ravens' at home (or neutral site), '@ Chiefs' on the road."""
    return f"{'vs' if row['is_home'] else '@'} {row['opponent']}"


# ---------------------------------------------------------------------------
# Results and records
# ---------------------------------------------------------------------------


def add_results(games):
    """
    Add result columns to team_games() output:
      result       'W' / 'L' / 'T' (blank until final)
      result_label 'W 41–23', 'L 30–33 OT'
    """
    games = games.copy()
    final = games["status"] == "final"
    games["result"] = ""
    games.loc[final & (games["team_score"] > games["opp_score"]), "result"] = "W"
    games.loc[final & (games["team_score"] < games["opp_score"]), "result"] = "L"
    games.loc[final & (games["team_score"] == games["opp_score"]), "result"] = "T"

    def label(row):
        if row["status"] != "final":
            return ""
        suffix = " SO" if row["shootout"] else " OT" if row["extra_time"] else ""
        return f"{row['result']} {row['team_score']:.0f}–{row['opp_score']:.0f}{suffix}"

    games["result_label"] = games.apply(label, axis=1)
    return games


def record(games, league):
    """
    W-L record for a set of finished games. NHL uses W-L-OTL (an overtime or
    shootout loss is its own column); the NFL adds ties only if there are any.
    """
    final = games[games["status"] == "final"]
    wins = (final["result"] == "W").sum()
    if league == "NHL":
        losses = ((final["result"] == "L") & ~final["extra_time"]).sum()
        ot_losses = ((final["result"] == "L") & final["extra_time"]).sum()
        return f"{wins}-{losses}-{ot_losses}"
    losses = (final["result"] == "L").sum()
    ties = (final["result"] == "T").sum()
    return f"{wins}-{losses}" + (f"-{ties}" if ties else "")


# ---------------------------------------------------------------------------
# Layout pieces
# ---------------------------------------------------------------------------


def page_header(title, subtitle=None, team_name=None):
    """Page title with the team's logo and a thin brand-color accent line."""
    meta = team_meta(team_name) if team_name else None
    if meta and meta["logo"]:
        logo_col, text_col = st.columns([1, 11], vertical_alignment="center")
        logo_col.image(meta["logo"], width=64)
    else:
        text_col = st.container()
    text_col.markdown(f"## {title}")
    if subtitle:
        text_col.caption(subtitle)
    accent = meta["color"] if meta else "#2a78d6"
    st.markdown(
        f"<div style='height:3px;background:{accent};border-radius:2px;"
        "margin:0 0 1rem 0'></div>",
        unsafe_allow_html=True,
    )


def empty_state(message):
    st.info(message, icon=":material/info:")


def persisted_widget(widget, label, options, state_key, default, **kwargs):
    """
    Draw a widget whose value survives switching pages.

    Streamlit forgets a widget's value when a page doesn't draw it, so the
    real value is kept in st.session_state[state_key]. Each run, it works out
    who changed the value last:
      - the user clicked the widget -> save the widget's value
      - other code set state_key (e.g. a "Team page" button) -> show that
    "_synced_<key>" remembers the value both agreed on at the end of last run.
    """
    widget_key = f"_{state_key}"
    synced_key = f"_synced_{state_key}"
    state = st.session_state

    user_changed = (
        widget_key in state
        and state[widget_key] != state.get(synced_key)
        and state[widget_key] in options
    )
    if user_changed:
        state[state_key] = state[widget_key]
    if state.get(state_key) not in options:
        state[state_key] = default

    state[widget_key] = state[state_key]
    widget(label, options, key=widget_key, **kwargs)
    state[synced_key] = state[state_key]
    return state[state_key]


# ---------------------------------------------------------------------------
# Stat tables
# ---------------------------------------------------------------------------


def _display_values(table, group):
    """Convert raw values into display units (seconds -> minutes/MM:SS, ratio -> %)."""
    table = table.copy()
    for col in group["columns"]:
        label = col["label"]
        if label not in table.columns:
            continue
        if col["format"] == "minutes":
            table[label] = table[label] / 60
        elif col["format"] == "time":
            table[label] = table[label].map(format_seconds)
        elif col["format"] == "pct":
            table[label] = table[label] * 100
    return table


def stat_header(column, mode):
    """A column's display name: "PTS/G" when it's a per-game average."""
    if is_averaged(column, mode):
        return f"{column['label']}/G"
    return column["label"]


def _column_config(group, mode):
    """
    Header labels and number formats for each column, driven by config.py.
    In per-game mode, averaged columns are relabelled "PTS/G" so an average
    is never mistaken for a total. Rates (FG%) keep their name either way.
    """
    config = {"GP": st.column_config.NumberColumn("GP", format="%d")}
    for col in group["columns"]:
        label, fmt = col["label"], col["format"]
        header = stat_header(col, mode)
        if fmt == "time":
            config[label] = st.column_config.TextColumn(header)
            continue
        if fmt == "pct":
            number_format = "%.1f%%"
        elif fmt == "decimal" or is_averaged(col, mode):
            number_format = "%.1f"
        else:
            number_format = "%d"
        config[label] = st.column_config.NumberColumn(header, format=number_format)
    return config


def stat_table(table, group, mode=None, lead_columns=(), extra_config=None, **kwargs):
    """
    Render a stats table as an interactive st.dataframe.

    lead_columns: columns to show first (e.g. "Player", or "Date"/"Opponent").
    mode: PER_GAME / TOTALS for season tables; None for single-game rows.
    Extra keyword arguments pass straight through to st.dataframe (e.g. key=).
    """
    stat_labels = [col["label"] for col in group["columns"]]
    # Skip a label column that's entirely blank (e.g. Pos for opponents,
    # since ESPN box scores don't include positions).
    lead_columns = [col for col in lead_columns if table[col].notna().any()]
    ordered = lead_columns + (["GP"] if "GP" in table.columns else [])
    ordered += stat_labels
    config = _column_config(group, mode)
    config.update(extra_config or {})
    return st.dataframe(
        _display_values(table, group)[ordered],
        column_config=config,
        hide_index=True,
        width="stretch",
        placeholder="—",  # blank cells (e.g. FO% with no faceoffs) show a dash
        **kwargs,
    )
