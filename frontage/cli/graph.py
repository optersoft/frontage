"""The import graph of an app, read with `ast` on CPython: what a page reaches, and nothing else.

`frontage build` packs the closure of what the entry imports — of the app, of the framework,
of the components — instead of the whole framework and every module of every component the
app touches. This module answers the question; `build.py` acts on it.

The walk never imports anything. An app's Python, and a component's, is written for the
browser, and running it here would be the wrong interpreter. It reads every `import` form at
any depth (function-local imports count: `router.py` reaches `reactive.on_mount` inside a
method), resolves `from frontage import Signal` through `_exports.py` — the table the package's
own `__getattr__` reads, so the build's reading of a name and the interpreter's are one data
structure — and treats `import frontage` followed by `frontage.Signal` the same way.

What it cannot see it says so: `__import__(f"pages.{name}")` is invisible, like a variable
`import()` is to every JavaScript bundler. The escape hatch is a comment in any module,

    # frontage: include pages.map, reports.*

or `--include` on the command line. A route that names a module — `Route("/map",
lazy="pages.map")` — is a chunk root: reached, but packed apart (`build.py` §chunks).
"""

import ast
import re
from pathlib import Path

from frontage._exports import EXPORTS

from . import frontage_rt

FRAMEWORK = "frontage"

# A comment line anywhere in a module; several names, `pkg.*` for a whole package.
_INCLUDE = re.compile(r"^[ \t]*#[ \t]*frontage:[ \t]*include[ \t]+(.+?)[ \t]*$", re.M)


def _without_templates(source):
    """`source` with every `t"…"` literal replaced by an empty triple-quoted string of the
    same height, or None when there is none to replace.

    The lexer is the language server's, which reads t-strings as text rather than through
    `ast` — that is the whole point here, since the interpreter doing the reading may be the
    one that cannot parse them.
    """
    from ..lsp.scanner import scan_templates

    found = scan_templates(source)
    if not found:
        return None
    out = []
    at = 0
    for template in found:
        out.append(source[at : template.start])
        out.append('"""' + "\n" * source.count("\n", template.start, template.end) + '"""')
        at = template.end
    out.append(source[at:])
    return "".join(out)


def _dotted(relative):
    """`pages/map.py` → `pages.map`; `pages/__init__.py` → `pages`."""
    parts = list(relative.with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


class Graph:
    """Every module a build could pack, by dotted name, and the edges between them.

    `modules` maps a name to its file. Three families: the app's own (`app`, `pages.map`),
    the framework's (`frontage`, `frontage.reactive`, …) and the components' (`frontage.chart`,
    `frontage.chart.plot`, or a third party's `frontage_gantt.widget`).
    """

    def __init__(self, app, components=(), framework=None):
        self.app = Path(app)
        self.modules = {}
        self.app_modules = set()
        self.framework_modules = set()
        self.component_modules = {}  # dotted name → the Component it belongs to
        self._deps = {}
        self._parsed = {}

        for path in sorted(self.app.rglob("*.py")):
            relative = path.relative_to(self.app)
            if any(
                part in ("_frontage", "__pycache__", "dist", "www") or part.startswith(".") for part in relative.parts
            ):
                continue
            name = _dotted(relative)
            self.modules[name] = path
            self.app_modules.add(name)

        package = Path(framework) if framework else frontage_rt.ROOT / "frontage"
        self.modules[FRAMEWORK] = package / "__init__.py"
        self.framework_modules.add(FRAMEWORK)
        for path in frontage_rt.browser_modules(package):
            if path.name == "__init__.py":
                continue
            name = f"{FRAMEWORK}.{path.stem}"
            self.modules[name] = path
            self.framework_modules.add(name)

        for component in components:
            for archive_name, path in component.modules():
                name = _dotted(Path(archive_name))
                self.modules[name] = path
                self.component_modules[name] = component

    # -- reading one module -----------------------------------------------------------------

    def _tree(self, name):
        if name not in self._parsed:
            source = self.modules[name].read_text()
            try:
                tree = ast.parse(source, filename=str(self.modules[name]))
            except SyntaxError as exc:
                # Template strings are Python 3.14, and a build host may be older. An import
                # cannot live inside one, so blank them and read the file that is left: the
                # walk sees every import, and a real syntax error still reports its line.
                blanked = _without_templates(source)
                if blanked is None:
                    raise SystemExit(f"error: {self.modules[name]}: {exc.msg} (line {exc.lineno})") from exc
                try:
                    tree = ast.parse(blanked, filename=str(self.modules[name]))
                except SyntaxError:
                    raise SystemExit(f"error: {self.modules[name]}: {exc.msg} (line {exc.lineno})") from exc
            self._parsed[name] = (tree, source)
        return self._parsed[name]

    def _package_of(self, name):
        """The package a module's relative imports resolve against."""
        path = self.modules[name]
        return name if path.name == "__init__.py" else name.rpartition(".")[0]

    def _known(self, dotted):
        return dotted in self.modules

    def _add_import(self, found, dotted):
        """`import a.b.c` imports `a`, then `a.b`, then `a.b.c`; each known one is an edge."""
        parts = dotted.split(".")
        for i in range(1, len(parts) + 1):
            candidate = ".".join(parts[:i])
            if self._known(candidate):
                found.add(candidate)

    def deps(self, name):
        """The modules `name` imports, resolved to names in this graph; the rest is stdlib,
        the browser's `js`, or a JavaScript module a component registered — not ours to pack."""
        if name in self._deps:
            return self._deps[name]
        found = set()
        tree, source = self._tree(name)
        package = self._package_of(name)
        bare_frontage = False  # `import frontage`, then `frontage.X`

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self._add_import(found, alias.name)
                    if alias.name == FRAMEWORK:
                        bare_frontage = True
            elif isinstance(node, ast.ImportFrom):
                base = node.module or ""
                if node.level:
                    root = package.split(".")
                    if node.level > 1:
                        root = root[: len(root) - (node.level - 1)]
                    base = ".".join(root + ([base] if base else []))
                if base:
                    self._add_import(found, base)
                for alias in node.names:
                    if alias.name == "*":
                        continue
                    if base == FRAMEWORK and alias.name in EXPORTS:
                        found.add(f"{FRAMEWORK}.{EXPORTS[alias.name]}")
                    elif base and self._known(f"{base}.{alias.name}"):
                        found.add(f"{base}.{alias.name}")
                    elif not base and self._known(alias.name):
                        found.add(alias.name)

        if bare_frontage:
            unresolved = False
            bases = set()  # the `frontage` names that are the object of an attribute access
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == FRAMEWORK:
                    bases.add(id(node.value))
                    attr = node.attr
                    if attr in EXPORTS:
                        found.add(f"{FRAMEWORK}.{EXPORTS[attr]}")
                    elif self._known(f"{FRAMEWORK}.{attr}"):
                        found.add(f"{FRAMEWORK}.{attr}")
                    elif attr not in ("__version__", "__all__"):
                        unresolved = True
            for node in ast.walk(tree):
                # `frontage` used as a value — `getattr(frontage, name)`, passed along, aliased —
                # is an access the walk cannot attribute.
                if isinstance(node, ast.Name) and node.id == FRAMEWORK and isinstance(node.ctx, ast.Load):
                    if id(node) not in bases:
                        unresolved = True
            if unresolved:
                # `getattr(frontage, name)` or a name we cannot attribute: the whole package.
                found.update(self.framework_modules)

        for match in _INCLUDE.finditer(source):
            for item in match.group(1).split(","):
                found.update(self.expand(item.strip()))

        self._deps[name] = found
        return found

    def expand(self, pattern):
        """`pages.map` → itself; `pages.*` → every module under `pages`."""
        if pattern.endswith(".*"):
            prefix = pattern[:-1]
            return {n for n in self.modules if n.startswith(prefix) or n == pattern[:-2]}
        return {pattern} if self._known(pattern) else set()

    # -- closures and chunk roots -------------------------------------------------------------

    def closure(self, roots, stop=()):
        """Every module reachable from `roots`, never crossing into `stop`.

        A module's packages come with it: `import pages.map` needs `pages` to exist, and a
        `pages/__init__.py` that imports nothing is reached by no edge in this graph — which
        made a chunk whose root sat in a package unimportable in the page.
        """
        seen, todo = set(), [r for r in roots if self._known(r)]
        stop = set(stop)
        while todo:
            name = todo.pop()
            if name in seen or name in stop:
                continue
            seen.add(name)
            todo.extend(d for d in self.deps(name) if d not in seen)
            todo.extend(p for p in self._packages(name) if p not in seen)
        return seen

    def _packages(self, name):
        """The packages `name` lives in, outermost first, that this graph knows."""
        parts = name.split(".")[:-1]
        return [p for i in range(1, len(parts) + 1) if self._known(p := ".".join(parts[:i]))]

    def lazy_roots(self, within):
        """The modules named by `Route(…, lazy="pages.map")`, `chunks.load("pages.map")` or
        `island("comments:thread")` in `within`, as `(module, [modules that name it])` — the
        chunk roots of the app.

        An island named by a *function* is not one: the module that places it imports it, so
        it is in the first payload already. Naming it by a string is how a page says the
        island is worth its own request — the chart nobody scrolls to.
        """
        roots = {}
        for name in within:
            tree, _ = self._tree(name)
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                callee = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else ""
                spec = None
                if callee == "Route":
                    for kw in node.keywords:
                        if kw.arg == "lazy" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                            spec = kw.value.value
                elif callee in ("load", "prefetch", "island") and node.args and isinstance(node.args[0], ast.Constant):
                    if isinstance(node.args[0].value, str) and self._known(node.args[0].value.partition(":")[0]):
                        spec = node.args[0].value
                if spec:
                    module = spec.partition(":")[0]
                    if self._known(module):
                        roots.setdefault(module, []).append(name)
        return roots

    def uses_islands(self, within):
        """Does any module here place an `island`? What decides whether a prerendered page
        gets a boot tag and an entry to run, or the island loader and nothing else."""
        for name in within:
            tree, _ = self._tree(name)
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    func = node.func
                    callee = (
                        func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else ""
                    )
                    if callee == "island":
                        return True
        return False

    def size(self, names):
        return sum(self.modules[n].stat().st_size for n in names if n in self.modules)
