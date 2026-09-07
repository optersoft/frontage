// The JavaScript half of a frontage chart component: it owns the library and the canvas, and
// exposes the smallest surface Python needs. Python sends data and options; nothing else.
import uPlot from "./uplot.js";

const charts = new WeakMap();

/** Draw or update a chart in `node`. `series` is [x[], y1[], y2[]...]. */
export function draw(node, series, options) {
  const data = series.map((column) => Float64Array.from(column));
  const existing = charts.get(node);
  if (existing) {
    existing.setData(data);
    return;
  }
  const opts = {
    width: options.width || node.clientWidth || 600,
    height: options.height || 240,
    title: options.title || "",
    scales: { x: { time: false } },
    series: [{}, ...data.slice(1).map((_, i) => ({
      stroke: options.colors ? options.colors[i] : "#b3541e",
      width: 2,
      label: options.labels ? options.labels[i] : `series ${i + 1}`,
    }))],
  };
  charts.set(node, new uPlot(opts, data, node));
}

export function destroy(node) {
  const chart = charts.get(node);
  if (chart) { chart.destroy(); charts.delete(node); }
}
