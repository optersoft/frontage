"""`python -m frontage build` and the runtime image behind it (no network, no browser)."""

import tarfile
from pathlib import Path

import pytest

from frontage.cli import build
from frontage.cli import micropython as mp

ROOT = Path(__file__).resolve().parents[1]

APP = "from frontage import Signal, h, mount\n\nmount(lambda: h.p('hi'), '#app')\n"


def write_app(tmp_path, **files):
    app = tmp_path / "app"
    app.mkdir()
    for name, text in files.items():
        (app / f"{name}.py").write_text(text)
    return app


# --- what ships ------------------------------------------------------------------------


def test_browser_modules_are_the_top_level_ones_without_dunder_main():
    names = {p.name for p in mp.browser_modules()}
    assert "__main__.py" not in names
    # debug.py ships: an app imports it to get the hydration report. The old pyscript.json
    # listed fifteen modules and left it out, which is why this is asserted rather than counted.
    assert "debug.py" in names
    assert {"reactive.py", "view.py", "dom.py", "runtime.py", "version.py"} <= names
    assert not any("/" in n for n in names)


def test_the_vendored_runtime_is_present_and_is_the_pinned_build():
    for name in mp.WANTED + ("boot.js", mp.IMAGE_NAME):
        assert (mp.RUNTIME_DIR / name).exists(), f"{name} missing: run `mk runtime.fetch`"
    # The pin is a single line; if it moves, the image and the tests move with it.
    assert mp.VERSION.startswith("1.28.")
    assert (mp.RUNTIME_DIR / "micropython.wasm").stat().st_size > 300_000


def test_the_framework_image_holds_every_browser_module(tmp_path):
    out, compiled = mp.image(tmp_path, quiet=True)
    with tarfile.open(out) as tf:
        members = tf.getnames()
    assert len(members) == len(mp.browser_modules())
    assert all(m.startswith("frontage/") for m in members)
    stems = {Path(m).stem for m in members}
    assert stems == {p.stem for p in mp.browser_modules()}
    if compiled:
        assert all(m.endswith(".mpy") for m in members)


def test_the_framework_image_is_reproducible(tmp_path):
    # mtime is pinned to 0 so the same sources give the same bytes; CI compares them rather
    # than trusting a timestamp, which a wheel install flattens anyway.
    first, _ = mp.image(tmp_path / "a", quiet=True)
    second, _ = mp.image(tmp_path / "b", quiet=True)
    assert first.read_bytes() == second.read_bytes()


# --- choosing the entry ----------------------------------------------------------------


def test_the_entry_is_the_module_that_mounts(tmp_path):
    app = write_app(tmp_path, helpers="X = 1\n", ui=APP)
    assert build.find_entry(app) == "ui"


def test_a_conventional_name_wins_when_several_modules_mount(tmp_path):
    app = write_app(tmp_path, app=APP, other=APP)
    assert build.find_entry(app) == "app"


def test_a_lone_module_is_the_entry_even_without_mount(tmp_path):
    app = write_app(tmp_path, thing="X = 1\n")
    assert build.find_entry(app) == "thing"


def test_an_ambiguous_directory_says_so_instead_of_guessing(tmp_path):
    app = write_app(tmp_path, one=APP, two=APP)
    with pytest.raises(SystemExit) as exc:
        build.find_entry(app)
    assert "one" in str(exc.value) and "two" in str(exc.value) and "--entry" in str(exc.value)


def test_an_empty_directory_says_so(tmp_path):
    app = tmp_path / "app"
    app.mkdir()
    with pytest.raises(SystemExit):
        build.find_entry(app)


# --- the built directory ---------------------------------------------------------------


def test_build_writes_a_page_that_boots_from_wasm(tmp_path):
    app = write_app(tmp_path, counter=APP)
    out = build.build(app, tmp_path / "out", quiet=True)

    for name in ("boot.js", "micropython.mjs", "micropython.wasm", "frontage.tar", "app.tar"):
        assert (out / "_frontage" / name).exists()

    page = (out / "index.html").read_text()
    assert 'data-fr-entry="counter"' in page and "data-fr-boot" in page
    assert "_frontage/boot.js" in page
    # Nothing of PyScript survives: no config, no core.js, no interpreter type attribute.
    assert "pyscript" not in page.lower()
    assert not (out / "pyscript.json").exists()


def test_the_app_image_holds_the_app_modules_as_source(tmp_path):
    app = write_app(tmp_path, counter=APP, helpers="X = 1\n")
    out = build.build(app, tmp_path / "out", quiet=True)
    with tarfile.open(out / "_frontage" / "app.tar") as tf:
        assert sorted(tf.getnames()) == ["counter.py", "helpers.py"]
        member = tf.extractfile("helpers.py")
        assert member is not None
        assert member.read() == b"X = 1\n"
    # The sources stay readable in the output too, which is the point of a teaching framework.
    assert (out / "counter.py").exists()


def test_an_existing_page_keeps_its_markup_and_gains_the_tag(tmp_path):
    app = write_app(tmp_path, counter=APP)
    (app / "index.html").write_text("<!DOCTYPE html>\n<body>\n<main id='app'>x</main>\n</body>\n")
    out = build.build(app, tmp_path / "out", quiet=True)
    page = (out / "index.html").read_text()
    assert "<main id='app'>x</main>" in page
    assert page.count("data-fr-boot") == 1


def test_a_page_that_already_declares_the_tag_is_left_alone(tmp_path):
    app = write_app(tmp_path, counter=APP)
    tag = build.boot_tag("counter")
    (app / "index.html").write_text(f"<!DOCTYPE html>\n<body>\n{tag}\n</body>\n")
    out = build.build(app, tmp_path / "out", quiet=True)
    assert (out / "index.html").read_text().count("data-fr-boot") == 1


def test_build_does_not_copy_a_previous_build(tmp_path):
    app = write_app(tmp_path, counter=APP)
    (app / "_frontage").mkdir()
    (app / "_frontage" / "stale.wasm").write_bytes(b"old")
    out = build.build(app, tmp_path / "out", quiet=True)
    assert not (out / "_frontage" / "stale.wasm").exists()


def test_an_unknown_entry_is_an_error(tmp_path):
    app = write_app(tmp_path, counter=APP)
    with pytest.raises(SystemExit) as exc:
        build.build(app, tmp_path / "out", entry="nope", quiet=True)
    assert "nope.py" in str(exc.value)
