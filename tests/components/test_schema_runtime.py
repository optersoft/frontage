"""The rule a component can break while installing and importing perfectly: its Python must run
on the runtime. This compiles the package with `fpy`, loads it into the wasm the browser boots,
under node, and runs it — with no browser in the way.

Skipped when `node` is not on PATH; CI has it."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

HERE = Path(__file__).parent
ROOT = HERE.parent.parent
PACKAGE = ROOT / "frontage" / "schema"

SMOKE = r"""
import json
from frontage.schema import *
from frontage.schema.jsonschema import from_json_schema
User = record(("id", integer(ge=0)), ("name", text(min=1, max=100)), ("email", email()),
              ("age", optional(integer(gt=0, le=150)), None), ("when", iso_datetime()), ("uid", uuid()))
rows = json.loads(ROWS)
value, errors = array(User).validate(rows)
out = {"errors": errors, "n": len(value), "age0": value[0]["age"]}
out["coerced"] = User.parse({"id": "3", "name": "x", "email": "a@b.co", "age": "", "when": "2026-09-07T21:17Z",
                             "uid": "123e4567-e89b-12d3-a456-426614174000"}, coerce=True)["id"]
out["bad"] = array(User).validate(rows, sample=1)[1]
back = from_json_schema(User.json_schema())
out["repr"] = sorted(repr(f) for f in back.fields) == sorted(repr(f) for f in User.fields)
out["email"] = [email().is_valid(s) for s in ("a@b.co", "a@@b.c", "üser@b.co")]
out["dates"] = [iso_date().is_valid(s) for s in ("2026-09-07", "2026-02-30")]
try:
    text(pattern="^a{2}$")
    out["brace"] = "accepted"
except ValueError:
    out["brace"] = "refused"
print("RESULT " + json.dumps(out))
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node")
def test_the_package_runs_on_the_shipped_runtime(tmp_path):
    from frontage.cli import build, frontage_rt

    rows = [
        {
            "id": i,
            "name": "n%d" % i,
            "email": "u%d@example.com" % i,
            "when": "2026-09-07T21:17:05+02:00",
            "uid": "123e4567-e89b-12d3-a456-426614174000",
        }
        for i in range(50)
    ]
    rows[0]["age"] = 30
    rows[49]["email"] = "broken"
    main = tmp_path / "smoke.py"
    main.write_text("ROWS = %r\n" % json.dumps(rows) + SMOKE)
    modules = frontage_rt.closure(tmp_path, "smoke", components=list(build.discover()))
    args = []
    for name, path in modules:
        if name == "smoke":
            continue
        out = tmp_path / f"{name}.fbc"
        out.write_bytes(frontage_rt.compile_module(path))
        args.append(f"{name}={out}")
    assert any(n.startswith("frontage.schema") for n, _ in modules), "the package was not reached"
    entry = tmp_path / "smoke.fbc"
    entry.write_bytes(frontage_rt.compile_module(main))
    run = subprocess.run(
        ["node", str(ROOT / "rust" / "web" / "run.mjs"), str(entry), *args], capture_output=True, text=True, timeout=120
    )
    assert run.returncode == 0, run.stderr
    line = next(line for line in run.stdout.splitlines() if line.startswith("RESULT "))
    out = json.loads(line[7:])
    assert out["n"] == 50 and out["age0"] == 30
    assert out["errors"] and "email" in json.dumps(out["errors"])
    assert out["coerced"] == 3
    assert out["repr"] is True
    assert out["email"] == [True, False, False] or out["email"] == [True, False, True]
    assert out["dates"] == [True, False]
    assert out["brace"] in ("accepted", "refused")
