"""The rule a component can break while installing and importing perfectly: its Python must run
on MicroPython. This loads the package's source into the interpreter frontage ships, under
node, and runs it — the same wasm the browser boots, with no browser in the way.

Skipped when `node` is not on PATH; CI has it."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

HERE = Path(__file__).parent
PACKAGE = HERE.parent / "frontage-schema" / "frontage_schema"
RUNTIME = HERE.parent.parent / "frontage" / "frontage" / "_runtime"

SMOKE = r"""
import json
from frontage_schema import *
from frontage_schema.jsonschema import from_json_schema
User = record(("id", integer(ge=0)), ("name", text(min=1, max=100)), ("email", email()),
              ("age", optional(integer(gt=0, le=150)), None), ("when", iso_datetime()), ("uid", uuid()))
rows = json.loads(ROWS)
value, errors = array(User).validate(rows)
out = {"errors": errors, "n": len(value), "age0": value[0]["age"]}
out["coerced"] = User.parse({"id": "3", "name": "x", "email": "a@b.co", "age": "", "when": "2026-09-07T21:17Z",
                             "uid": "123e4567-e89b-12d3-a456-426614174000"}, coerce=True)["id"]
out["bad"] = array(User).validate(rows, sample=1)[1]
# Field order is the document's, which MicroPython does not keep: compare as sets.
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
def test_the_package_runs_on_the_shipped_micropython(tmp_path):
    assert (RUNTIME / "micropython.mjs").is_file(), "frontage checked out beside this repo"
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
    files = {p.relative_to(PACKAGE).as_posix(): p.read_text() for p in PACKAGE.rglob("*.py")}
    script = tmp_path / "smoke.mjs"
    script.write_text(
        "const m = await import(%s);\n" % json.dumps(str(RUNTIME / "micropython.mjs"))
        + "const mp = await m.loadMicroPython({});\n"
        + "const files = %s;\n" % json.dumps(files)
        + "mp.FS.mkdirTree('/lib/frontage_schema');\n"
        + "for (const [name, text] of Object.entries(files)) mp.FS.writeFile('/lib/frontage_schema/' + name, text);\n"
        + "try { mp.runPython(%s + %s); } catch (e) { console.log('PYERR ' + (e.message || e)); process.exit(1); }\n"
        % (json.dumps("ROWS = %r\n" % json.dumps(rows)), json.dumps(SMOKE))
    )
    run = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=120)
    assert run.returncode == 0, run.stdout[-3000:] or run.stderr[-3000:]
    line = [ln for ln in run.stdout.splitlines() if ln.startswith("RESULT ")][0]
    out = json.loads(line[len("RESULT ") :])
    assert out["errors"] == [["$[49].email", "not an email address"]]
    assert out["n"] == 50 and out["age0"] == 30 and out["coerced"] == 3
    assert out["bad"] == [["$[49].email", "not an email address"]]
    assert out["repr"] is True
    assert out["email"] == [True, False, False]
    assert out["dates"] == [True, False]
    assert out["brace"] == "refused"
