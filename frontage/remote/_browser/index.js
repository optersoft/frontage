// The JavaScript half: the transport, and nothing else. Python decides *what* to ask and what
// to do with the answer; this module does one fetch or one event stream per call, so a request
// costs two crossings (start it, take the text) instead of one per Response method.

/** Start a GET. Returns {promise, abort}: `promise` settles to {status, text}. */
export function get(url) {
  const controller = new AbortController();
  const promise = fetch(url, { signal: controller.signal }).then(async (response) => ({
    status: response.status,
    text: await response.text(),
  }));
  return { promise, abort: () => controller.abort() };
}

/** Open a Server-Sent Events stream; `callback(text)` per message. Returns a closer. */
export function subscribe(url, callback) {
  const stream = new EventSource(url);
  stream.onmessage = (event) => callback(event.data);
  return () => stream.close();
}

/** Start a GET for `/series/…`. `promise` settles to {status, text, series, height}: on 200,
 * `series` is one Float64Array per column, views over the response's own buffer — the chart
 * draws them as they are, and no value ever crosses into Python. */
export function getSeries(url) {
  const controller = new AbortController();
  const promise = fetch(url, { signal: controller.signal }).then(async (response) => {
    if (response.status !== 200) {
      return { status: response.status, text: await response.text(), series: null, height: 0 };
    }
    const buffer = await response.arrayBuffer();
    const view = new DataView(buffer);
    const columns = view.getUint32(0, true);
    const height = view.getUint32(4, true);
    const series = [];
    for (let c = 0; c < columns; c++) series.push(new Float64Array(buffer, 8 + c * height * 8, height));
    return { status: 200, text: "", series, height };
  });
  return { promise, abort: () => controller.abort() };
}
