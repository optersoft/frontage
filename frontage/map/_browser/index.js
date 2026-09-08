// The JavaScript half: it owns Leaflet, the tile layer and the markers, and exposes the two
// calls Python makes. Points cross as plain arrays or objects, because the two WebAssembly
// modules have separate memories and a copy is the only way through — so `draw` takes the
// whole set at once rather than a marker at a time.
import L from "./leaflet.js";

const held = new WeakMap();

const OSM = "https://tile.openstreetmap.org/{z}/{x}/{y}.png";
const OSM_ATTRIBUTION =
  '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';

/** Accept `[lat, lon]`, `{lat, lon}`, `{lat, lng}` or `{latitude, longitude}`. */
function at(point) {
  if (Array.isArray(point)) return point.length >= 2 ? [point[0], point[1]] : null;
  const lat = point.lat ?? point.latitude;
  const lon = point.lon ?? point.lng ?? point.longitude;
  return lat === undefined || lat === null || lon === undefined || lon === null ? null : [lat, lon];
}

function pick(point, key, options, fallback) {
  const own = Array.isArray(point) ? undefined : point[key];
  return own ?? options[key] ?? fallback;
}

/**
 * Draw or update the map in `node`.
 *
 * The map itself is built once and then only its marker layer is replaced, so a redraw does
 * not refetch a tile and does not move the map out from under a reader who has panned it.
 */
export function draw(node, points, options, onClick, onMove) {
  let map = held.get(node);
  if (!map) {
    const instance = L.map(node, {
      // Canvas rather than one SVG element per point: tens of thousands of markers stay
      // interactive, which is the case a data app actually has.
      preferCanvas: true,
      zoomControl: options.controls !== false,
      scrollWheelZoom: options.scroll !== false,
      attributionControl: true,
    });
    // `tiles: None` is a deliberate option, not a mistake: it draws the points on a plain
    // background and makes the whole app work with no network at all.
    if (options.tiles !== null) {
      L.tileLayer(options.tiles || OSM, {
        attribution: options.attribution ?? OSM_ATTRIBUTION,
        maxZoom: options.max_zoom || 19,
      }).addTo(instance);
    }
    // Leaflet measures its container once. A container that grows later — a flex column, a
    // tab that becomes visible, a window resize — otherwise renders at the old size forever.
    const observer = new ResizeObserver(() => instance.invalidateSize());
    observer.observe(node);
    map = { instance, layer: L.layerGroup().addTo(instance), observer, placed: false };
    held.set(node, map);
    if (onClick) instance.on("click", (e) => onClick(e.latlng.lat, e.latlng.lng));
    if (onMove) {
      const report = () => {
        const b = instance.getBounds();
        onMove(b.getSouth(), b.getWest(), b.getNorth(), b.getEast(), instance.getZoom());
      };
      instance.on("moveend", report);
      instance.whenReady(report);
    }
  }

  map.layer.clearLayers();
  const bounds = [];
  for (const point of points) {
    const here = at(point);
    if (!here) continue;
    bounds.push(here);
    const colour = pick(point, "color", options, "#b3541e");
    const marker = L.circleMarker(here, {
      radius: pick(point, "radius", options, 5),
      color: colour,
      weight: pick(point, "weight", options, 1),
      fillColor: pick(point, "fill", options, colour),
      fillOpacity: pick(point, "opacity", options, 0.6),
    });
    const popup = Array.isArray(point) ? undefined : point.popup;
    const tooltip = Array.isArray(point) ? undefined : point.tooltip;
    if (popup !== undefined && popup !== null) marker.bindPopup(String(popup));
    if (tooltip !== undefined && tooltip !== null) marker.bindTooltip(String(tooltip));
    marker.addTo(map.layer);
  }

  // Placed once. A redraw that re-centred would fight every reader who has panned, and the
  // common case — new points arriving from a filter — is exactly when that would happen.
  if (!map.placed || options.follow) {
    const fit = options.fit === undefined ? !options.center : Boolean(options.fit);
    if (fit && bounds.length) {
      map.instance.fitBounds(bounds, { padding: [24, 24], maxZoom: options.fit_zoom || 16 });
    } else {
      map.instance.setView(options.center || [0, 0], options.zoom ?? 2);
    }
    map.placed = true;
  }
}

export function destroy(node) {
  const map = held.get(node);
  if (!map) return;
  map.observer.disconnect();
  map.instance.remove();
  held.delete(node);
}
