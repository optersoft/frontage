"""Streamlit's Seattle Weather demo, ported to frontage: the same dashboard, no server.

The original (github.com/streamlit/demo-seattle-weather) is a script Streamlit re-runs from
the top on every interaction, on a machine somewhere, with pandas slicing the frame and Altair
rendering the charts. This is the same page as a reactive graph in the browser: the year pills
write one signal, six memos recompute the slices that read it, and only the nodes those memos
feed are touched. The eight summary metrics never recompute, because nothing they read moved.

Two of the charts are a JavaScript library — uPlot, wrapped as a component in `plot.py` and
`chartlib.js`, because 1,464 daily points per year want a canvas. The other three are divs and
a `conic-gradient`, built by `For` out of numbers Python already has. Both are the same
framework; the choice is only about how many points there are.

The dataset ships in `data.py`, so the page fetches nothing at all.
"""

import data
from plot import chart

from frontage import For, Memo, Show, Signal, h, mount

# --- the palette ---------------------------------------------------------------------------

YEAR_COLOR = ("#b3541e", "#1f7a8c", "#5c6f3c", "#7d4a8b")
WEATHER_COLOR = {
    "sun": "#e8a33d",
    "drizzle": "#8fb8d6",
    "fog": "#a3aab0",
    "rain": "#3f6d9e",
    "snow": "#cfd9e4",
}
WEATHER_ICON = {"sun": "☀", "drizzle": "🌧", "fog": "🌫", "rain": "💧", "snow": "❄"}
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
DAYS = list(range(1, 367))  # a shared x axis, so every year lines up day for day


def color_of(year):
    return YEAR_COLOR[data.YEARS.index(year) % len(YEAR_COLOR)]


# --- the 2015 summary ----------------------------------------------------------------------
#
# Computed once, at import: it reads the whole dataset and no signal, so it is not a memo and
# never recomputes. That is the part a re-run-the-script framework cannot express.

LATEST, PREVIOUS = data.YEARS[-1], data.YEARS[-2]


def extremes(year, column):
    values = [row[column] for row in data.ROWS if row["year"] == year]
    return min(values), max(values)


def counted():
    """Every weather kind and how often it happened, commonest first."""
    counts = {}
    for row in data.ROWS:
        counts[row["weather"]] = counts.get(row["weather"], 0) + 1
    # A dict does not keep its order on MicroPython, so the order is made here, not assumed.
    return sorted(counts.items(), key=lambda pair: -pair[1])


def metric(label, value, delta=None, unit=""):
    """One summary tile: a number, and how far it moved since the year before."""
    tile = [h.div(label, cls="metric-label"), h.div(value, cls="metric-value")]
    if delta is not None:
        arrow = "▲" if delta >= 0 else "▼"
        tile.append(h.div(f"{arrow} {abs(delta):.1f}{unit}", cls="metric-delta " + ("up" if delta >= 0 else "down")))
    return h.div(*tile, cls="metric")


def summary():
    tiles = []
    for label, column, unit in (
        ("temperature", "temp_max", "C"),
        ("precipitation", "precipitation", " mm"),
        ("wind", "wind", " m/s"),
    ):
        low, high = extremes(LATEST, column)
        was_low, was_high = extremes(PREVIOUS, column)
        tiles.append(metric(f"Max {label}", f"{high:.1f}{unit}", high - was_high, unit))
        tiles.append(metric(f"Min {label}", f"{low:.1f}{unit}", low - was_low, unit))
    kinds = counted()
    for label, name in (("Most common weather", kinds[0][0]), ("Least common weather", kinds[-1][0])):
        tiles.append(metric(label, f"{WEATHER_ICON[name]} {name.upper()}"))
    return h.div(*tiles, cls="metrics")


# --- the selection -------------------------------------------------------------------------

selected = Signal(list(data.YEARS))
rows = Memo(lambda: [row for row in data.ROWS if row["year"] in selected()])


def toggle(year):
    def click(ev):
        chosen = [y for y in selected() if y != year]
        if len(chosen) == len(selected()):
            chosen.append(year)
            chosen.sort()
        selected.set(chosen)

    return click


def pills():
    return h.div(
        For(
            lambda: data.YEARS,
            lambda year, index: h.button(
                str(year),
                cls="pill",
                type="button",
                on_click=toggle(year),
                style_border_color=lambda: color_of(year) if year in selected() else "",
                class_on=lambda: year in selected(),
            ),
        ),
        cls="pills",
    )


# --- the two canvas charts -----------------------------------------------------------------


def by_day(year, column):
    """One year's column, indexed by day-of-year, so the shared x axis can be filled."""
    return {row["day"]: row[column] for row in data.ROWS if row["year"] == year}


def temperature_series():
    """x, then a high and a low column per selected year: uPlot bands the pairs."""
    columns = [DAYS]
    for year in selected():
        high, low = by_day(year, "temp_max"), by_day(year, "temp_min")
        columns.append([high.get(day) for day in DAYS])
        columns.append([low.get(day) for day in DAYS])
    return columns


def temperature_options():
    years = selected()
    return {
        "labels": [f"{year} {half}" for year in years for half in ("high", "low")],
        "colors": [color_of(year) for year in years for _ in (0, 1)],
        "bands": [[i * 2 + 1, i * 2 + 2] for i in range(len(years))],
    }


def wind_series():
    """The two-week rolling mean the original computes with a window transform."""
    columns = [DAYS]
    for year in selected():
        speeds = by_day(year, "wind")
        column = []
        for day in DAYS:
            window = [speeds[k] for k in range(day, day + 14) if k in speeds]
            column.append(sum(window) / len(window) if window else None)
        columns.append(column)
    return columns


# --- the three charts made of divs ---------------------------------------------------------


def monthly(column):
    """`column` summed per (year, month), in one pass over the selected rows."""
    totals = {}
    for row in rows():
        key = (row["year"], row["month"])
        totals[key] = totals.get(key, 0.0) + row[column]
    return totals


def precipitation_months():
    totals = monthly("precipitation")
    peak = max(totals.values()) if totals else 1.0
    return [
        {
            "month": month,
            "bars": [
                (year, totals.get((year, month), 0.0), totals.get((year, month), 0.0) / peak * 100)
                for year in selected()
            ],
        }
        for month in range(1, 13)
    ]


def distribution():
    """How often each weather kind happened in the selected years."""
    counts = {}
    for row in rows():
        counts[row["weather"]] = counts.get(row["weather"], 0) + 1
    total = sum(counts.values()) or 1
    return [(name, counts[name], counts[name] / total * 100) for name in data.WEATHER if name in counts]


def donut():
    """The pie the original draws with `mark_arc()`, as one CSS gradient."""
    stops, at = [], 0.0
    for name, _, share in distribution():
        stops.append(f"{WEATHER_COLOR[name]} {at:.2f}% {at + share:.2f}%")
        at += share
    return "conic-gradient(" + ", ".join(stops) + ")" if stops else "none"


def breakdown():
    """Each month's days by weather kind, normalised — the original's stacked bar."""
    counts = {}
    for row in rows():
        key = (row["month"], row["weather"])
        counts[key] = counts.get(key, 0) + 1
    months = []
    for month in range(1, 13):
        total = sum(counts.get((month, name), 0) for name in data.WEATHER) or 1
        months.append(
            {
                "month": month,
                "parts": [
                    (name, counts.get((month, name), 0) / total * 100)
                    for name in data.WEATHER
                    if counts.get((month, name), 0)
                ],
            }
        )
    return months


# --- the view ------------------------------------------------------------------------------

precipitation = Memo(precipitation_months)
weather_share = Memo(distribution)
monthly_weather = Memo(breakdown)


def card(title, *body, **attrs):
    return h.section(h.h3(title), *body, cls="card", **attrs)


def precipitation_chart():
    return card(
        "Precipitation",
        h.div(
            For(
                precipitation,
                lambda month, index: h.div(
                    h.div(
                        For(
                            lambda: month()["bars"],
                            lambda bar, i: h.div(
                                cls="bar",
                                title=lambda: f"{bar()[0]}: {bar()[1]:.0f} mm",
                                style_height=lambda: f"{bar()[2]:.1f}%",
                                style_background=lambda: color_of(bar()[0]),
                            ),
                            key=False,
                        ),
                        cls="bar-group",
                    ),
                    h.div(lambda: MONTHS[month()["month"] - 1], cls="bar-label"),
                    cls="bar-column",
                ),
                key=False,
            ),
            cls="bars",
        ),
        h.p("monthly total, mm", cls="axis-note"),
        id="precipitation",
    )


def distribution_chart():
    return card(
        "Weather distribution",
        h.div(h.div(cls="donut-hole"), cls="donut", style_background=donut),
        h.ul(
            For(
                weather_share,
                lambda share, index: h.li(
                    h.span(cls="swatch", style_background=lambda: WEATHER_COLOR[share()[0]]),
                    lambda: f"{share()[0]} ",
                    h.b(lambda: f"{share()[2]:.0f}%"),
                ),
                key=False,
            ),
            cls="legend",
        ),
        id="distribution",
    )


def breakdown_chart():
    return card(
        "Monthly weather breakdown",
        h.div(
            For(
                monthly_weather,
                lambda month, index: h.div(
                    h.div(lambda: MONTHS[month()["month"] - 1], cls="stack-label"),
                    h.div(
                        For(
                            lambda: month()["parts"],
                            lambda part, i: h.div(
                                cls="segment",
                                title=lambda: f"{part()[0]}: {part()[1]:.0f}%",
                                style_width=lambda: f"{part()[1]:.2f}%",
                                style_background=lambda: WEATHER_COLOR[part()[0]],
                            ),
                            key=False,
                        ),
                        cls="stack",
                    ),
                    cls="stack-row",
                ),
                key=False,
            ),
            cls="stacks",
        ),
        id="breakdown",
    )


SHOWN = 100  # the raw table is a sample; the whole frame is what the charts above read


def raw_table():
    return card(
        "Raw data",
        h.div(
            h.table(
                h.thead(h.tr(*[h.th(name) for name in ("date", "precip.", "max", "min", "wind", "weather")])),
                h.tbody(
                    For(
                        lambda: rows()[:SHOWN],
                        lambda row, index: h.tr(
                            h.td(row["date"]),
                            h.td(f"{row['precipitation']:.1f}"),
                            h.td(f"{row['temp_max']:.1f}"),
                            h.td(f"{row['temp_min']:.1f}"),
                            h.td(f"{row['wind']:.1f}"),
                            h.td(row["weather"]),
                        ),
                        key="date",
                    )
                ),
            ),
            cls="table-scroll",
        ),
        h.p(lambda: f"first {min(SHOWN, len(rows()))} of {len(rows())} rows", cls="axis-note", id="row-count"),
        id="raw",
    )


def page():
    return h.div(
        h.header(
            h.h1("Seattle Weather"),
            h.p(
                "The classic Seattle weather dataset, four years of it, plotted in Python in "
                "your browser. Nothing here is fetched and no server is asked anything.",
            ),
        ),
        h.h2(f"{LATEST} summary"),
        summary(),
        h.h2("Compare different years"),
        pills(),
        Show(
            lambda: len(selected()) > 0,
            lambda: h.div(
                h.div(
                    card(
                        "Temperature",
                        chart(temperature_series, temperature_options, height=280, format="day", legend=False),
                        h.p("daily range, C", cls="axis-note"),
                        id="temperature",
                    ),
                    distribution_chart(),
                    cls="row wide-left",
                ),
                h.div(
                    card(
                        "Wind",
                        chart(
                            wind_series,
                            lambda: {
                                "labels": [str(year) for year in selected()],
                                "colors": [color_of(year) for year in selected()],
                            },
                            height=220,
                            format="day",
                            legend=False,
                        ),
                        h.p("average of the next two weeks, m/s", cls="axis-note"),
                        id="wind",
                    ),
                    precipitation_chart(),
                    cls="row",
                ),
                h.div(breakdown_chart(), raw_table(), cls="row"),
                cls="charts",
            ),
            fallback=h.p("Select at least one year.", cls="warning", id="empty"),
        ),
        h.footer(
            "A port of ",
            h.a("Streamlit's Seattle Weather demo", href="https://github.com/streamlit/demo-seattle-weather"),
            ". Built with ",
            h.a("frontage", href="https://github.com/optersoft/frontage"),
            ".",
        ),
        cls="page",
    )


mount(page, "#app")
