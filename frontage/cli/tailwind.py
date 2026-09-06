"""`python -m frontage tailwind`: Tailwind CSS with nothing to install.

Downloads Tailwind's standalone CLI (one binary, no Node) into the cache the first time, then
runs it over the project: every non-ignored text file, `.py` included, is scanned for class
names, and the CSS for the ones found is written to the output file the page links. A missing
input file is created with `@import "tailwindcss";`, which is the whole configuration."""

import argparse
import os
import platform
import stat
import subprocess
import sys
import urllib.request
from pathlib import Path

from . import PROG
from ._cache import cache_dir

VERSION = "4.3.3"
RELEASES = "https://github.com/tailwindlabs/tailwindcss/releases/download"
STARTER = '@import "tailwindcss";\n'


def asset_name(system=None, machine=None):
    """The release asset for this platform, e.g. `tailwindcss-macos-arm64`."""
    system = (system or platform.system()).lower()
    machine = (machine or platform.machine()).lower()
    arch = "arm64" if machine in ("arm64", "aarch64") else "x64"
    if system == "darwin":
        return f"tailwindcss-macos-{arch}"
    if system == "windows":
        return f"tailwindcss-windows-{arch}.exe"
    return f"tailwindcss-linux-{arch}"


def binary(version=VERSION, quiet=False):
    """The CLI binary for this platform, downloaded on first use."""
    name = asset_name()
    path = cache_dir("tailwind", version) / name
    if path.exists():
        return path
    url = f"{RELEASES}/v{version}/{name}"
    if not quiet:
        print(f"fetching {url}")
    data = urllib.request.urlopen(url, timeout=300).read()
    partial = path.with_suffix(".part")
    partial.write_bytes(data)
    partial.chmod(partial.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    os.replace(partial, path)
    return path


def main(argv=None):
    parser = argparse.ArgumentParser(prog=f"{PROG} tailwind", description=__doc__)
    parser.add_argument(
        "--input",
        default="tailwind.css",
        help="the CSS with @import/@theme (default: tailwind.css, created if missing)",
    )
    parser.add_argument(
        "--output", default="tailwind.out.css", help="where the generated CSS goes (default: tailwind.out.css)"
    )
    parser.add_argument("--watch", action="store_true", help="keep running and rebuild on every change")
    parser.add_argument("--minify", action="store_true", help="minify the output")
    parser.add_argument("--version", default=VERSION, help=f"Tailwind release to use (default: {VERSION})")
    args = parser.parse_args(argv)
    source = Path(args.input)
    if not source.exists():
        source.write_text(STARTER)
        print(f"created {source} with {STARTER.strip()}")
    try:
        cli = binary(args.version)
    except OSError as exc:
        print(f"error: could not fetch Tailwind {args.version}: {exc}", file=sys.stderr)
        return 2
    command = [str(cli), "--input", str(source), "--output", args.output]
    if args.watch:
        command.append("--watch")
    if args.minify:
        command.append("--minify")
    try:
        return subprocess.call(command)
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
