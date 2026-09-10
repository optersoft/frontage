"""Finding the server binary, and running it.

`pip install frontage-api` gives you a library and no server: the server is Rust — the VM
your handlers run on is compiled into it — so it ships as a release asset per platform, the
way `fpy` does, and this fetches the one for this machine on first use.

    uvx --from frontage-api frontage-api app.py --addr 127.0.0.1:8000

⚠ **Underscored, so it stays on CPython.** Nothing in here can run on the runtime it starts.

⚠ **`shutil.which("frontage-api")` is not in the search order, and must not be**: the wheel
installs a console script under exactly that name, so a PATH lookup finds *this* and execs
itself forever. `FRONTAGE_API_BIN` is the way to name one explicitly.
"""

import os
import platform
import stat
import sys
from pathlib import Path

__all__ = ["asset_name", "binary", "main"]

#: A checkout's own build, tried before anything is downloaded — `--profile api` first,
#: because that is the profile the release is built with and the one the gate needs.
PROFILES = ("api", "release", "debug")


def asset_name(system=None, machine=None):
    """The release asset for this platform, e.g. `frontage-api-macos-arm64`.

    No Windows: the consumers are fleet VMs and a laptop, and CI builds no such asset — so
    this says so here rather than letting a download 404 explain it.
    """
    system = (system or platform.system()).lower()
    machine = (machine or platform.machine()).lower()
    arch = "arm64" if machine in ("arm64", "aarch64") else "x64"
    if system == "darwin":
        return f"frontage-api-macos-{arch}"
    if system == "windows":
        raise SystemExit("error: there is no frontage-api build for Windows; build it from a checkout")
    return f"frontage-api-linux-{arch}"


def _checkout():
    """`rust/target/<profile>/frontage-api` in a source checkout, if this is one."""
    root = Path(__file__).resolve().parent.parent
    for profile in PROFILES:
        candidate = root / "rust" / "target" / profile / "frontage-api"
        if candidate.is_file():
            return candidate
    return None


def binary(quiet=False):
    """The server binary: `FRONTAGE_API_BIN`, a checkout's build, else the release asset for
    this version, downloaded once into the cache."""
    import urllib.request

    from frontage.cli._cache import cache_dir
    from frontage.cli.frontage_rt import asset_urls
    from frontage.version import __version__

    named = os.environ.get("FRONTAGE_API_BIN")
    if named:
        return Path(named)
    found = _checkout()
    if found:
        return found
    name = asset_name()
    path = cache_dir("frontage-api", __version__) / name
    if path.exists():
        return path
    data, last = None, None
    for url in asset_urls(name, quiet=quiet):
        if not quiet:
            print(f"fetching {url}", file=sys.stderr)
        try:
            data = urllib.request.urlopen(url, timeout=600).read()
            break
        except OSError as exc:
            last = exc
    if data is None:
        raise SystemExit(
            f"error: no frontage-api server for this platform ({last}); in a checkout run "
            "`cargo build --profile api -p frontage-api` in rust/, or set FRONTAGE_API_BIN"
        ) from None
    # Written aside and renamed, so two processes racing the first run cannot leave a
    # half-written file behind that every later run then tries to execute.
    partial = path.with_suffix(".part")
    partial.write_bytes(data)
    partial.chmod(partial.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    os.replace(partial, path)
    return path


def main(argv=None):
    """`frontage-api …`: hand the arguments straight to the binary.

    `execv`, not a subprocess: the server is the process from here on, so a signal reaches it
    directly and a supervisor sees one pid rather than a wrapper holding a child.
    """
    argv = list(sys.argv[1:] if argv is None else argv)
    path = binary()
    os.execv(str(path), [str(path), *argv])
