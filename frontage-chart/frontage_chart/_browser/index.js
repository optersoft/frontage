// The JavaScript half: it owns uPlot and the canvas, and exposes the two calls Python makes.
// Everything crosses as plain arrays, because the two WebAssembly modules have separate
// memories and a copy is the only way through — so the calls are coarse by design.
import uPlot from "./uplot.js";

const charts = new WeakMap();

const STROKES = ["#b3541e", "#1e6fb3", "#3d8b40", "#8b3da8", "#b39a1e"];

function paths(kind) {
  if (kind === "bar") return uPlot.paths.bars({ size: [0.7] });
  if (kind === "scatter") return () => null; // points only; uPlot draws those anyway
  return undefined; // line and area use the default line path
}

/** Draw or update a chart in `node`. `series` is [x[], y1[], y2[]…] — plain arrays from
 * Python, or Float64Arrays that arrived from a server (`frontage-polars`' `series`), which are
 * drawn as they are: no copy, and Python never held a value. */
export function draw(node, series, options) {
  const data = Array.from(series, (column) => (column instanceof Float64Array ? column : Float64Array.from(column)));
  const existing = charts.get(node);
  if (existing && existing.kind === options.kind && existing.chart.series.length === data.length) {
    existing.chart.setData(data);
    return;
  }
  if (existing) existing.chart.destroy();

  const kind = options.kind || "line";
  const opts = {
    width: options.width || node.clientWidth || 600,
    height: options.height || 240,
    title: options.title || "",
    scales: { x: { time: Boolean(options.time) } },
    series: [
      {},
      ...data.slice(1).map((_, i) => ({
        stroke: (options.colors && options.colors[i]) || STROKES[i % STROKES.length],
        fill: kind === "area" ? (options.colors && options.colors[i]) || STROKES[i % STROKES.length] + "33" : undefined,
        width: kind === "scatter" ? 0 : 2,
        points: { show: kind === "scatter" ? true : undefined },
        paths: paths(kind),
        label: (options.labels && options.labels[i]) || `series ${i + 1}`,
      })),
    ],
  };
  charts.set(node, { chart: new uPlot(opts, data, node), kind });
}

export function destroy(node) {
  const held = charts.get(node);
  if (held) {
    held.chart.destroy();
    charts.delete(node);
  }
}
