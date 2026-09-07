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
