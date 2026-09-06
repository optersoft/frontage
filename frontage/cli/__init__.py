"""The command line behind `python -m frontage`. Stdlib only; runs on the developer's CPython,
never in the browser (the package's browser files are the top-level modules only).

    python -m frontage export APP [--out DIR] [--no-pyscript] [--pyscript DIR]
    python -m frontage prerender APP [--out DIR] [--route /path ...] [--entry app.py]
    python -m frontage tailwind [--input tailwind.css] [--output tailwind.out.css] [--watch] [--minify]
    python -m frontage check PATH...
    python -m frontage lsp [--stdio]
    python -m frontage pyscript [--dest DIR]
    python -m frontage serve [DIR] [--port 8000] [--watch DIR] [--open]
"""

import sys

# How the command line was invoked, for usage lines: `frontage` (the console script that a
# `pip install frontage` puts on PATH) or `python -m frontage`.
PROG = "python -m frontage"

USAGE = """usage: {prog} <command> [options]

commands:
  export     copy an app, the package and PyScript into a directory that runs anywhere
  prerender  export, then write each route as finished HTML that the browser hydrates
  tailwind   run the Tailwind CSS standalone CLI over the project (downloaded once)
  check      flag code MicroPython or a template will reject (lambda in a t-string, html(f"…"))
  lsp        the language server: what an editor knows about html(t"…")
  serve      serve a directory and reload the page whenever a file changes
  pyscript   fetch PyScript's offline bundle
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
    if command == "export":
        from .export import main as run
    elif command == "prerender":
        from .prerender import main as run
    elif command == "tailwind":
        from .tailwind import main as run
    elif command == "check":
        from .check import main as run
    elif command == "lsp":
        from frontage.lsp.server import main as run
    elif command == "pyscript":
        from .pyscript import main as run
    elif command == "serve":
        from .serve import main as run
    else:
        print(f"error: unknown command {command!r}\n\n{usage()}", file=sys.stderr)
        return 2
    return run(rest)
