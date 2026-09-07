"""Half a million taxi trips that never leave the server.

The page holds one signal, the borough, and asks the server four questions about it: a
summary, a daily series, an hourly histogram and a window of rows. Each answer is a few
kilobytes; the 500,000-row frame stays in polars. Change the borough and four requests go
out, four answers come back, and the metrics, the two charts and the grid update in place.
Scroll the grid and it asks for the next block; sort or search and the server does it.

When the server appends trips (`POST /demo/append`) it says so on the event stream, and every
query on this page refetches — no timer, no re-run.

Run it: `uvicorn server:app --app-dir examples/trips` after `frontage build examples/trips`.
"""

from frontage import Loading, Signal, h, mount
from frontage.widgets import select, text_input
from frontage_chart import bar_chart, line_chart
from frontage_layout import columns, metric, spinner
from frontage_polars import remote
from frontage_table import table

api = remote("/api")

borough = Signal("all")
search = Signal("")

summary = api.query("summary", borough=borough)
daily = api.query("daily", borough=borough)
hourly = api.query("by_hour", borough=borough)

BOROUGHS = [("all", "All boroughs"), "Manhattan", "Brooklyn", "Queens", "Bronx", "Staten Island"]
COLUMNS = [
    ("id", "#"),
    ("date", "Date"),
    ("hour", "Hour"),
    ("borough", "Borough"),
    ("distance_km", "km", ".1f"),
    ("fare", "Fare", ".2f"),
    ("passengers", "Pax"),
]


def number(name, spec=None):
    """A metric's text. MicroPython formats an int with `,` but ignores it on a float, so a
    whole number is rounded to an int first."""
    if spec is None:
        return lambda: "{:,}".format(int(round(summary()[name][0])))
    return lambda: ("{:" + spec + "}").format(summary()[name][0])


def app():
    return h.div(
        h.h1("Trips"),
        h.p("500,000 rows in polars on the server. The page has the answers, not the data.", cls="lede"),
        h.div(
            select(borough, BOROUGHS, label="Borough", id="borough"),
            text_input(search, label="Search the trips", id="search", placeholder="e.g. Queens"),
            cls="toolbar",
        ),
        Loading(
            spinner("Asking the server…"),
            lambda: columns(
                metric("Trips", number("trips"), id="m-trips"),
                metric("Revenue", number("revenue"), id="m-revenue"),
                metric("Avg distance", number("avg_km", ".2f"), id="m-km"),
                metric("Avg passengers", number("avg_passengers", ".2f"), id="m-pax"),
            ),
        ),
        Loading(
            spinner(),
            lambda: columns(
                line_chart(lambda: daily().series("day", "trips"), labels=["trips per day"], height=220),
                bar_chart(lambda: hourly().series("hour", "trips"), labels=["trips per hour"], height=220),
            ),
        ),
        table(api.rows("trips", borough=borough), columns=COLUMNS, search=search, height=360, id="grid"),
    )


mount(app, "#app")
