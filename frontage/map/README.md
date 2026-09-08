# frontage.map

Maps for [frontage](https://github.com/optersoft/frontage), on
[Leaflet](https://leafletjs.com): points on a basemap, popups, and — the part a map in a
reactive framework can do that a map in a rerun framework cannot — **a viewport the app can
read**.

```sh
pip install frontage
```

```py
from frontage import Signal
from frontage.map import map_view

stations = Signal(
    [
        {"lat": 41.3874, "lon": 2.1686, "popup": "Barcelona", "radius": 8},
        {"lat": 40.4168, "lon": -3.7038, "popup": "Madrid", "radius": 8},
    ]
)

map_view(stations, height=420)
```

`points` is an accessor, so the map redraws when the data changes and at no other time. A point
is `[lat, lon]` or a mapping with `lat`/`lon` — `lng` and `latitude`/`longitude` are accepted
too, so a row out of a dataset usually needs no reshaping — and may carry `popup`, `tooltip`,
`color`, `radius`, `opacity` and `weight`. The same names as keyword arguments set the default
for every point.

## The viewport is state

`on_move` fires when the viewport settles, and once when the map is ready:

```py
from frontage import Memo, Signal
from frontage.map import map_view

view = Signal(None)
visible = Memo(
    lambda: (
        []
        if view() is None
        else [p for p in rows() if view()[0] <= p["lat"] <= view()[2] and view()[1] <= p["lon"] <= view()[3]]
    )
)

map_view(rows, on_move=lambda s, w, n, e, z: view.set((s, w, n, e)))
```

Now a table, a count and a chart elsewhere on the page follow the map as it is panned, with no
round trip and no rerun. `on_click(lat, lon)` is there for the same reason.

## Placement

`center` and `zoom` place the map, or it fits itself to the points. Either way it is placed
**once**: points arriving from a filter never yank the map away from a reader who has panned
it. Pass `follow=True` if refitting on every change is what you actually want.

## Tiles, and the one honest caveat

This is the only component here that talks to the network at runtime. A basemap comes from a
tile server, and there is no way around that — but it is the thing you asked for rather than a
phone-home, and it is yours to choose:

```py
map_view(points, tiles="https://tiles.example.com/{z}/{x}/{y}.png", attribution="© Example")
map_view(points, tiles=None)  # points on a plain background; asks the network for nothing
```

The default is OpenStreetMap's own tile server with its attribution. That is right for
development and for small sites, and it is **not** right for a production app with traffic —
their [tile usage policy](https://operations.osmfoundation.org/policies/tiles/) asks you to run
or buy your own. Setting `tiles` is one keyword argument.

## Cost

| | raw | gzipped |
|---|---|---|
| `leaflet.js` | 148 KB | **42 KB** |
| `index.css` | 15 KB | **3.7 KB** |

Leaflet rather than MapLibre because MapLibre measures 275 KB gzipped — bigger than frontage
itself — and what a data app draws is points on a basemap, which is Leaflet's whole job. Vector
tiles, 3D and WebGL styling are a heavier component, and can stay a separate one.

No image ever loads. Markers are canvas circles, not the default icon, so the three image URLs
inside Leaflet's stylesheet belong to features this component does not use and are never
requested. Canvas is also why tens of thousands of points stay interactive.

Vendored, not fetched: the build needs no network and the app has no CDN in its critical path.
Leaflet is BSD-2-Clause and its licence travels in the file's own header.
