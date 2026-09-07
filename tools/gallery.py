"""Build every gallery app, measure it in a real browser, and write the index from the result.

The gallery is the marketing and the acceptance test at once, so the numbers on it have to be
generated rather than typed: `mk gallery` builds each app with `frontage build`, serves the
output, loads it in Chromium, and records what the browser actually transferred and how long
it took to show something. If an app stops working the build fails; if it gets slower the page
says so.

    mk gallery              build, measure, write www/gallery/
    mk gallery --quick      skip the browser; sizes only (no cold-start column)
"""

import argparse
import json
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# What goes on the page, in the order a reader should meet it. `ready` is the selector that
# means "this app is doing its job", which is also what makes this a test.
APPS = [
    ("counter", "Counter", "Signals, a memo, and a hole that updates one text node.", "#value"),
    ("todo", "Todo", "A store, a keyed <code>For</code>, two-way binding.", "#app li"),
    ("template", "Template", 'The same counter written as <code>html(t"…")</code>.', "#value"),
    ("forms", "Forms", "Bindings, <code>Switch</code>, an <code>Action</code> on submit.", "#app form"),
    ("fetch", "Fetch", "<code>Resource</code>, <code>Loading</code> and <code>Errored</code>.", "#app"),
    ("contacts", "Contacts", "The router: nested routes, links, query strings.", "#app a"),
    ("chart", "Chart", "uPlot as a component — a 20,000-point chart from Python.", "canvas"),
    ("wasm", "Wasm library", "A WebAssembly library imported like any Python module.", "#answer"),
    ("tracker", "Tracker", "The whole framework in one app: routes, store, optimistic writes, a portal.", "#app"),
]

PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Frontage gallery</title>
<meta name="description" content="Python apps running in the browser on WebAssembly. No server, no build step, no JavaScript.">
<style>
  :root {{ color-scheme: light dark; --bg:#fbfaf7; --fg:#1b1b1b; --line:#e3e0d8; --accent:#b3541e; --muted:#6b6862; }}
  @media (prefers-color-scheme: dark) {{ :root {{ --bg:#15140f; --fg:#ebe8e1; --line:#2b2a24; --accent:#e08a4a; --muted:#9a968d; }} }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; padding:2rem 1.25rem 4rem; font:16px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
         background:var(--bg); color:var(--fg); }}
  .wrap {{ max-width: 62rem; margin: 0 auto; }}
  h1 {{ font-size: 2rem; margin: 0 0 .25rem; }}
  .lede {{ color: var(--muted); margin: 0 0 .5rem; max-width: 44rem; }}
  a {{ color: var(--accent); }}
  .grid {{ display: grid; gap: 1rem; grid-template-columns: repeat(auto-fill, minmax(17rem, 1fr)); margin-top: 2rem; }}
  .card {{ border:1px solid var(--line); border-radius:10px; padding:1rem 1.1rem; display:flex; flex-direction:column; gap:.4rem; }}
  .card h2 {{ font-size:1.05rem; margin:0; }}
  .card h2 a {{ text-decoration: none; }}
  .card p {{ margin:0; color:var(--muted); font-size:.9rem; flex:1; }}
  .nums {{ display:flex; gap:1.25rem; font-size:.8rem; color:var(--muted); font-variant-numeric:tabular-nums;
           border-top:1px solid var(--line); padding-top:.5rem; margin-top:.3rem; }}
  .nums b {{ color:var(--fg); font-weight:600; }}
  footer {{ margin-top:3rem; color:var(--muted); font-size:.85rem; border-top:1px solid var(--line); padding-top:1rem; }}
  code {{ background:color-mix(in srgb, currentColor 8%, transparent); padding:.05em .35em; border-radius:4px; font-size:.9em; }}
</style>
</head>
<body>
<div class="wrap">
<h1>Frontage gallery</h1>
<p class="lede">Python in the browser, on MicroPython compiled to WebAssembly. Every app below is
a directory of static files: no server, no build step, no JavaScript toolchain. The numbers are
measured, not claimed — they come from loading each page in Chromium with a cold cache.</p>
<p class="lede"><a href="https://academy.optersoft.com/python/frontage">Learn it</a> ·
<a href="/playground/">Playground</a> ·
<a href="https://github.com/optersoft/frontage">Source</a></p>
<div class="grid">
{cards}
</div>
<footer>{footer}</footer>
</div>
</body>
</html>
"""

CARD = """  <div class="card">
    <h2><a href="./{name}/">{title}</a></h2>
    <p>{blurb}</p>
    <div class="nums"><span><b>{kb}</b> KB</span>{timing}</div>
  </div>"""


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def build_all(out):
    """Every app built with the real command, so a broken one fails the gallery."""
    built = []
    for name, title, blurb, ready in APPS:
        source = ROOT / "examples" / name
        target = out / name
        subprocess.run(
            [sys.executable, "-m", "frontage", "build", str(source), "--out", str(target), "--quiet"],
            check=True,
            cwd=ROOT,
        )
        size = sum(p.stat().st_size for p in target.rglob("*") if p.is_file())
        built.append({"name": name, "title": title, "blurb": blurb, "ready": ready, "bytes": size})
    return built


def measure(built, out):
    """Load each app cold and record what the browser fetched and how long it waited."""
    from playwright.sync_api import sync_playwright

    port = free_port()
    server = subprocess.Popen(
        [sys.executable, "-m", "frontage", "serve", str(out), "--port", str(port), "--quiet"],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        for _ in range(100):
            try:
                socket.create_connection(("127.0.0.1", port), 0.1).close()
                break
            except OSError:
                time.sleep(0.1)
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            for app in built:
                context = browser.new_context()  # cold cache per app
                page = context.new_page()
                sent = [0]
                page.on(
                    "response", lambda r, s=sent: s.__setitem__(0, s[0] + int(r.header_value("content-length") or 0))
                )
                start = time.perf_counter()
                page.goto(f"http://127.0.0.1:{port}/{app['name']}/index.html")
                page.wait_for_selector(app["ready"], timeout=60_000)
                app["ms"] = round((time.perf_counter() - start) * 1000)
                app["transferred"] = sent[0]
                context.close()
            browser.close()
    finally:
        server.terminate()
    return built


def shared_bytes(out, built):
    """What every app downloads identically: the interpreter, its glue, the loader and the
    framework. Computed, not guessed — it is the honest denominator for every figure above."""
    runtime = out / built[0]["name"] / "_frontage"
    return sum(p.stat().st_size for p in runtime.iterdir() if p.is_file() and p.name != "app.tar")


def write_index(built, out, measured):
    cards = "\n".join(
        CARD.format(
            name=app["name"],
            title=app["title"],
            blurb=app["blurb"],
            kb=f"{app['bytes'] // 1024:,}",
            timing=f"<span>starts in <b>{app['ms']}</b> ms</span>" if measured else "",
        )
        for app in built
    )
    when = time.strftime("%Y-%m-%d")
    how = "Chromium, cold cache, first paint of the app's own content" if measured else "sizes only"
    shared = shared_bytes(out, built) // 1024
    footer = (
        f"Measured {when} · {how} · the interpreter, the loader and the framework are "
        f"{shared:,} KB of every figure and are byte-identical, so a browser downloads them "
        "once for all nine."
    )
    (out / "index.html").write_text(PAGE.format(cards=cards, footer=footer))
    (out / "gallery.json").write_text(json.dumps(built, indent=2))


def main(argv=None):
    parser = argparse.ArgumentParser(prog="mk gallery", description=__doc__)
    parser.add_argument("--out", default=str(ROOT / "www" / "gallery"))
    parser.add_argument("--quick", action="store_true", help="skip the browser; sizes only")
    args = parser.parse_args(argv)

    out = Path(args.out)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    built = build_all(out)
    measured = not args.quick
    if measured:
        built = measure(built, out)
    write_index(built, out, measured)
    total = sum(app["bytes"] for app in built)
    print(f"{out}: {len(built)} apps, {total:,} bytes")
    for app in built:
        timing = f", {app['ms']:>4} ms" if measured else ""
        print(f"  {app['name']:10} {app['bytes'] // 1024:>4} KB{timing}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
