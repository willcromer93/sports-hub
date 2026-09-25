"""
Turns long-format stat rows (one row per player/game/stat) into the tables
described by STAT_GROUPS in config.py. No SQL and no Streamlit here — just
pandas — so this is the place to look if a number on screen looks wrong.
"""

import pandas as pd

from config import LEADER_MIN_GAMES_SHARE

PER_GAME = "Per game"
TOTALS = "Totals"


def is_averaged(column, mode):
    """
    Does this column show a per-game average in this mode? Only counting
    stats in per-game mode, and never one marked average=False in config.py.
    """
    return mode == PER_GAME and column["kind"] == "stat" and column["average"]


def pivot_stats(long_rows):
    """
    Long rows -> one row per (game_id, player_id) with a column per stat.
    This "pivot" is the pandas version of a SQL crosstab.
    """
    # team_id (which side the player was on) rides along when present.
    index = [col for col in ["game_id", "player_id", "team_id"] if col in long_rows]
    if long_rows.empty:
        return pd.DataFrame(columns=index)
    wide = long_rows.pivot_table(
        index=index,
        columns="stat_name",
        values="value",
        aggfunc="sum",
    )
    wide.columns.name = None
    return wide.reset_index()


def _sum_keys(frame, keys):
    """Add up several stat columns row by row. Missing stats count as blank."""
    present = [key for key in keys if key in frame.columns]
    if not present:
        return pd.Series(float("nan"), index=frame.index)
    return frame[present].sum(axis=1, min_count=1)


def _rows_for_group(wide, group):
    """Only the player-games where the group's `requires` stat was recorded."""
    if group["requires"] not in wide.columns:
        return wide.iloc[0:0]
    return wide[wide[group["requires"]].notna()]


def per_game_table(wide, group):
    """
    One row per player-game, with the group's columns — used for single-game
    box scores and player game logs. Keeps game_id/player_id for joining.
    """
    rows = _rows_for_group(wide, group)
    id_columns = [col for col in ["game_id", "player_id", "team_id"] if col in rows]
    table = rows[id_columns].copy()
    for col in group["columns"]:
        if col["kind"] == "stat":
            table[col["label"]] = _sum_keys(rows, col["keys"])
        else:
            made = _sum_keys(rows, col["made"])
            attempted = _sum_keys(rows, col["attempted"])
            table[col["label"]] = made / attempted.where(attempted > 0)
    return table


def season_table(wide, group, mode):
    """
    One row per player for a whole season: totals or per-game averages for
    counting stats, and rates recomputed from summed totals.
    """
    rows = _rows_for_group(wide, group)
    grouped = rows.groupby("player_id")
    table = pd.DataFrame({"GP": grouped.size()})
    for col in group["columns"]:
        if col["kind"] == "stat":
            total = (
                _sum_keys(rows, col["keys"]).groupby(rows["player_id"]).sum(min_count=1)
            )
            table[col["label"]] = (
                total / table["GP"] if is_averaged(col, mode) else total
            )
        else:
            made = _sum_keys(rows, col["made"]).groupby(rows["player_id"]).sum()
            attempted = (
                _sum_keys(rows, col["attempted"]).groupby(rows["player_id"]).sum()
            )
            table[col["label"]] = made / attempted.where(attempted > 0)
    return table.reset_index()


def sort_group_table(table, group):
    return table.sort_values(group["sort_by"], ascending=False, na_position="last")


def find_column(group, label):
    return next(col for col in group["columns"] if col["label"] == label)


def leader(table, group, label, mode, team_games_played):
    """
    The player leading `table` in column `label`, or None. Averages and rates
    only count players who've played LEADER_MIN_GAMES_SHARE of team games.
    """
    col = find_column(group, label)
    candidates = table.dropna(subset=[label])
    if col["kind"] == "ratio" or is_averaged(col, mode):
        candidates = candidates[
            candidates["GP"] >= team_games_played * LEADER_MIN_GAMES_SHARE
        ]
    if candidates.empty:
        return None
    return candidates.loc[candidates[label].idxmax()]
