"""Maps for frontage, on Leaflet: points, popups and a viewport you can read.

Leaflet rather than MapLibre because 42 KB gzipped is the same size as the whole framework and
MapLibre is 275 KB, measured, and because what a data app draws is points on a basemap — which
is Leaflet's entire job. Vector tiles, 3D and WebGL styling are a different, heavier component
and can stay one.

`map_view(points)` takes an accessor and redraws when it changes. `on_move` reports the
viewport back, so the map can filter the page rather than only display it.

One honest caveat: this is the first component here that talks to the network at runtime, for
its tiles. That is the thing you asked for rather than a phone-home, the provider is yours to
choose, and `tiles=None` turns it off entirely.
"""

from .map import map_view

__all__ = ["map_view"]
