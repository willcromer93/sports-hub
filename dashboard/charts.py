"""
Chart builders (Altair). Each function takes a DataFrame and returns a chart
for st.altair_chart(). Colors are defined once here so every chart matches.
"""

import math

import altair as alt

# One color for single-series charts; a blue/orange pair for win vs. loss
# (colorblind-safe, and deliberately not green/red).
SERIES = "#2a78d6"
WIN = "#2a78d6"
LOSS = "#eb6834"
MUTED = "#8a8985"
GRID = "#e6e5e1"


def _whole_number_axis(values):
    """
    An axis with whole-number ticks only (no "0.5 goals"). The tick values
    are listed explicitly — a tickMinStep setting gets lost when charts are
    layered (e.g. bars + an average line).
    """
    top = max(1, math.ceil(max((v for v in values if v == v), default=1)))
    step = max(1, math.ceil(top / 5))
    return alt.Axis(values=list(range(0, top + step, step)), format="d")


def _style(chart, height):
    """Shared look: quiet axes and gridlines so the data carries the color."""
    return (
        chart.properties(height=height)
        .configure_view(strokeWidth=0)
        .configure_axis(
            labelColor="#52514e",
            titleColor="#52514e",
            gridColor=GRID,
            domainColor=GRID,
            tickColor=GRID,
            labelFontSize=12,
            titleFontSize=12,
            titleFontWeight="normal",
        )
        .configure_legend(labelColor="#52514e", titleColor="#52514e", orient="top")
    )


def margin_chart(games):
    """
    Scoring margin per finished game — bars up for wins, down for losses.
    Expects columns: game_label, margin, result, matchup, result_label, date.
    """
    base = alt.Chart(games).encode(
        x=alt.X("game_label:N", sort=None, title=None, axis=alt.Axis(labelAngle=0)),
    )
    bars = base.mark_bar(cornerRadiusEnd=4, size=18).encode(
        y=alt.Y("margin:Q", title="Margin"),
        color=alt.Color(
            "result:N",
            scale=alt.Scale(domain=["W", "L", "T"], range=[WIN, LOSS, MUTED]),
            legend=alt.Legend(title=None),
        ),
        tooltip=[
            alt.Tooltip("date:N", title="Date"),
            alt.Tooltip("matchup:N", title="Game"),
            alt.Tooltip("result_label:N", title="Result"),
        ],
    )
    zero = alt.Chart().mark_rule(color=MUTED).encode(y=alt.datum(0))
    return _style(alt.layer(bars, zero, data=games), height=220)


def game_log_chart(log, label, average, whole_numbers=False):
    """
    One stat across a player's games, with a dashed line at their average.
    Expects columns: game_label, <label>, matchup, date.
    """
    axis = _whole_number_axis(log[label]) if whole_numbers else alt.Axis()
    bars = (
        alt.Chart(log)
        .mark_bar(cornerRadiusEnd=4, size=18, color=SERIES)
        .encode(
            x=alt.X("game_label:N", sort=None, title=None, axis=alt.Axis(labelAngle=0)),
            y=alt.Y(f"{label}:Q", title=label, axis=axis),
            tooltip=[
                alt.Tooltip("date:N", title="Date"),
                alt.Tooltip("matchup:N", title="Game"),
                alt.Tooltip(f"{label}:Q", title=label, format=",.1f"),
            ],
        )
    )
    layers = [bars]
    if average is not None:
        layers.append(
            alt.Chart()
            .mark_rule(color=MUTED, strokeDash=[4, 4])
            .encode(y=alt.datum(average))
        )
    return _style(alt.layer(*layers, data=log), height=240)


def leaders_chart(table, label, value_format=",.1f"):
    """
    Horizontal bars for the top players in one stat, biggest at the top.
    Expects columns: Player, <label>.
    """
    # Whole-number stats (goals, yards) get whole-number axis ticks.
    whole_numbers = value_format.endswith("0f")
    axis = _whole_number_axis(table[label]) if whole_numbers else alt.Axis()
    base = alt.Chart(table).encode(
        y=alt.Y("Player:N", sort="-x", title=None),
        x=alt.X(f"{label}:Q", title=label, axis=axis),
    )
    bars = base.mark_bar(cornerRadiusEnd=4, size=16, color=SERIES).encode(
        tooltip=[
            alt.Tooltip("Player:N"),
            alt.Tooltip(f"{label}:Q", title=label, format=value_format),
        ]
    )
    values = base.mark_text(align="left", dx=4, color="#52514e").encode(
        text=alt.Text(f"{label}:Q", format=value_format)
    )
    return _style(bars + values, height=max(120, 30 * len(table)))
