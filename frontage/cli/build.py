"""`python -m frontage build APP`: a directory that runs the app from WebAssembly.

The output is static and self-contained — no repo, no PyPI, no CDN, no server:

    index.html                 the page, with the boot tag
    app.py, …                  the app's sources, still readable
    _frontage/boot.js          the loader
    _frontage/micropython.mjs  the interpreter's glue
    _frontage/micropython.wasm the interpreter
    _frontage/frontage.tar     the framework, precompiled
    _frontage/app.tar          the app's modules, as the interpreter imports them

Four requests to first paint, and every one of them but `app.tar` is immutable for a given
frontage version, so a second app on the same site pays for none of it again.

This replaces `export`, which wrote a PyScript page: a `pyscript.json`, the framework as
sixteen separate `.py` files fetched and compiled on every page view, and PyScript's own
bundle on top. `export` keeps working through 0.9.x for the pages that still need it.
"""

import argparse
import re
import shutil
import sys
from pathlib import Path

from . import PROG

IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", "_frontage", "*.tar")

PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1.0">
  <title>{title}</title>
</head>
<body>
<div id="app">Loading…</div>
{tag}
</body>
</html>
"""


# PyScript's two page-level assets. An app being migrated still names them, and left in place
# they are two 404s and a console error on a page that otherwise works. Only these two are
# touched: an app's own inline JavaScript is its own business, and a `<script type="mpy">` that
# PyScript never claims is inert anyway.
_PYSCRIPT_ASSET = re.compile(
    r"""[ \t]*<(?:script[^>]*\bsrc|link[^>]*\bhref)\s*=\s*["'][^"']*\bcore\.(?:js|css)["'][^>]*>"""
    r"""(?:\s*</script>)?[ \t]*\n?""",
    re.I,
)


def strip_pyscript(html):
    """`html` without PyScript's `core.js` / `core.css` tags."""
    return _PYSCRIPT_ASSET.sub("", html)


def boot_tag(entry, prefix="./", declarations=()):
    """The one tag a page needs. `declarations` are `name=specifier` pairs for `data-fr-js`."""
    js = f' data-fr-js="{", ".join(declarations)}"' if declarations else ""
    return f'<script type="module" src="{prefix}_frontage/boot.js" data-fr-boot data-fr-entry="{entry}"{js}></script>'


# --- components ------------------------------------------------------------------------
#
# A component is a Python package that also ships browser assets. Frontage's own are
# subpackages — `frontage.chart`, `frontage.table`, `frontage.map`, … — found by the
# `_browser/` directory they carry; a third-party one declares itself with a
# `frontage.components` entry point, which is metadata read on CPython at build time, so the
# browser pays nothing for the mechanism:
#
#     [project.entry-points."frontage.components"]
#     gantt = "frontage_gantt"
#
# Either lays its browser half out by convention, because a manifest for two files is a form
# to fill in rather than a thing that helps:
#
#     frontage/chart/_browser/index.js     the module `data-fr-js` registers (required)
#     frontage/chart/_browser/index.css    linked from the page if it exists
#
# Its Python is packed under its package path, so `import frontage.chart` works in the page —
# except a module whose name starts with an underscore, which stays on CPython. That is how a
# component keeps a server half (`_server.py`) or a build-time tool (`_compile.py`) out of a
# page that could not import it anyway: frontage-polars shipped 15 KB of FastAPI imports to the
# browser before this rule existed (2026-09-07).

BROWSER_DIR = "_browser"
COMPONENT_ENTRY = "index.js"
COMPONENT_STYLE = "index.css"


class Component:
    def __init__(self, name, package, root=None):
        self.name = name  # the `data-fr-js` key: the JavaScript module the component's Python imports
        self.package = Path(package)
        # Where the Python lands in the archive, which is also what the app imports: a
        # subpackage of frontage lives at `frontage/<name>`, a third-party package at its own
        # name (`frontage_gantt`).
        self.root = root or self.package.name
        # Frontage's own subpackages arrive with the framework; a third-party one was
        # installed on purpose, which is what makes "installed but not imported" worth saying.
        self.builtin = False

    @property
    def import_name(self):
        return self.root.replace("/", ".")

    @property
    def browser(self):
        return self.package / BROWSER_DIR

    def modules(self):
        """The component's Python, as (archive path, file) pairs under its package name."""
        found = []
        for path in sorted(self.package.rglob("*.py")):
            relative = path.relative_to(self.package)
            if BROWSER_DIR in relative.parts or "__pycache__" in relative.parts:
                continue
            if path.name.startswith("_") and path.name != "__init__.py":
                continue  # private to CPython: a server half, a compiler, a test helper
            found.append((f"{self.root}/{relative.as_posix()}", path))
        return found


def builtin():
    """Frontage's own components: every subpackage that ships a `_browser/` directory —
    `frontage.chart`, `frontage.table`, `frontage.map`, … (one distribution since 0.10)."""
    package = Path(__file__).resolve().parent.parent
    found = []
    for sub in sorted(package.iterdir()):
        if sub.is_dir() and (sub / BROWSER_DIR / COMPONENT_ENTRY).is_file():
            component = Component(sub.name, sub, root=f"frontage/{sub.name}")
            component.builtin = True
            found.append(component)
    return found


def discover():
    """Every component here: frontage's own, then any third-party package that declares the
    `frontage.components` entry point. Never imports one: a component's Python is written for
    the browser, and importing it here would run it on the wrong interpreter."""
    from importlib import metadata, util

    found = builtin()
    taken = {c.name for c in found}
    for entry in metadata.entry_points(group="frontage.components"):
        if entry.name in taken:
            continue
        spec = util.find_spec(entry.value)
        origin = getattr(spec, "origin", None)
        if origin is None:
            continue
        package = Path(origin).parent
        if (package / BROWSER_DIR / COMPONENT_ENTRY).is_file():
            found.append(Component(entry.name, package))
    return found


_IMPORTS = "(?:^|\n)[ \t]*(?:from|import)[ \t]+{0}\\b"
# `from frontage import dsp`, or `dsp` anywhere in that import's list of names.
_FROM_LIST = "(?:^|\n)[ \t]*from[ \t]+{0}[ \t]+import[ \t]+\\(?[^\n()]*(?:\n[^()]*)?\\b{1}\\b"


def imports(text, package):
    """Does this source import that package? `import x`, `from x import y`, `from x.y import z`,
    and — for a subpackage — `from x import y` naming it in the list.

    That last form is the one a reader writes without thinking (`from frontage import dsp`), and
    missing it meant the component was neither declared on the boot tag nor packed into the
    page, with the import failing in the browser and nothing here saying why.
    """
    if re.search(_IMPORTS.format(re.escape(package)), text) is not None:
        return True
    parent, _, leaf = package.rpartition(".")
    if not parent:
        return False
    return re.search(_FROM_LIST.format(re.escape(parent), re.escape(leaf)), text) is not None


def required(app, installed):
    """The installed components an app actually imports, and whatever those import in turn.

    `discover()` answers "what is in this environment", which is not the question a build asks.
    Without this step a developer with five components installed ships five: an app with no
    chart still downloads uPlot, registers it as a JavaScript module and links its stylesheet.
    That is the exact opposite of the rule the whole design rests on — a component is a
    dependency and costs nothing until it is imported — and it is invisible, because the extra
    ones work perfectly and only make the page bigger.

    Matching is textual on purpose. A component's Python is written for the browser's runtime,
    so asking the import system here would run it on the wrong interpreter, which is why
    `discover()` refuses to import one either. `--component` bypasses discovery and this too.
    """
    by_import = {c.import_name: c for c in installed}
    sources = "\n".join(path.read_text() for path in sorted(app.glob("*.py")))
    wanted, frontier = set(), [name for name in by_import if imports(sources, name)]
    while frontier:
        name = frontier.pop()
        if name in wanted:
            continue
        wanted.add(name)
        # A component may use another — a table built out of layout's container, say — and its
        # own imports are as binding as the app's.
        body = "\n".join(path.read_text() for _, path in by_import[name].modules())
        frontier.extend(n for n in by_import if n not in wanted and imports(body, n))
    return [c for c in installed if c.import_name in wanted]


def find_entry(app):
    """The module that mounts the app, in the order a person would guess it.

    The one that calls `mount(`, then a conventional name, then the only module there is. A
    directory that answers to none of those gets an error naming its candidates rather than a
    guess: picking the wrong entry produces a blank page and no explanation.
    """
    modules = sorted(p for p in app.glob("*.py") if not p.name.startswith("_"))
    if not modules:
        raise SystemExit(f"error: no .py files in {app}")
    mounting = [p for p in modules if "mount(" in p.read_text()]
    if len(mounting) == 1:
        return mounting[0].stem
    names = {p.stem for p in modules}
    for guess in ("app", "main", app.name):
        if guess in names:
            return guess
    if len(modules) == 1:
        return modules[0].stem
    raise SystemExit(f"error: cannot tell which module mounts the app ({', '.join(sorted(names))}); pass --entry")


_BOOT_TAG = re.compile(r"<script[^>]*\bdata-fr-boot\b[^>]*>", re.I)
_FR_JS = re.compile(r"""\s*data-fr-js\s*=\s*["\']([^"\']*)["\']""", re.I)


def declare(html, declarations):
    """Merge `declarations` into the page's existing boot tag's `data-fr-js`.

    A page may carry a hand-written boot tag — the examples do. Rewriting it wholesale would
    throw away whatever the author put there; ignoring it would mean an installed component
    silently does nothing. So the attribute is merged, author's entries first.
    """
    if not declarations:
        return html
    match = _BOOT_TAG.search(html)
    if match is None:
        return html
    tag = match.group(0)
    existing = _FR_JS.search(tag)
    names = [item.strip() for item in (existing.group(1).split(",") if existing else []) if item.strip()]
    have = {item.split("=", 1)[0].strip() for item in names}
    names += [d for d in declarations if d.split("=", 1)[0] not in have]
    merged = (_FR_JS.sub("", tag) if existing else tag)[:-1].rstrip()
    return html[: match.start()] + f'{merged} data-fr-js="{", ".join(names)}">' + html[match.end() :]


def build(app, out="", entry="", quiet=False, components=None, tailwind=False):
    from . import frontage_rt

    app = Path(app).resolve()
    if not app.is_dir():
        raise SystemExit(f"error: {app} is not a directory")
    out = Path(out).resolve() if out else Path("dist") / app.name
    entry = entry or find_entry(app)
    if not (app / f"{entry}.py").exists():
        raise SystemExit(f"error: no {entry}.py in {app}")

    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(app, out, ignore=IGNORE)

    runtime = out / "_frontage"
    runtime.mkdir(parents=True, exist_ok=True)
    if not frontage_rt.available():
        raise SystemExit("error: the runtime is missing from frontage/_runtime: run `mk runtime.build`")
    # The two scripts by name (the page names boot.js); the wasm by content hash, so it can be
    # cached forever and a runtime bump changes its URL.
    for name in ("glue.js", "boot.js", "island.js"):
        shutil.copy2(frontage_rt.RUNTIME_DIR / name, runtime / name)
    wasm_bytes = (frontage_rt.RUNTIME_DIR / "frontage.wasm").read_bytes()
    wasm_file = frontage_rt.hashed("frontage", wasm_bytes, "wasm")
    (runtime / wasm_file).write_bytes(wasm_bytes)

    # Components: assets beside the runtime, Python in the archive, a line in the boot tag.
    if components is None:
        found = list(discover())
        installed = required(app, found)
        # Only a component someone installed: frontage's own subpackages are always there,
        # and naming seven of them on every build would be noise rather than a warning.
        skipped = [c.name for c in found if c not in installed and not c.builtin]
    else:
        installed, skipped = list(components), []
    declarations, styles = [], []
    for component in installed:
        assets = runtime / "components" / component.name
        shutil.copytree(component.browser, assets, dirs_exist_ok=True)
        declarations.append(f"{component.name}=./_frontage/components/{component.name}/{COMPONENT_ENTRY}")
        if (assets / COMPONENT_STYLE).is_file():
            styles.append(f'<link rel="stylesheet" href="./_frontage/components/{component.name}/{COMPONENT_STYLE}">')
    # The entry's import closure, each module as bytecode, and a manifest naming them;
    # nothing the page does not reach is shipped.
    members, chunks, islands = frontage_rt.analyse(app, entry, installed)
    files = {}
    for name, path in members:
        data = frontage_rt.compile_module(path)
        files[name] = frontage_rt.hashed(name, data, "fbc")
        (runtime / files[name]).write_bytes(data)
    (runtime / frontage_rt.MANIFEST).write_bytes(
        frontage_rt.manifest([n for n, _ in members], entry, files, wasm_file, chunks, islands=islands)
    )
    if not (out / "_headers").exists():
        (out / "_headers").write_text(frontage_rt.HEADERS)

    page = out / "index.html"
    if page.exists():
        html = strip_pyscript(page.read_text())
        if "data-fr-boot" not in html:
            tag = boot_tag(entry, declarations=declarations)
            html = html.replace("</body>", f"{tag}\n</body>") if "</body>" in html else html + f"\n{tag}\n"
        else:
            html = declare(html, declarations)
    else:
        html = PAGE.format(title=app.name, tag=boot_tag(entry, declarations=declarations))
    # Preload hints: the boot and the glue as modules, the wasm as a fetch, all in flight
    # before the parser reaches the boot tag.
    hints = [
        '<link rel="modulepreload" href="./_frontage/boot.js">',
        '<link rel="modulepreload" href="./_frontage/glue.js">',
        f'<link rel="preload" href="./_frontage/{wasm_file}" as="fetch" crossorigin>',
    ]
    if tailwind:
        styles = styles + [build_tailwind(app, out, quiet=quiet)]
    for link in hints + styles:
        if link not in html:
            html = html.replace("</head>", f"  {link}\n</head>") if "</head>" in html else link + html
    page.write_text(html)

    if not quiet:
        total = sum(p.stat().st_size for p in out.rglob("*") if p.is_file())
        names = ", ".join(c.name for c in installed)
        extra = f", components: {names}" if installed else ""
        # Named rather than silent: an app that imports a component in a way the scan cannot
        # see would otherwise fail in the browser with no clue where the module went.
        extra += f" (installed but not imported, so not shipped: {', '.join(skipped)})" if skipped else ""
        print(f"{out}: entry {entry}, {len(members)} modules{extra}, {total:,} bytes")
    return out


TAILWIND_INPUT = "tailwind.css"
TAILWIND_OUTPUT = "tailwind.out.css"


def build_tailwind(app, out, quiet=False):
    """Run Tailwind over the app and write the stylesheet into the build; returns the link.

    The app directory is what Tailwind scans, `.py` included — a class name in a template
    string is a class name in a file, which is all its scanner asks for. The input file is
    the app's own `tailwind.css` (created with `@import "tailwindcss";` if it is not there,
    the same starter `frontage tailwind` writes), so the two commands cannot disagree about
    what the configuration is.
    """
    import subprocess

    from . import tailwind as tailwind_cli

    source = Path(app) / TAILWIND_INPUT
    if not source.exists():
        source.write_text(tailwind_cli.STARTER)
        if not quiet:
            print(f"created {source} with {tailwind_cli.STARTER.strip()}")
    target = Path(out) / TAILWIND_OUTPUT
    command = [str(tailwind_cli.binary(quiet=quiet)), "--input", str(source), "--output", str(target), "--minify"]
    run = subprocess.run(command, capture_output=True, text=True, cwd=str(app))
    if run.returncode != 0:
        raise SystemExit(f"error: tailwind failed: {run.stderr.strip() or run.stdout.strip()}")
    # The copy of the *input* that came in with the app's files is not a stylesheet the page
    # wants; the generated one beside it is.
    stale = Path(out) / TAILWIND_INPUT
    if stale.exists():
        stale.unlink()
    if not quiet:
        print(f"{target}: {target.stat().st_size:,} bytes of Tailwind")
    return f'<link rel="stylesheet" href="./{TAILWIND_OUTPUT}">'


def main(argv=None):
    parser = argparse.ArgumentParser(prog=f"{PROG} build", description=__doc__)
    parser.add_argument("app", help="the app directory")
    parser.add_argument("--out", default="", help="where to write (default: dist/<app>)")
    parser.add_argument("--entry", default="", help="the module that mounts (default: inferred)")
    parser.add_argument(
        "--component",
        action="append",
        default=[],
        metavar="NAME=PATH",
        help="a component package not installed yet, for developing one (repeatable)",
    )
    parser.add_argument(
        "--tailwind",
        action="store_true",
        help="generate the Tailwind stylesheet for this app and link it in the page",
    )
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)
    local = []
    for item in args.component:
        name, _, path = item.partition("=")
        if not path:
            print(f"error: --component wants NAME=PATH, not {item!r}", file=sys.stderr)
            return 2
        local.append(Component(name, path))
    try:
        # An explicit --component replaces discovery, so a component under development is
        # tested as itself rather than alongside an older installed copy of the same name.
        build(args.app, args.out, args.entry, quiet=args.quiet, components=local or None, tailwind=args.tailwind)
    except SystemExit as exc:
        print(exc, file=sys.stderr)
        return 2
    return 0
