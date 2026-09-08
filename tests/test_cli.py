"""`python -m frontage`: check, the entry point, tailwind's platform table."""

import subprocess
import sys
from pathlib import Path

from frontage.cli import check, main, tailwind

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


def test_tailwind_asset_names():
    assert tailwind.asset_name("Darwin", "arm64") == "tailwindcss-macos-arm64"
    assert tailwind.asset_name("Linux", "x86_64") == "tailwindcss-linux-x64"
    assert tailwind.asset_name("Linux", "aarch64") == "tailwindcss-linux-arm64"
    assert tailwind.asset_name("Windows", "AMD64") == "tailwindcss-windows-x64.exe"


def test_module_entry_point_prints_usage_and_version():
    usage = subprocess.run([sys.executable, "-m", "frontage"], capture_output=True, text=True, cwd=ROOT)
    assert usage.returncode == 0 and "build" in usage.stdout and "tailwind" in usage.stdout
    version = subprocess.run([sys.executable, "-m", "frontage", "version"], capture_output=True, text=True, cwd=ROOT)
    from frontage import __version__

    assert version.stdout.strip() == __version__
    assert main(["nonsense"]) == 2
