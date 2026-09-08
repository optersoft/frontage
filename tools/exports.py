"""Write `frontage/__init__.pyi` from `frontage/_exports.py`.

The package resolves its public names lazily (PEP 562), so a page loads only the modules it
reaches. An editor and `ty` cannot see through that, and the stub is what they read instead —
one line per name, from the same table the runtime uses, so the two cannot drift.

    uv run python tools/exports.py            # write it
    uv run python tools/exports.py --check    # fail if it is out of date (the gate does this)
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from frontage._exports import EXPORTS  # noqa: E402

HEADER = """# Generated from _exports.py by `tools/exports.py`: the static view of the lazy package,
# for editors and ty.
"""


def stub():
    """Every public name as its own import line, sorted the way isort sorts them, plus the two
    things `__init__.py` defines beside the table."""
    pairs = [(module, name) for name, module in EXPORTS.items()]
    pairs.append(("version", "__version__"))
    lines = [HEADER]
    lines += [f"from .{module} import {name} as {name}" for module, name in sorted(pairs)]
    lines.append("")
    lines.append("__all__: list[str]")
    return "\n".join(lines) + "\n"


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    target = ROOT / "frontage" / "__init__.pyi"
    text = stub()
    if "--check" in argv:
        if target.read_text() != text:
            print(f"{target} is out of date: run `uv run python tools/exports.py`")
            return 1
        return 0
    target.write_text(text)
    print(f"{target}: {len(EXPORTS)} names")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
