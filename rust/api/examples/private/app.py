"""A private site: a directory of prerendered pages, and nothing served to a stranger.

This is the shape `governor` deploys as — `frontage site` writes `www/`, and the server puts
Google sign-in in front of all of it:

    frontage-api rust/api/examples/private/app.py --path . --auth google

The two routes are the only ones the gate lets through unauthenticated, and they are here
because a deploy's liveness and version probes ask for them and must not be answered with a
redirect to a login page. Everything else — every page under `www/` included — needs a session.
"""

from frontage_api import App, Response

app = App(title="a private site", static="www")


@app.get("/healthz")
async def healthz():
    return Response("ok", media_type="text/plain; charset=utf-8")


@app.get("/version")
async def version():
    return {"version": "0.0.0"}


@app.get("/api/secret")
async def secret():
    return {"secret": "only for a session"}
