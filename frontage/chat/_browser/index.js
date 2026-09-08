// The JavaScript half: one POST whose answer is read as it arrives, and nothing else. Python
// decides what to send and what to do with each token; this module owns the reader loop,
// because pulling a stream chunk by chunk across the bridge would cost a crossing per byte.

/** POST `body` to `url` and call `onToken(text)` for every `data:` line the server sends.
 *  Returns {promise, abort}: `promise` settles to {status, text} when the stream ends. */
export function stream(url, body, onToken) {
  const controller = new AbortController();
  const promise = (async () => {
    const response = await fetch(url, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body,
      signal: controller.signal,
    });
    if (!response.ok || !response.body) {
      return { status: response.status, text: await response.text() };
    }
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      // Server-Sent Events: frames are separated by a blank line, and only `data:` carries
      // payload. A partial frame stays in the buffer until the rest of it arrives — the
      // whole reason this is a loop and not a `split`.
      let cut;
      while ((cut = buffer.indexOf("\n\n")) >= 0) {
        const frame = buffer.slice(0, cut);
        buffer = buffer.slice(cut + 2);
        for (const line of frame.split("\n")) {
          if (line.startsWith("data:")) {
            const payload = line.slice(5).replace(/^ /, "");
            if (payload === "[DONE]") return { status: 200, text: "" };
            // JSON, so a token holding a newline survives: SSE would otherwise split it
            // across two `data:` lines and the text would silently lose the break.
            onToken(JSON.parse(payload));
          }
        }
      }
    }
    return { status: 200, text: "" };
  })();
  return { promise, abort: () => controller.abort() };
}
