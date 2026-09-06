"""The academy's Examples page is generated from examples/ (tools/academy_examples.py)."""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("academy_examples", ROOT / "tools" / "academy_examples.py")
assert spec is not None and spec.loader is not None
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def test_every_example_becomes_one_pyscript_frame_naming_the_wheel():
    page = mod.render("9.9.9", today="2026-09-06")
    assert page.startswith("---\ntitle: Examples\nupdated: 2026-09-06\n")
    assert page.count("::: pyscript ") == len(mod.EXAMPLES) == 8
    assert page.count('packages="https://frontage.optersoft.com/dist/frontage-9.9.9-py3-none-any.whl"') == 8
    assert "## Counter" in page and 'title="examples/counter/counter.py"' in page
    counter = page.split("## Counter")[1].split("## ")[0]
    assert '<div id="app">' in counter and "from frontage import" in counter and '"""' not in counter


def test_docstring_becomes_prose_and_leaves_the_code():
    prose, code = mod.split_docstring('"""First line.\n\nSecond paragraph."""\nx = 1\n')
    assert prose == "First line." and code == "x = 1\n"
    assert mod.split_docstring("x = 1\n") == ("", "x = 1\n")
    assert (
        mod.body_of('<html><body>\n<div id="app">Loading…</div>\n<script>x</script></body></html>')
        == '<div id="app">Loading…</div>'
    )
