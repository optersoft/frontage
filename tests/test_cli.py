"""`python -m frontage`: check, export (no network), tailwind's platform table."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from frontage.cli import check, export, main, tailwind

ROOT = Path(__file__).resolve().parents[1]


def test_check_flags_a_parenthesised_lambda_in_a_template_string():
    # The rule's real subject: CPython accepts this and MicroPython does not.
    src = 'from frontage import html\nx = html(t"<b on:click={(lambda ev: None)}>hi</b>")\n'
    found = check.check_source(src, "app.py")
    assert [(p, line) for p, line, _ in found] == [("app.py", 2)]
    assert "lambda" in found[0][2] and "name the function" in found[0][2]


def test_a_bare_lambda_in_a_template_string_is_a_parse_error_here_too():
    # CPython 3.14 rejects `{lambda ev: None}` outright (the `:` opens a format spec), so this
    # never reaches the rule; the message still says "lambda", which is what the reader needs.
    src = 'from frontage import html\nx = html(t"<b on:click={lambda ev: None}>hi</b>")\n'
    found = check.check_source(src, "app.py")
    assert [(p, line) for p, line, _ in found] == [("app.py", 2)]
    assert "cannot parse" in found[0][2] and "lambda" in found[0][2]


def test_check_flags_html_of_an_f_string():
    src = 'from frontage import html\nname = "x"\nx = html(f"<b>{name}</b>")\n'
    found = check.check_source(src, "app.py")
    assert len(found) == 1 and "t-string" in found[0][2]


def test_check_accepts_named_functions_and_t_strings():
    src = 'from frontage import html\n\ndef f(ev):\n    pass\n\nx = html(t"<b on:click={f}>{lambda: 1}</b>")\n'
    # The lambda here is in the t-string, so it *is* flagged; the named handler is not.
    assert len(check.check_source(src)) == 1
    assert check.check_source('def f():\n    return lambda: 1\nx = html(t"<b>{f}</b>")\n') == []


def test_check_reads_markdown_code_blocks(tmp_path):
    md = tmp_path / "page.md"
    md.write_text('# Title\n\n```py\nfrom frontage import html\n```\n\ntext\n\n```python\nhtml(t"{lambda: 1}")\n```\n')
    found = check.check_path(md)
    assert [line for _, line, _ in found] == [10]


def test_check_command_exit_status(tmp_path, capsys):
    good = tmp_path / "good.py"
    good.write_text("x = 1\n")
    assert main(["check", str(good)]) == 0
    bad = tmp_path / "bad.py"
    bad.write_text('y = html(t"{lambda: 1}")\n')
    assert main(["check", str(tmp_path)]) == 1
    assert f"{bad}:1:" in capsys.readouterr().out


def test_export_without_the_bundle(tmp_path):
    out = export.export(ROOT / "examples" / "counter", tmp_path / "counter", bundle_pyscript=False)
    html = (out / "index.html").read_text()
    assert "https://pyscript.net/releases/" in html and " offline" not in html
    assert '"./pyscript.json"' in html
    config = json.loads((out / "pyscript.json").read_text())
    assert config["files"]["./frontage/view.py"] == "frontage/view.py"
    assert "./frontage/__main__.py" not in config["files"]
    assert (out / "frontage" / "reactive.py").exists() and not (out / "frontage" / "cli").exists()
    assert (out / "counter.py").exists()


THREE_FILE_HTML = """<!DOCTYPE html>
<html><head>
  <link rel="stylesheet" href="https://pyscript.net/releases/{v}/core.css">
  <script type="module" src="https://pyscript.net/releases/{v}/core.js"></script>
</head><body><div id="app"></div>
<script type="mpy" src="./app.py" config="./pyscript.json"></script></body></html>
"""


def _three_file_app(tmp_path):
    """The academy's layout: PyScript from its CDN, the package as a wheel URL."""
    from frontage.cli import pyscript

    app = tmp_path / "app"
    app.mkdir()
    (app / "index.html").write_text(THREE_FILE_HTML.format(v=pyscript.VERSION))
    (app / "app.py").write_text("from frontage import html, mount\n")
    (app / "pyscript.json").write_text(
        json.dumps({"packages": ["https://frontage.optersoft.com/dist/frontage-0.4.0-py3-none-any.whl", "numpy"]})
    )
    return app


def test_export_drops_the_frontage_wheel_and_keeps_other_packages(tmp_path):
    out = export.export(_three_file_app(tmp_path), tmp_path / "out", bundle_pyscript=False)
    config = json.loads((out / "pyscript.json").read_text())
    assert config["packages"] == ["numpy"]
    assert config["files"]["./frontage/view.py"] == "frontage/view.py"
    html = (out / "index.html").read_text()
    assert "https://pyscript.net/releases/" in html and "offline" not in html


def test_export_drops_an_empty_packages_key(tmp_path):
    app = _three_file_app(tmp_path)
    (app / "pyscript.json").write_text(json.dumps({"packages": ["./frontage-0.4.0-py3-none-any.whl"]}))
    out = export.export(app, tmp_path / "out", bundle_pyscript=False)
    assert "packages" not in json.loads((out / "pyscript.json").read_text())


def test_export_with_the_bundle_rewrites_the_cdn_links(tmp_path):
    bundles = sorted(ROOT.glob("tools/pyscript/*/pyscript"))
    if not bundles:
        pytest.skip("no local PyScript: run `mk pyscript.fetch`")
    out = export.export(_three_file_app(tmp_path), tmp_path / "out", pyscript_dir=bundles[-1])
    html = (out / "index.html").read_text()
    assert 'src="./pyscript/core.js" offline' in html and '"./pyscript/core.css"' in html
    assert "pyscript.net" not in html
    assert (out / "pyscript" / "core.js").exists()


def test_export_refuses_an_output_inside_the_app(tmp_path):
    app = tmp_path / "app"
    app.mkdir()
    (app / "index.html").write_text("<div id=app></div>")
    try:
        export.export(app, app / "build", bundle_pyscript=False)
    except ValueError as exc:
        assert "inside" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_tailwind_asset_names():
    assert tailwind.asset_name("Darwin", "arm64") == "tailwindcss-macos-arm64"
    assert tailwind.asset_name("Linux", "x86_64") == "tailwindcss-linux-x64"
    assert tailwind.asset_name("Linux", "aarch64") == "tailwindcss-linux-arm64"
    assert tailwind.asset_name("Windows", "AMD64") == "tailwindcss-windows-x64.exe"


def test_module_entry_point_prints_usage_and_version():
    usage = subprocess.run([sys.executable, "-m", "frontage"], capture_output=True, text=True, cwd=ROOT)
    assert usage.returncode == 0 and "export" in usage.stdout and "tailwind" in usage.stdout
    version = subprocess.run([sys.executable, "-m", "frontage", "version"], capture_output=True, text=True, cwd=ROOT)
    from frontage import __version__

    assert version.stdout.strip() == __version__
    assert main(["nonsense"]) == 2
