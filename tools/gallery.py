"""Build every gallery app, measure it in a real browser, and write the index from the result.

The gallery is the marketing and the acceptance test at once, so the numbers on it have to be
generated rather than typed: `mk gallery` builds each app with `frontage build`, serves the
output, loads it in Chromium, and records what the browser actually transferred and how long
it took to show something. If an app stops working the build fails; if it gets slower the page
says so. The page is web/src/pages/gallery/index.astro (the Astro site); this writes the JSON
it renders.

    mk gallery              build, measure, write www/gallery/ and web/src/data/gallery.json
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
    ("weather", "Weather", "Streamlit's Seattle Weather demo, ported: five charts, no server.", "#app canvas"),
    (
        "uber",
        "Uber NYC",
        "Streamlit's flagship demo, rebuilt: a million pickups, and panning the map is an input.",
        "#histogram .bar",
    ),
    ("tracker", "Tracker", "The whole framework in one app: routes, store, optimistic writes, a portal.", "#app"),
]

#: Where the site's gallery page reads the result from (web/src/data/, gitignored). The page
#: itself is web/src/pages/gallery/index.astro; this script only produces the facts.
SITE_DATA = ROOT / "web" / "src" / "data" / "gallery.json"


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
    """Load each app cold and record what the browser fetched and how long it waited.

    Returns `(apps, measured)`. A build host without Playwright or without a browser gets
    sizes only rather than a failure: this runs on the deploy builder, and a site that cannot
    be assembled without Chromium is a site that stops deploying the first time that breaks.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("no playwright: publishing sizes only", file=sys.stderr)
        return built, False

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
            try:
                browser = pw.chromium.launch()
            except Exception as exc:  # no browser installed on this host
                print(f"no browser ({type(exc).__name__}): publishing sizes only", file=sys.stderr)
                return built, False
            for app in built:
                context = browser.new_context()  # cold cache per app
                page = context.new_page()
                # Nothing off this machine counts, and nothing off this machine is needed: the
                # map app fetches OpenStreetMap tiles, which are neither ours to measure nor
                # something a gallery build should depend on being reachable.
                context.route(
                    "**/*",
                    lambda route: route.continue_() if "127.0.0.1" in route.request.url else route.abort(),
                )
                sent = [0]

                def count_bytes(response, s=sent):
                    # A response that arrives as the context closes cannot be read any more,
                    # and its bytes are not part of what the page waited for either.
                    try:
                        s[0] += int(response.header_value("content-length") or 0)
                    except Exception:
                        pass

                page.on("response", count_bytes)
                start = time.perf_counter()
                page.goto(f"http://127.0.0.1:{port}/{app['name']}/index.html")
                page.wait_for_selector(app["ready"], timeout=60_000)
                app["ms"] = round((time.perf_counter() - start) * 1000)
                app["transferred"] = sent[0]
                context.close()
            browser.close()
    finally:
        server.terminate()
    return built, True


def shared_bytes(out, built):
    """What every app downloads identically: the interpreter, its glue, the loader and the
    framework. Computed, not guessed — it is the honest denominator for every figure above."""
    runtime = out / built[0]["name"] / "_frontage"
    return sum(p.stat().st_size for p in runtime.iterdir() if p.is_file() and p.name != "app.tar")


def write_index(built, out, measured):
    """Write the facts the gallery page renders: the apps, when and how they were measured, and
    the shared denominator. One document, two copies — beside the apps (served as
    /gallery/gallery.json) and where the Astro build reads it."""
    when = time.strftime("%Y-%m-%d")
    shared = shared_bytes(out, built) // 1024
    apps = [{k: v for k, v in app.items() if k != "ready"} for app in built]
    document = json.dumps({"apps": apps, "measured": measured, "when": when, "shared_kb": shared}, indent=2)
    (out / "gallery.json").write_text(document)
    SITE_DATA.parent.mkdir(parents=True, exist_ok=True)
    SITE_DATA.write_text(document)


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
    measured = False
    if not args.quick:
        built, measured = measure(built, out)
    write_index(built, out, measured)
    total = sum(app["bytes"] for app in built)
    print(f"{out}: {len(built)} apps, {total:,} bytes")
    for app in built:
        timing = f", {app['ms']:>4} ms" if measured else ""
        print(f"  {app['name']:10} {app['bytes'] // 1024:>4} KB{timing}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
