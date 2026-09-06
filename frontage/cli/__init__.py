"""The command line behind `python -m frontage`. Stdlib only; runs on the developer's CPython,
never in the browser (the package's browser files are the top-level modules only).

    python -m frontage export APP [--out DIR] [--no-pyscript] [--pyscript DIR]
    python -m frontage tailwind [--input tailwind.css] [--output tailwind.out.css] [--watch] [--minify]
    python -m frontage check PATH...
    python -m frontage pyscript [--dest DIR]
"""

import sys

USAGE = """usage: python -m frontage <command> [options]

commands:
  export     copy an app, the package and PyScript into a directory that runs anywhere
  tailwind   run the Tailwind CSS standalone CLI over the project (downloaded once)
  check      flag code MicroPython or a template will reject (lambda in a t-string, html(f"…"))
  pyscript   fetch PyScript's offline bundle
  version    print the package version

`python -m frontage <command> --help` for each command's options."""


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(USAGE)
        return 0
    command, rest = argv[0], argv[1:]
    if command in ("version", "--version"):
        from frontage.version import __version__

        print(__version__)
        return 0
    if command == "export":
        from .export import main as run
    elif command == "tailwind":
        from .tailwind import main as run
    elif command == "check":
        from .check import main as run
    elif command == "pyscript":
        from .pyscript import main as run
    else:
        print(f"error: unknown command {command!r}\n\n{USAGE}", file=sys.stderr)
        return 2
    return run(rest)
