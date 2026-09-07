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
    ("weather", "Weather", "Streamlit's Seattle Weather demo, ported: five charts, no server.", "#app canvas"),
    ("tracker", "Tracker", "The whole framework in one app: routes, store, optimistic writes, a portal.", "#app"),
]

PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Frontage gallery</title>
<meta name="description" content="Python apps running in the browser on WebAssembly. No server, no build step, no JavaScript.">
<link rel="stylesheet" href="./site.css">
</head>
<body class="min-h-screen bg-page text-ink dark:bg-page-dark dark:text-ink-dark font-sans antialiased">
<div class="mx-auto max-w-5xl px-5 py-10 sm:py-14">

<header class="flex flex-wrap items-baseline gap-x-3 gap-y-1">
  <a href="/" class="text-2xl font-bold tracking-tight no-underline text-ink dark:text-ink-dark">Frontage</a>
  <span class="text-2xl tracking-tight text-muted dark:text-muted-dark">gallery</span>
</header>

<p class="mt-4 max-w-2xl text-muted dark:text-muted-dark">Python in the browser, on MicroPython
compiled to WebAssembly. Every app below is a directory of static files: no server, no build
step, no JavaScript toolchain. The numbers are measured, not claimed — they come from loading
each page in Chromium with a cold cache.</p>

<nav class="mt-4 flex flex-wrap gap-x-4 gap-y-1 text-sm font-medium">
  <a href="https://academy.optersoft.com/python/frontage" class="text-brand dark:text-brand-dark hover:underline">Learn it</a>
  <a href="/playground/" class="text-brand dark:text-brand-dark hover:underline">Playground</a>
  <a href="https://github.com/optersoft/frontage" class="text-brand dark:text-brand-dark hover:underline">Source</a>
</nav>

<div class="mt-10 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
{cards}
</div>

<footer class="mt-14 border-t border-line dark:border-line-dark pt-4 text-sm text-muted dark:text-muted-dark">{footer}</footer>
</div>
</body>
</html>
"""

CARD = """  <a href="./{name}/"
     class="group flex flex-col gap-2 rounded-xl border border-line dark:border-line-dark
            bg-card dark:bg-card-dark p-5 no-underline text-ink dark:text-ink-dark
            transition hover:-translate-y-0.5 hover:border-brand dark:hover:border-brand-dark hover:shadow-md">
    <h2 class="text-base font-semibold group-hover:text-brand dark:group-hover:text-brand-dark">{title}</h2>
    <p class="flex-1 text-sm text-muted dark:text-muted-dark">{blurb}</p>
    <div class="mt-1 flex gap-5 border-t border-line dark:border-line-dark pt-2 text-xs
                tabular-nums text-muted dark:text-muted-dark">
      <span><b class="font-semibold text-ink dark:text-ink-dark">{kb}</b> KB</span>{timing}
    </div>
  </a>"""

TIMING = '<span>starts in <b class="font-semibold text-ink dark:text-ink-dark">{ms}</b> ms</span>'


def stylesheet(out, force=False):
    """Put the site's stylesheet beside the page. Compiled only when stale — see site_css."""
    import site_css

    current = site_css.build(force=force)
    shutil.copy(site_css.OUTPUT, out / "site.css")
    return current


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
    return built, True


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
            timing=TIMING.format(ms=app["ms"]) if measured else "",
        )
        for app in built
    )
    when = time.strftime("%Y-%m-%d")
    how = "Chromium, cold cache, first paint of the app's own content" if measured else "sizes only"
    shared = shared_bytes(out, built) // 1024
    footer = (
        f"Measured {when} · {how} · the interpreter, the loader and the framework are "
        f"{shared:,} KB of every figure and are byte-identical, so a browser downloads them "
        "once for all of them."
    )
    (out / "index.html").write_text(PAGE.format(cards=cards, footer=footer))
    (out / "gallery.json").write_text(json.dumps(built, indent=2))


def main(argv=None):
    parser = argparse.ArgumentParser(prog="mk gallery", description=__doc__)
    parser.add_argument("--out", default=str(ROOT / "www" / "gallery"))
    parser.add_argument("--quick", action="store_true", help="skip the browser; sizes only")
    parser.add_argument("--css", action="store_true", help="recompile tools/gallery.css with Tailwind")
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
    stylesheet(out, force=args.css)
    total = sum(app["bytes"] for app in built)
    print(f"{out}: {len(built)} apps, {total:,} bytes")
    for app in built:
        timing = f", {app['ms']:>4} ms" if measured else ""
        print(f"  {app['name']:10} {app['bytes'] // 1024:>4} KB{timing}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
