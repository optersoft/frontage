"""The command line behind `python -m frontage`. Stdlib only; runs on the developer's CPython,
never in the browser (the package's browser files are the top-level modules only).

    python -m frontage build APP [--out DIR] [--entry NAME]
    python -m frontage prerender APP [--out DIR] [--route /path ...] [--entry app.py]
    python -m frontage tailwind [--input tailwind.css] [--output tailwind.out.css] [--watch] [--minify]
    python -m frontage check PATH...
    python -m frontage schema MODULE:Model... [--json FILE] [--ref POINTER] [-o FILE]
    python -m frontage lsp [--stdio]
    python -m frontage runtime
    python -m frontage serve [DIR] [--port 8000] [--watch DIR] [--open]
"""

import sys

# How the command line was invoked, for usage lines: `frontage` (the console script that a
# `pip install frontage` puts on PATH) or `python -m frontage`.
PROG = "python -m frontage"

USAGE = """usage: {prog} <command> [options]

commands:
  build      compile an app and copy it with the runtime into a directory that runs anywhere
  prerender  build, then write each route as finished HTML that the browser hydrates
  site       a directory of pages as a directory of files: file routing, layouts, endpoints
  tailwind   run the Tailwind CSS standalone CLI over the project (downloaded once)
  check      flag code a template will reject (lambda in a t-string, html(f"…"))
  schema     Pydantic models or a JSON Schema in, a `frontage.schema` module out
  lsp        the language server: what an editor knows about html(t"…")
  serve      serve a directory and swap the page's modules whenever a file changes
  runtime    where the runtime's files and its compiler are (fetching the compiler)
  version    print the package version

`{prog} <command> --help` for each command's options."""


def usage():
    return USAGE.format(prog=PROG)


def script():
    """The `frontage` console script (pyproject `[project.scripts]`)."""
    global PROG
    PROG = "frontage"
    return main()


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(usage())
        return 0
    command, rest = argv[0], argv[1:]
    if command in ("version", "--version"):
        from frontage.version import __version__

        print(__version__)
        return 0
    if command == "build":
        from .build import main as run
    elif command == "prerender":
        from .prerender import main as run
    elif command == "site":
        from .site import main as run
    elif command == "tailwind":
        from .tailwind import main as run
    elif command == "check":
        from .check import main as run
    elif command == "lsp":
        from frontage.lsp.server import main as run
    elif command == "runtime":
        from .frontage_rt import main as run
    elif command == "serve":
        from .serve import main as run
    elif command == "schema":
        from frontage.schema._compile import main as run
    else:
        print(f"error: unknown command {command!r}\n\n{usage()}", file=sys.stderr)
        return 2
    return run(rest)
