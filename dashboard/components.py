"""
Reusable building blocks shared by the pages in views/: formatting helpers,
the page header, W/L records, and stat tables styled from config.py.
"""

from html import escape

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


# Small stylesheet for the few pieces drawn in HTML instead of Streamlit
# widgets. They're HTML because they need to *rearrange* on a phone (e.g.
# 6 tiles in a row on a laptop, 3 per row on a phone), which st.columns
# can't do: it either keeps every column or stacks them all one per line.
DASHBOARD_CSS = """
<style>
.sh-header { display: flex; align-items: center; gap: 1rem; }
.sh-header img { width: 64px; height: 64px; object-fit: contain; flex: none; }
.sh-title { font-size: 2rem; font-weight: 700; line-height: 1.2; }
.sh-subtitle { font-size: .875rem; color: #6b6a66; }
.sh-tiles {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(var(--tile-min), 1fr));
    gap: .75rem;
    margin: .25rem 0 1rem;
}
.sh-tile {
    border: 1px solid #e6e5e1; border-radius: .6rem; background: #fff;
    padding: .75rem 1rem; min-width: 0;
}
.sh-label, .sh-note {
    font-size: .8rem; color: #6b6a66;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.sh-value {
    font-size: 1.75rem; font-weight: 600; line-height: 1.3; color: #1f1f1d;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.sh-facts {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(120px, 1fr));
    gap: .75rem 1rem;
}
.sh-fact-value { font-weight: 600; }
.sh-matchup {
    display: grid; grid-template-columns: 1fr auto 1fr; align-items: center;
    gap: 1rem; padding: 1rem 1.25rem; margin-bottom: 1rem;
    border: 1px solid #e6e5e1; border-radius: .6rem; background: #fff;
}
.sh-side { min-width: 0; }
.sh-side.home { text-align: right; }
.sh-side img { width: 56px; height: 56px; object-fit: contain; }
.sh-side-label {
    font-size: .75rem; color: #6b6a66;
    text-transform: uppercase; letter-spacing: .05em;
}
.sh-side-name { font-size: 1.1rem; font-weight: 600; line-height: 1.25; }
.sh-side-big { font-size: 2.75rem; font-weight: 700; line-height: 1.1; }
.sh-side-small { font-size: .85rem; color: #6b6a66; }
.sh-center { text-align: center; font-size: .9rem; color: #52514e; }
.sh-center-main { font-size: 1.2rem; font-weight: 600; color: #1f1f1d; }
.sh-pill {
    display: inline-block; margin-top: .35rem; padding: .1rem .5rem;
    border-radius: .4rem; font-size: .8rem;
}
/* Streamlit leaves a tall empty band above the page content; trim it. */
[data-testid="stMainBlockContainer"] { padding-top: 3.5rem; }
@media (max-width: 640px) {
    [data-testid="stMainBlockContainer"] { padding-top: 3rem; }
    .sh-matchup { gap: .5rem; padding: .75rem; }
    .sh-side img { width: 36px; height: 36px; }
    .sh-side-name { font-size: .9rem; }
    .sh-side-big { font-size: 2rem; }
    .sh-center { font-size: .75rem; }
    .sh-center-main { font-size: 1rem; }
    .sh-header img { width: 44px; height: 44px; }
    .sh-title { font-size: 1.5rem; }
    .sh-tiles { gap: .5rem; }
    .sh-tile { padding: .6rem .7rem; }
    .sh-value { font-size: 1.3rem; }
}
</style>
"""


def inject_css():
    """Add DASHBOARD_CSS to the page (called once per run from app.py)."""
    st.markdown(DASHBOARD_CSS, unsafe_allow_html=True)


def page_header(title, subtitle=None, team_name=None):
    """Page title with the team's logo and a thin brand-color accent line."""
    meta = team_meta(team_name) if team_name else None
    logo = f"<img src='{meta['logo']}' alt=''>" if meta and meta["logo"] else ""
    sub = f"<div class='sh-subtitle'>{escape(subtitle)}</div>" if subtitle else ""
    st.markdown(
        f"<div class='sh-header'>{logo}<div>"
        f"<div class='sh-title'>{escape(title)}</div>{sub}</div></div>",
        unsafe_allow_html=True,
    )
    accent = meta["color"] if meta else "#2a78d6"
    st.markdown(
        f"<div style='height:3px;background:{accent};border-radius:2px;"
        "margin:.5rem 0 1rem 0'></div>",
        unsafe_allow_html=True,
    )


# Pill colors per season type, matching the st.badge colors used elsewhere.
PILL_COLORS = {
    "preseason": ("#eceae6", "#52514e"),
    "regular": ("#e3effc", "#1f5fae"),
    "postseason": ("#ece9fb", "#4a3aa7"),
}


def matchup_card(away, home, center_lines, season_type=None):
    """
    Away team | game details | home team, side by side at every screen size.

    away/home: dicts with "name", and optionally "logo", "big" (e.g. the
        score) and "small" (e.g. the record).
    center_lines: text lines for the middle; the first one is emphasized.
    season_type: adds a Preseason / Regular season / Postseason pill.
    """

    def side(team, label, css_class):
        logo = f"<img src='{team['logo']}' alt=''>" if team.get("logo") else ""
        big = team.get("big")
        big_html = f"<div class='sh-side-big'>{escape(str(big))}</div>" if big else ""
        small = team.get("small")
        small_html = (
            f"<div class='sh-side-small'>{escape(small)}</div>" if small else ""
        )
        return (
            f"<div class='sh-side {css_class}'>{logo}"
            f"<div class='sh-side-label'>{label}</div>"
            f"<div class='sh-side-name'>{escape(team['name'])}</div>"
            f"{big_html}{small_html}</div>"
        )

    lines = [line for line in center_lines if line]
    center = "".join(
        f"<div class='sh-center-main'>{escape(line)}</div>"
        if i == 0
        else f"<div>{escape(line)}</div>"
        for i, line in enumerate(lines)
    )
    if season_type:
        background, color = PILL_COLORS[season_type]
        center += (
            f"<div class='sh-pill' style='background:{background};color:{color}'>"
            f"{SEASON_TYPE_LABELS[season_type]}</div>"
        )
    st.markdown(
        f"<div class='sh-matchup'>{side(away, 'Away', 'away')}"
        f"<div class='sh-center'>{center}</div>{side(home, 'Home', 'home')}</div>",
        unsafe_allow_html=True,
    )


def fact_grid(facts):
    """
    Label-over-value pairs (e.g. Height / 6'2") in a grid that wraps to fit
    the screen. facts: dict of {label: value}.
    """
    cells = "".join(
        f"<div><div class='sh-label'>{escape(str(label))}</div>"
        f"<div class='sh-fact-value'>{escape(str(value))}</div></div>"
        for label, value in facts.items()
    )
    st.markdown(f"<div class='sh-facts'>{cells}</div>", unsafe_allow_html=True)


def stat_tiles(tiles, min_width=100):
    """
    A row of bordered stat tiles that wraps to fit the screen.

    tiles: list of (label, value) or (label, value, note) tuples, e.g.
           [("Record", "0-2"), ("PTS/G", "0.3", "1 total")]
    min_width: narrowest a tile may get, in pixels. 100 fits 3 per row on a
           phone; use more for tiles with longer text (e.g. player names).
    """
    cells = []
    for tile in tiles:
        label, value = tile[0], tile[1]
        note = tile[2] if len(tile) > 2 else None
        note_html = f"<div class='sh-note'>{escape(str(note))}</div>" if note else ""
        cells.append(
            f"<div class='sh-tile'><div class='sh-label'>{escape(str(label))}</div>"
            f"<div class='sh-value'>{escape(str(value))}</div>{note_html}</div>"
        )
    st.markdown(
        f"<div class='sh-tiles' style='--tile-min:{min_width}px'>"
        + "".join(cells)
        + "</div>",
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
