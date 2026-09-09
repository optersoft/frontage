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
    ("lazy", "Lazy route", "A route in a chunk of its own: fetched on hover, not on load.", "#home"),
    ("chart", "Chart", "uPlot as a component — a 20,000-point chart from Python.", "canvas"),
    ("wasm", "Wasm library", "A WebAssembly library imported like any Python module.", "#answer"),
    ("rustlib", "Your own Rust", "A 1 KB Rust library, called from Python: 13× on the arithmetic.", "#mean"),
    ("spectrum", "Spectrum", "An FFT, a spectrogram and a filter, in 12 KB of Rust. No server.", "#rms"),
    ("weather", "Weather", "Streamlit's Seattle Weather demo, ported: five charts, no server.", "#app canvas"),
    (
        "uber",
        "Uber NYC",
        "Streamlit's flagship demo, rebuilt: a million pickups, and panning the map is an input.",
        "#histogram .bar",
    ),
    ("tracker", "Tracker", "The whole framework in one app: routes, store, optimistic writes, a portal.", "#app"),
    ("islands", "Islands", "A static page and two islands: the runtime is not on the critical path.", "#theme"),
    (
        "blog",
        "Blog",
        "Markdown, front matter and a schema — rendered at build time, with an island in the prose.",
        "article",
    ),
]

#: Apps built with `frontage prerender` rather than `frontage build`, and measured with
#: everything under `_frontage/` blocked but the island loader.
#:
#: The point of a static page is that its content is finished before the runtime is asked
#: for, and the only honest way to publish that as a number is to deny the page the runtime
#: and see whether it still shows what it promised. So the card's `bytes` and `transferred`
#: are the page, its stylesheet and the 1.3 KB loader — nothing else — and its `ready`
#: selector is what proves the claim. An app that cannot render without the runtime fails
#: here rather than quietly publishing a number that includes 660 KB of it.
PRERENDERED = {"islands", "blog"}

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
        static = name in PRERENDERED
        command = "prerender" if static else "build"
        subprocess.run(
            [sys.executable, "-m", "frontage", command, str(source), "--out", str(target), "--quiet"],
            check=True,
            cwd=ROOT,
        )
        if static:
            # What a reader downloads to see the page: it, its stylesheets, the loader. The
            # rest of `_frontage/` is what the page is *not* waiting for, and counting it
            # would publish the opposite of what the card says.
            size = sum(p.stat().st_size for p in target.rglob("*") if p.is_file() and _critical(p, target))
        else:
            size = sum(p.stat().st_size for p in target.rglob("*") if p.is_file())
        built.append({"name": name, "title": title, "blurb": blurb, "ready": ready, "bytes": size, "deferred": static})
    return built


#: What a browser can actually fetch from a static page: the document, what it links, and the
#: island loader. Everything else in a build travels with it to be *read* — the app's `.py`
#: sources, the Markdown a collection rendered, the host's `_headers` — and counting it would
#: publish a number no reader ever pays.
FETCHABLE = {".html", ".htm", ".css", ".svg", ".png", ".jpg", ".jpeg", ".webp", ".avif", ".gif", ".ico", ".woff2"}


def _critical(path, root):
    """Is this file on the critical path of a static page, or is it just travelling with it?"""
    relative = path.relative_to(root)
    if relative.parts[0] == "_frontage":
        return relative.name == "island.js"  # the runtime is deferred by design
    return relative.suffix.lower() in FETCHABLE


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
                # A static page is measured with the runtime denied: everything under
                # `_frontage/` is aborted but the loader, so the `ready` selector below is
                # proof the page needs none of it, and the byte count is what a reader pays.
                deferred = app.get("deferred", False)

                def allowed(url, deferred=deferred):
                    if "127.0.0.1" not in url:
                        # Nothing off this machine counts, and nothing off this machine is
                        # needed: the map app fetches OpenStreetMap tiles, which are neither
                        # ours to measure nor something a gallery build should depend on.
                        return False
                    return not deferred or "/_frontage/" not in url or url.endswith("island.js")

                context.route(
                    "**/*",
                    lambda route: route.continue_() if allowed(route.request.url) else route.abort(),
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
