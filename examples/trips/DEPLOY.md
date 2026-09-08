# Deploying the trips example to the fleet

This is the fleet's first Python service, and the first use of hive's `runtime = "uv"` row.
Nothing is containerised at runtime: `hive fleet deploy` rsyncs this directory to the VM and
runs `uv sync --frozen` there; the unit runs `/home/trips/app/.venv/bin/trips`.

The row lives in `hive/hive-deploy/fleet.toml` as `[apps.trips]`: `nbg-3`, loopback port
8008, `activation = "restart"` (there is no ecdysis handoff for Python; the gateway holds an
`ECONNREFUSED` upstream for 15 s, so a deploy is a latency spike, not a 502).

## The artifact

```sh
cd ~/optersoft/frontage-component
uv run frontage build examples/trips --out examples/trips/www     # the page, beside the server
(cd examples/trips && uv lock)                                      # uv.lock is required, and committed
```

The artifact is this directory: `pyproject.toml`, `uv.lock`, `server.py`, `app.py`, `www/`.
`hive fleet deploy` refuses it without the lockfile.

## First rollout, in hive's order

```sh
cd ~/optersoft/hive
cargo run -p hive-cli -- fleet bootstrap --host trips --dry-run     # read it
cargo run -p hive-cli -- fleet bootstrap --host trips               # user, dirs, unit, uv on the box
cargo run -p hive-cli -- fleet deploy --host trips --artifact ~/optersoft/frontage-component/examples/trips
ssh root@nbg-3 systemctl start trips.service
ssh root@nbg-3 curl -s http://127.0.0.1:8008/healthz                # {"ok":true,"rows":500000}
```

Then DNS — a grey-cloud A record `trips.frontage.optersoft.com` → the floating IP — and the
gateway tenant: `hive fleet tenants` renders the row, `hive fleet config apply` installs it,
and the gateway issues the certificate over DNS-01.

## Every later deploy

```sh
uv run frontage build examples/trips --out examples/trips/www
cd ~/optersoft/hive && cargo run -p hive-cli -- fleet deploy --host trips --artifact ~/optersoft/frontage-component/examples/trips
```

Environment (`/etc/trips/trips.env`, rendered from the row's `env`): `TRIPS_ADDR`,
`TRIPS_STATIC=/home/trips/app/www`, `TRIPS_ROWS`.
