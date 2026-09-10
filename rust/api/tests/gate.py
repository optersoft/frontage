#!/usr/bin/env python3
"""What the sign-in gate must do, as assertions (`API.md` §5a).

    cargo build -p frontage-api --profile api      # in rust/
    python3 rust/api/tests/gate.py                 # from the repository root, or anywhere

No dependencies and no network: the standard library starts the binary with `--auth google`
over `rust/api/examples/private/app.py` and checks who is answered what, then does it again with
**no app and no arguments at all** — `--serve` out of the environment, which is the shape a
fleet unit deploys, since its `ExecStart=` carries the binary path and nothing else. Google is never
reached, because everything up to the consent screen is ours — the redirect, the state cookie,
the PKCE challenge — and everything after it is the `id_token` verification, which has unit
tests of its own.

The authenticated half is real rather than mocked: the test reads the session secret the
server persisted and mints the same HS256 cookie the callback would, which is the only way to
assert that a signed-in visitor actually gets the private page.
"""

import base64
import hashlib
import hmac
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

CRATE = pathlib.Path(__file__).resolve().parent.parent
PORT = 8793
FILES_PORT = 8794
BASE = f"http://127.0.0.1:{PORT}"
EMAIL = "reader@optersoft.com"
failures = []


def check(name, ok, detail=""):
    print(f"  {'ok  ' if ok else 'FAIL'}  {name}{'' if ok else '  ' + detail}")
    if not ok:
        failures.append(name)


class NoRedirects(urllib.request.HTTPRedirectHandler):
    """A browser follows a 303; this test is about the 303 itself."""

    def redirect_request(self, *args):
        return None


opener = urllib.request.build_opener(NoRedirects)


def get(path, cookie=None, base=None):
    request = urllib.request.Request((base or BASE) + path)
    if cookie:
        request.add_header("Cookie", cookie)
    try:
        with opener.open(request, timeout=10) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def b64(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def session_cookie(secret, email, ttl=3600, name="private_session"):
    """The cookie the callback mints, minted here: HS256 over `{sub, exp}`."""
    header = b64(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    claims = b64(json.dumps({"sub": email, "exp": int(time.time()) + ttl}, separators=(",", ":")).encode())
    signed = f"{header}.{claims}"
    mac = hmac.new(secret.encode(), signed.encode(), hashlib.sha256).digest()
    return f"{name}={signed}.{b64(mac)}"


def auth_env(base, secret_file):
    """What a deployment sets. `AUTH_COOKIE_SECURE` is not among them: an http base is what
    drops `Secure`, and this test could not send a cookie back over plain HTTP otherwise."""
    return dict(
        os.environ,
        FRONTAGE_AUTH_GOOGLE_CLIENT_ID="test-client-id",
        FRONTAGE_AUTH_GOOGLE_CLIENT_SECRET="test-client-secret",
        FRONTAGE_AUTH_BASE_URL=base,
        FRONTAGE_AUTH_ALLOWED_EMAILS=f"  {EMAIL.upper()} , ",
        FRONTAGE_AUTH_SECRET_FILE=str(secret_file),
    )


def wait_for(base, path="/healthz"):
    deadline = time.time() + 20
    while time.time() < deadline:
        try:
            opener.open(base + path, timeout=0.5).read()
            return True
        except urllib.error.HTTPError:
            return True
        except OSError:
            time.sleep(0.05)
    return False


def refuses_a_secret_inside_the_site(binary, tmp):
    """A secret under the served directory is served, and wiped by the next deploy. Refuse."""
    www = CRATE / "examples" / "private" / "www"
    env = dict(auth_env("http://127.0.0.1:1", www / ".auth_secret"), FRONTAGE_API_SERVE=str(www),
               FRONTAGE_API_ADDR="127.0.0.1:8796", FRONTAGE_API_AUTH="google")
    done = subprocess.run([str(binary)], capture_output=True, text=True, env=env, timeout=30)
    check("a secret inside the served tree stops the server before it binds",
          done.returncode != 0 and "inside the directory being served" in done.stderr,
          f"{done.returncode} {done.stderr.strip()[:100]}")


def refuses_an_empty_site(binary, tmp):
    """An empty --serve directory is invisible from outside: the gate redirects a stranger
    whether or not there is anything behind it, so only a signed-in reader ever sees the 404."""
    empty = pathlib.Path(tmp) / "empty"
    empty.mkdir()
    env = dict(auth_env("http://127.0.0.1:1", pathlib.Path(tmp) / "s3"), FRONTAGE_API_SERVE=str(empty),
               FRONTAGE_API_ADDR="127.0.0.1:8797", FRONTAGE_API_AUTH="google")
    done = subprocess.run([str(binary)], capture_output=True, text=True, env=env, timeout=30)
    check("an empty site stops the server before it binds",
          done.returncode != 0 and "the directory is empty" in done.stderr,
          f"{done.returncode} {done.stderr.strip()[:100]}")


def files_only(binary, tmp):
    """The shape a private site deploys as: no app, no arguments, and the whole configuration
    out of the environment — which is all a fleet unit's `ExecStart=` can carry (`API.md` §5a).
    """
    base = f"http://127.0.0.1:{FILES_PORT}"
    secret_file = pathlib.Path(tmp) / "files_secret"
    env = dict(
        auth_env(base, secret_file),
        FRONTAGE_API_SERVE=str(CRATE / "examples" / "private" / "www"),
        FRONTAGE_API_ADDR=f"127.0.0.1:{FILES_PORT}",
        FRONTAGE_API_WORKERS="2",
        FRONTAGE_API_AUTH="google",
        FRONTAGE_API_AUTH_LABEL="governor",
        BUILD_ID="deadbeef",
    )
    proc = subprocess.Popen([str(binary)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            start_new_session=True, env=env)
    try:
        if not wait_for(base):
            check("the files-only server came up on env alone", False, "it never answered")
            return
        status, _, body = get("/healthz", base=base)
        check("--serve answers the liveness probe 200, not a redirect", status == 200 and body == b"ok", str(status))

        status, _, body = get("/version", base=base)
        check("and /version, which a deploy reads", status == 200 and b"deadbeef" in body, f"{status} {body[:60]}")

        status, headers, _ = get("/", base=base)
        check("a stranger cannot read the site", status == 303 and headers.get("location") == "/login?return_to=%2F", str(status))

        good = session_cookie(secret_file.read_text().strip(), EMAIL, name="governor_session")
        status, _, body = get("/", cookie=good, base=base)
        check("a signed-in reader gets index.html with no interpreter in the process",
              status == 200 and b"private page" in body, str(status))

        # The secret must not be reachable through the very server it protects.
        status, _, _ = get("/.auth_secret", cookie=good, base=base)
        check("the signing secret is not inside the served tree", status == 404, str(status))
    finally:
        proc.terminate()
        proc.wait(timeout=10)


def main():
    binary = CRATE.parent / "target" / "api" / "frontage-api"
    if not binary.exists():
        sys.exit(f"build it first: cargo build -p frontage-api --profile api ({binary} is missing)")
    app = CRATE / "examples" / "private" / "app.py"
    root = CRATE.parent.parent
    with tempfile.TemporaryDirectory() as tmp:
        secret_file = pathlib.Path(tmp) / "auth_secret"
        env = auth_env(BASE, secret_file)
        proc = subprocess.Popen(
            [str(binary), str(app), "--addr", f"127.0.0.1:{PORT}", "--workers", "2",
             "--path", str(root), "--auth", "google", "--auth-label", "private"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True, env=env,
        )
        try:
            if not wait_for(BASE):
                sys.exit("the server never came up")

            status, headers, _ = get("/")
            check("a stranger is sent to sign in", status == 303 and headers.get("location") == "/login?return_to=%2F",
                  f"{status} {headers.get('location')}")

            # The page under `www/` is the whole point: `ServeDir` must not answer it either.
            status, _, body = get("/index.html")
            check("the files are behind the gate too", status == 303 and b"private page" not in body, str(status))

            status, headers, _ = get("/plan/?x=1")
            check("where they were going survives the redirect",
                  headers.get("location") == "/login?return_to=%2Fplan%2F%3Fx%3D1", str(headers.get("location")))

            status, _, body = get("/api/secret")
            check("an API path gets a bare 401, not a login page", status == 401 and b"secret" not in body, str(status))

            status, _, body = get("/healthz")
            check("the liveness probe answers without a session", status == 200 and body == b"ok", f"{status} {body[:40]}")

            status, _, body = get("/login")
            check("the login page offers Google", status == 200 and b"Sign in with Google" in body, str(status))

            status, headers, _ = get("/auth/google/start?return_to=%2Fplan%2F")
            location = headers.get("location", "")
            query = urllib.parse.parse_qs(urllib.parse.urlparse(location).query)
            check("start redirects to Google with PKCE and a state",
                  status == 303
                  and location.startswith("https://accounts.google.com/o/oauth2/v2/auth")
                  and query.get("code_challenge_method") == ["S256"]
                  and query.get("client_id") == ["test-client-id"]
                  and query.get("redirect_uri") == [f"{BASE}/auth/google/callback"]
                  and query.get("state"),
                  location[:120])
            state_cookie = headers.get("set-cookie", "")
            check("the state cookie is scoped to the callback and hidden from scripts",
                  "Path=/auth/google" in state_cookie and "HttpOnly" in state_cookie, state_cookie[:120])

            # A callback with no state cookie is the shape of a forged or replayed one.
            status, _, body = get("/auth/google/callback?code=x&state=y")
            check("a callback with no state fails closed", status == 200 and b"Sign-in failed" in body, str(status))

            forged = session_cookie("not the server's secret", EMAIL)
            status, headers, _ = get("/", cookie=forged)
            check("a forged session is nobody", status == 303, str(status))

            secret = secret_file.read_text().strip()
            check("the signing secret was persisted 0600",
                  len(secret) == 64 and (secret_file.stat().st_mode & 0o777) == 0o600, secret_file.stat().st_mode & 0o777)

            good = session_cookie(secret, EMAIL)
            status, _, body = get("/", cookie=good)
            check("a signed-in reader gets the private page", status == 200 and b"private page" in body, str(status))

            status, _, body = get("/api/secret", cookie=good)
            check("and the API answers them", status == 200 and b"only for a session" in body, str(status))

            expired = session_cookie(secret, EMAIL, ttl=-60)
            status, _, _ = get("/", cookie=expired)
            check("an expired session is over", status == 303, str(status))

            status, headers, _ = get("/logout", cookie=good)
            cleared = headers.get("set-cookie", "")
            check("logout clears the cookie and goes back to the login page",
                  status == 303 and headers.get("location") == "/login" and "Max-Age=0" in cleared, cleared[:80])
        finally:
            proc.terminate()
            proc.wait(timeout=10)

        files_only(binary, tmp)
        refuses_a_secret_inside_the_site(binary, tmp)
        refuses_an_empty_site(binary, tmp)

    print(f"\n{'FAILED: ' + ', '.join(failures) if failures else 'all good'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
