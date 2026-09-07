// The JavaScript half of this app's chart component: it owns uPlot and the canvas, and takes
// two things from Python — the columns and the options. Everything reactive stays on the
// Python side; this file has no idea a signal exists.
import uPlot from "./uplot.js";

const charts = new WeakMap();

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const BEFORE_MONTH = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334];

/** The month a day-of-year falls in, for the x axis of a chart drawn against `day`. */
function monthOf(day) {
  let month = 0;
  while (month < 11 && day > BEFORE_MONTH[month + 1]) month++;
  return MONTHS[month];
}

// Ticks on the first of each month rather than wherever uPlot's own spacing lands: the
// labels are month names, so they have to sit on month boundaries to mean anything.
function monthAxis() {
  return {
    splits: () => BEFORE_MONTH.map((day) => day + 1),
    values: (u, splits) => splits.map((v) => monthOf(v)),
  };
}

/** What makes a chart a different chart rather than the same one with new numbers. */
function shape(series, options) {
  return [series.length, (options.labels || []).join("|"), options.format || ""].join("/");
}

function config(series, options) {
  const colors = options.colors || [];
  const labels = options.labels || [];
  const bands = options.bands || [];
  // A band runs from a high series to a low one and the pair shares a colour, so the low
  // half is drawn faint: the eye should read one range, not two lines.
  const faint = new Set(bands.map((pair) => pair[1]));
  const x = options.format === "day" ? monthAxis() : null;
  return {
    height: options.height || 240,
    scales: { x: { time: false } },
    axes: x ? [x, {}] : undefined,
    legend: { show: options.legend !== false },
    series: [
      { label: options.x_label || "day" },
      ...series.slice(1).map((_, i) => ({
        stroke: colors[i] || "#b3541e",
        width: faint.has(i + 1) ? 0.5 : 1.5,
        label: labels[i] || `series ${i + 1}`,
        points: { show: false },
      })),
    ],
    bands: bands.map((pair) => ({ series: pair, fill: (u) => u.series[pair[0]].stroke + "33" })),
  };
}

/** Draw or update the chart in `node`. `series` is [x[], y1[], …]; a null is a gap. */
export function draw(node, series, options) {
  const data = series.map((column) => Array.from(column));
  const held = charts.get(node);
  const wanted = shape(series, options);
  if (held && held.shape === wanted) {
    held.chart.setData(data);
    return;
  }
  if (held) held.chart.destroy();
  const width = options.width || node.clientWidth || 600;
  const chart = new uPlot({ ...config(series, options), width }, data, node);
  charts.set(node, { chart, shape: wanted });
}

export function destroy(node) {
  const held = charts.get(node);
  if (held) {
    held.chart.destroy();
    charts.delete(node);
  }
}
