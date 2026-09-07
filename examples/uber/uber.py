"""Streamlit's Uber NYC Pickups demo, rebuilt — and then given the part Streamlit cannot do.

The original (github.com/streamlit/demo-uber-nyc-pickups) is a script that re-runs from the top
on a server every time you move the slider: it re-reads the frame, re-bins it, and ships a new
map and a new chart down the wire. This is the same page as a reactive graph in the browser.
Moving the slider writes one signal; the two memos that read it recompute; the map's marker
layer is replaced and nothing else on the page is touched. There is no server.

Then the part the original cannot have at any speed: **panning the map is an input**. The map
reports its viewport back through `on_move`, a memo scans the packed bytes for the pickups
inside it, and the hour histogram redraws for that neighbourhood alone. In a rerun framework
that is a round trip and a full-page rebuild per drag; here it is one signal write.

The data is real — 998,189 of the 1,028,136 pickups from September 2014, aggregated in
`data.py` — and the page fetches nothing but map tiles.
"""

import data
from mapview import map_view

from frontage import For, Memo, Signal, h, mount

HOURS = [f"{h:02d}:00" for h in range(24)]

# Five bands rather than a continuous scale: a circle two pixels bigger is not a fact a reader
# can read off a map, and five colours are.
BANDS = (
    (5, 2.5, "#4a5a8a"),
    (20, 3.5, "#5b83a8"),
    (60, 4.5, "#c9a227"),
    (200, 6.0, "#d97706"),
    (10**9, 8.0, "#b3202c"),
)

hour = Signal(18)  # 18:00 is the busiest hour of the month
view = Signal(None)  # (south, west, north, east), written by the map as it moves


def band(count):
    for limit, radius, color in BANDS:
        if count < limit:
            return radius, color
    return BANDS[-1][1], BANDS[-1][2]


def marker(cell):
    lat, lon, count = cell
    radius, color = band(count)
    return {"lat": lat, "lon": lon, "radius": radius, "color": color, "opacity": 0.75, "weight": 0}


points = Memo(lambda: [marker(c) for c in data.cells(hour())])
citywide = Memo(lambda: sum(c for _, _, c in data.cells(hour())))

# Twenty-four numbers for whatever is on screen. Recomputed when the map settles, and only
# then — the slider does not touch it, because the histogram covers every hour already.
histogram = Memo(lambda: data.histogram(*view()) if view() is not None else None)
in_view = Memo(lambda: 0 if histogram() is None else histogram()[hour()])
busiest = Memo(lambda: 0 if histogram() is None else max(histogram()) or 1)


def bars():
    counts = histogram()
    if counts is None:
        return []
    top = busiest()
    return [{"hour": i, "count": n, "height": 100.0 * n / top} for i, n in enumerate(counts)]


def moved(south, west, north, east, zoom):
    view.set((south, west, north, east))


def group(n):
    """A thousands separator, which MicroPython's format mini-language does not have."""
    text = str(int(n))
    out = []
    while len(text) > 3:
        out.insert(0, text[-3:])
        text = text[:-3]
    out.insert(0, text)
    return ",".join(out)


mount(
    lambda: h.div(
        h.header(
            h.h1("Uber pickups in New York City"),
            h.p(
                "All ",
                group(data.TOTAL),
                " pickups of September 2014, in the browser. ",
                h.a("Streamlit's demo", href="https://github.com/streamlit/demo-uber-nyc-pickups"),
                " reruns a Python script on a server for every one of these interactions.",
                cls="lede",
            ),
        ),
        h.section(
            h.div(
                h.label("Hour of day", for_="hour"),
                h.input(
                    type_="range",
                    id="hour",
                    min="0",
                    max="23",
                    value=lambda: str(hour()),
                    on_input=lambda ev: hour.set(int(ev.target.value)),
                ),
                h.output(lambda: HOURS[hour()], id="clock"),
                cls="slider",
            ),
            h.div(
                h.div(h.span(lambda: group(citywide()), id="citywide", cls="figure"), h.span("citywide", cls="unit")),
                h.div(h.span(lambda: group(in_view()), id="inview", cls="figure"), h.span("in view", cls="unit")),
                cls="figures",
            ),
            cls="controls",
        ),
        map_view(
            points,
            height=460,
            center=[40.745, -73.94],
            zoom=11,
            on_move=moved,
            fit=False,
            cls="pickups",
        ),
        h.section(
            h.h2("Pickups by hour, for whatever the map is showing"),
            h.p(
                "Drag the map. This chart is not the city's — it is the twenty-four hourly totals "
                "for the cells inside the current viewport, rescanned when you let go.",
                cls="lede",
            ),
            h.div(
                For(
                    bars,
                    lambda bar, index: h.div(
                        h.div(
                            cls=lambda: "bar on" if bar()["hour"] == hour() else "bar",
                            style_height=lambda: f"{bar()['height']:.1f}%",
                            title=lambda: f"{HOURS[bar()['hour']]} — {group(bar()['count'])} pickups",
                            on_click=lambda ev, bar=bar: hour.set(bar()["hour"]),
                        ),
                        h.div(lambda: str(bar()["hour"]), cls="tick"),
                        cls="column",
                    ),
                    key=False,
                ),
                cls="histogram",
                id="histogram",
            ),
            cls="panel",
        ),
        h.footer(
            h.p(
                "Cells are ",
                str(data.STEP),
                "° — about 550 by 420 metres — coloured in five bands by how many pickups "
                "started there in that hour. Data: FiveThirtyEight, from a New York City TLC "
                "FOIL request. Basemap: OpenStreetMap.",
            ),
        ),
        cls="page",
    ),
    "#app",
)
