# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A smart manufacturing data platform (WKU SMR Lab) that ingests telemetry from distributed edge devices (IMUs, cameras, robot arm) over MQTT and TCP, stores it in PostgreSQL, and exposes a live dashboard.

## Repository layout

```text
common/                # log_schema.py: the JSON LogRecord every service writes to stdout
db/                    # asyncpg pool + all database read/write logic (shared by fastapi-app and tcp)
├── database.py        # DatabaseSingleton — one pool per container
├── schema.sql         # from-scratch schema for local/portable Postgres, kept in sync with migrations.md
└── migrations.md      # hand-applied SQL migration log (no migration tool)
fast_server/           # FastAPI app: HTTP + WebSocket + MQTT ingestion
├── main.py            # routes, MQTT subscriptions, batch workers, startup/shutdown
├── health.py          # dependency health registry + retry backoff (GET /health)
├── healthcheck.py     # Docker HEALTHCHECK probe for fastapi-app and tcp
├── parsing.py         # MQTT payload → dict parsing for imu/camera topics
├── connection_manager.py  # WebSocket broadcast managers (camera/imu/robot/misc)
└── loggers.py
tcp_server/tcp_server.py   # raw asyncio TCP listener for robot telemetry (own process/container)
mqtt_conf/mosquitto.conf   # Mosquitto broker config
tests/                 # unittest-based tests, run as a package from repo root (see below)
deploy/                # standalone Swarm/Portainer stack manifests for the edge-node cluster
docker-compose.yml     # the always-on broker stack (single host: mqtt, fastapi, tcp, web, ntp, pgadmin)
pgadmin/               # provision-users.sh: per-person pgAdmin accounts + admin/viewer Postgres roles
Dockerfile             # fastapi-app image
web/                   # React + Vite dashboard AND a separate VitePress docs site
├── src/                # dashboard SPA (sessions, device status, message streams, backups)
├── public/info/        # SOP/diagram files served in-app, indexed by a generated manifest.json
├── docs/               # VitePress reference docs, built separately, served under /docs/
└── nginx.conf          # serves the SPA, proxies /api/ to fastapi-app, serves /docs/
```

For a deeper walkthrough with data-flow diagrams, read `web/docs/overview/structure.md` — it's kept current and is the best single orientation doc in the repo.

## Architecture

- **Two ingestion paths, one database.** IMU and camera data arrive via MQTT (`fastapi-app` subscribes to `imu/#` and `camera/#`, see `fast_server/main.py`); robot data arrives via a raw TCP line protocol (`tcp_server/tcp_server.py`, comma-separated fields). Both paths parse into dicts, push onto an `asyncio.Queue`, and are flushed to Postgres in batches by a background worker (`camera_worker`/`imu_worker` in `fast_server/main.py`, `robot_worker` in `tcp_server.py`). Batch size/flush interval are controlled by `BATCHES` and `B_TIMEOUT` env vars.
- **`DatabaseSingleton`** (`db/database.py`) wraps a single asyncpg pool per container — `fastapi-app` and `tcp` are separate containers/processes and each holds their own singleton instance, but both talk to the same Postgres. All inserts require an active session (`SessionNotStarted` is raised otherwise); the TCP server has no way to start a session itself, so it depends on `fastapi-app`'s `/session/start/{label}` having been called first. The TCP process reports status back to the dashboard by POSTing to `fastapi-app`'s `/send/robot` endpoint (`send_to_fastapi` in `tcp_server.py`), since it has no WebSocket of its own.
- **Sessions gate everything.** All data is scoped to a session row (`session` table); `get_latest_session()` caches the current session id for ~10s to avoid hammering the DB. Starting/stopping a session also rotates the file loggers (`loggers.create_loggers()`) and triggers an automatic DB backup on stop.
- **Capture state gates ingestion.** `fast_server/capture.py`'s `CaptureState` (`IDLE`/`MONITOR`/`RECORD`/`STOPPING`) decides whether MQTT messages and robot TCP lines are queued at all — only `RECORD` stores. `fastapi-app` owns it (`capture` in `main.py`, exposed at `GET /capture`, restored from an open session on startup) and pushes it to `tcp_server` (`PUT /capture` on its status server), which also re-polls every `CAPTURE_SYNC_INTERVAL` s. Queued items carry their `session_id`; workers drop items from an ended session and drop batches that hit `SessionNotStarted`, instead of retrying them into the next session. `stop_session` switches to `STOPPING` *before* removing stacks and draining. **Monitor mode** (`POST /listen/start` / `/listen/stop`, only from/to `IDLE`) deploys the edge stacks and shows data without storing it; `start_session` from `MONITOR` skips the redeploy unless the selection or the stack settings differ (they do by default: see PLC auto stop). In `MONITOR` and `RECORD`, `LiveSampler` sends at most one `"live"`-type sample per device per `LIVE_SAMPLE_INTERVAL` s to the existing `/ws/{imu,camera,robot}` channels (robot via `send_to_fastapi_nowait`). **Device selection**: device keys are `<category>/<device>` (the MQTT topic; robot is `robot/main`). The catalog (`GET /devices`) comes from `smr.category`/`smr.device` deploy labels on each service in `deploy/swarm-edge-nodes.yml`, read by stack-controller's `GET /stacks/{name}/services`, plus the robot. `/listen/start` (body `{devices}`) and `/session/start` (repeated `?devices=`) take an optional selection (omitted = all): `resolve_selection()` turns it into the capture filter plus per-stack service lists, and stack-controller deploys a filtered compose copy with `--prune` (a stack with nothing selected is removed). The selection is stored in `session.devices` (JSONB, NULL = all) and restored on startup. Each `/devices` entry also has `receiving`/`rate`/`last_seen_s` from `LiveSampler.activity()` (any message within `RECEIVING_TIMEOUT` s; robot's comes from tcp's `/queue/status`) — only tracked while monitoring/recording. The dashboard polls `/devices` every 3 s while listening, 10 s when idle. Design + figures: `plans/completed/listener-switch-plan.md`.
- **Nothing waits on the DB, NAS or broker to start.** `fastapi-app`'s `startup()` returns immediately: `db_supervisor()` and `mqtt_supervisor()` connect in the background with backoff (`fast_server/health.py`), so `app.state.db` is `None` until the first DB connect — DB-backed routes go through `require_db()`, which answers **503** `{"success": false, "error": "Database unavailable: ..."}`; `/capture`, `/devices`, `/listen/*`, `/send/*` and WebSockets work without it (monitor mode works with the DB down). `health_monitor()` re-checks db/mqtt/stack_controller/tcp/logs/backups every `HEALTH_INTERVAL` s and serves them at `GET /health` (always 200; `overall` ok/degraded/starting); state *transitions* go to `/ws/misc` and the logs as important events. `stop_session` works with the DB down (stacks removed, gate closed, `pending_session_end` saved when the DB returns). Workers keep at most `MAX_BACKLOG_ROWS` while inserts fail and report every `BACKLOG_REPORT_INTERVAL` s. `tcp` does the same (`db_monitor()`, DB status in `/queue/status`). nginx resolves `fastapi-app` per request, so `web` starts without it. Every app service has `restart: unless-stopped`. Design: `plans/dashboard-decouple-plan.md`.
- **Container health, watchdog, logs box.** Every compose service has `restart: unless-stopped` and a Docker healthcheck (`x-healthcheck-timing`; fastapi-app/tcp use `python -m fast_server.healthcheck [url]`, which stays healthy while the process answers and only *prints* degraded dependencies). Labels: `smr.monitor` (shown on the dashboard) and `smr.autoheal` (restartable). stack-controller (`stack_controller/containers.py`) runs a `Watchdog` that restarts unhealthy `smr.autoheal` containers (max `WATCHDOG_MAX_RESTARTS` per `WATCHDOG_WINDOW`, then "gives up"), and serves unauthenticated read-only `GET /containers` (state, health probes, crash log tail) and `GET /logs` (Docker logs normalized to LogRecords by `stack_controller/log_normalize.py`, credentials redacted). nginx exposes only those two as `/api/system/{containers,logs}`, so the dashboard's Container Health and Logs boxes work while fastapi-app is down. Docs: `web/docs/docker/health-and-logs.md`, `web/docs/operations/troubleshooting.md`.
- **PLC auto stop.** With `PLC_AUTO_STOP=true`, `fast_server/plc_listener.py`'s `PLCSignalWatcher` (ported from the IMU edge repo's `imu_edge/plc_signals.py`) polls the cell PLC (`PLC_PATH`, an L32E at `192.168.1.103`) over EtherNet/IP with pycomm3 in a background thread and counts rising edges of `PLC_TAG_STOP` (`Db_Stop`, a brief DINT pulse when the robot finishes). `plc_supervisor()` turns each new pulse into `stop_session_from_plc()`, which runs the same `_stop_session()` as `GET /session/stop`, but only in `RECORD` and only if no start/stop holds `session_lock` (monitor/idle ignore it). `session_lock` serializes `/session/start` and `/session/stop`; a Stop click shortly after a stop is answered `already_stopped` (`last_stop`). Status is the `plc` entry in `/health`. **IMU PLC trigger per mode:** every edge deploy carries `env` from `stack_env(mode)`: `IMU_PLC_TRIGGER=false` for monitoring, `true` for recording unless `IMU_PLC_TRIGGER_ON_RECORD` is off (root `.env` default, or the Run Parameters panel). stack-controller layers it over the stack's `env_file`, but only for variables in that stack's `env_overrides` (`stack_controller/stacks.yml`); others get a 400. Because the settings differ, `start_session` from `MONITOR` redeploys, which restarts only the IMU services; if that fails it returns to `MONITOR`. Docs: `web/docs/operations/plc-auto-stop.md`; plan: `plans/flag-listener-plan.md`.
- **Run parameters.** `fast_server/run_params.py` defines the per-run settings the dashboard's right-hand Run Parameters panel can change (`IMU_SAMPLE_HZ`, `IMU_PLC_TRIGGER_ON_RECORD`, `IMU_PLC_MAX_RUN_S`), with type/range checks. Only changed values are stored, in `/state/run_parameters.json` (`fastapi_state` volume); the `.env` values are the defaults (edge ones read via stack-controller's `GET /stacks/{name}/env`, which returns only `env_overrides` keys). `stack_env(mode)` turns them into each deploy's env. `PUT /parameters` holds `session_lock` (as do `/listen/start` and `/listen/stop`), is refused in `RECORD`/`STOPPING`, and in `MONITOR` redeploys if the monitor env changed (`deployed_env` tracks what the stacks run with). Each session stores its effective values in `session.parameters` (JSONB). Edge params must also be in `env_overrides` in `stack_controller/stacks.yml` (a test checks this). Docs: `web/docs/operations/run-parameters.md`; plan: `plans/param-manipulation-plan.md`.
- **Logging**: `fast_server/loggers.py` writes files to `LOG_DIR` on a background thread (a hung NFS mount can't block the event loop; failures are reported, not raised) and writes the system log plus every WARNING+ record to stdout as one JSON `LogRecord` per line (`common/log_schema.py`: `level` = severity, `priority` reserved/None, `category`, `important`). Use `loggers.log_event(msg, category=..., level=...)` for events a person should notice; plain `log_system_logger()` lines are `important: false`.
- **Live updates** flow to the dashboard over four separate WebSocket channels (`/ws/camera`, `/ws/imu`, `/ws/robot`, `/ws/misc`), each backed by a `ConnectionManager` in `connection_manager.py`. `POST /send/{channel}` lets any service (including the standalone TCP process) push a message onto one of these channels.
- **Backups** are `pg_dump`/`pg_restore` shelled out from `DatabaseSingleton` to an NFS-mounted volume (`/db_backups`), not a Postgres extension or managed service. Restoring drops and recreates the database, then reopens the pool — it is destructive and only intended for lab recovery workflows.
- **pgAdmin runs in the broker stack**, not on the NAS: an always-on `pgadmin` service in server mode with one account per person, each tied to their own Postgres login role in one of two groups: `lab_viewers` (students: read-only, per-role `statement_timeout`/connection limits, restricted `Viewer` pgAdmin role) or `lab_admins` (full access via inherited `DB_USER` rights with `SET FALSE`, so not superuser). Accounts are created by `pgadmin/provision-users.sh`; its data volume is deliberately local, not NFS.
- **Two deployment surfaces**: the always-on broker stack (`docker-compose.yml`, one host: mqtt broker, fastapi, tcp, web, ntp, pgadmin) and the IMU edge cluster (`deploy/swarm-imu-edge-nodes.yml`, a Docker Swarm across several Raspberry Pis, one per physical IMU via node labels). Related device-node repos (IMU, camera) are separate GitHub repos — see `REPOS.MD`.
- **`web/` builds two independent frontends** served by the same nginx container: the operational dashboard SPA (`src/`) and the VitePress docs site (`docs/`), built with separate `npm run build` / `npm run docs:build` commands and mounted at `/` and `/docs/` respectively by `nginx.conf`.
- **No schema migration tool.** Schema changes are hand-run SQL logged chronologically in `db/migrations.md`. When changing table shape, add an entry there and update the SQL in `db/database.py` together.

## Commands

All backend commands assume Python 3.13 with `pip install -r requirements.txt`.

### Backend tests
Tests import modules directly from the repo root (`fast_server`, `db`, etc.), so run them from the **repository root**:
```bash
python -m unittest tests.sessions_test
python -m unittest discover -s tests -t .
```
Tests are split into unit tests (mock the DB/managers, e.g. `channel_test.py`) and "integral" tests that exercise the FastAPI app via `TestClient` (e.g. `channel_integral_test.py`). There is no pytest config; plain `unittest` is used throughout.

### Frontend (`web/`)
```bash
npm install
npm run dev             # Vite dev server
npm run build            # also regenerates public/info/manifest.json via prebuild
npm run lint
npm run docs:dev         # VitePress docs site, separate from the dashboard SPA
npm run docs:build
```

### Full stack (Docker)
```bash
docker compose up -d
```
There are **two `.env` files**, both gitignored, each with a banner saying which it is: the broker stack's `.env` next to `docker-compose.yml` (read by compose; changes need a container recreate) and the edge stack's `deploy/.env` (read by stack-controller on each edge deploy; template `deploy/.env.example`). `IMU_PLC_TRIGGER_ON_RECORD` lives in the root one; the `IMU_PLC_TRIGGER` in `deploy/.env` is overridden on every dashboard deploy. See `web/docs/docker/compose.md#two-env-files`.

The broker stack's `.env` (see `.env.example`) provides `DB_HOST`, `DB_USER`, `DB_PASSWORD`, `DB_NAME`, `MQTT_PORT`, `FASTAPI_PORT`, `WEB_PORT`, `ROBOT_TCP_PORT`, `NTP_PORT`, `HOST_IP`, `QUEUE_SIZE`, `BATCHES`, `B_TIMEOUT`, and the `VITE_*`/`*_URL` build args consumed by `web/dockerfile`.

By default `DB_HOST` points at the lab NAS's Postgres instance, and the `nas_backups`/`logs` volumes are NFS mounts to that same NAS — this only works from inside the lab network. To replicate the stack elsewhere: `docker compose --profile local-db up -d` adds a bundled `postgres` alongside the lab stack (still requires NFS access for backups/logs unless unused); `docker compose -f docker-compose.local.yml up -d` is a fully self-contained, NAS-free copy of the whole stack (bundled Postgres/pgAdmin, local volumes) for testing on any machine. See `web/docs/docker/compose.md`.

## Notes for changes in this repo

- `db/database.py` is imported by both `fast_server` (FastAPI process) and `tcp_server.py` (separate process/container) — changes to its interface affect both call sites, and `DatabaseSingleton` state (device/session caches) is **not** shared between the two processes.
- Timestamps: the TCP robot protocol is parsed assuming `US/Eastern` local time and converted to UTC epoch (`tcp_server.py`); IMU/camera timestamps come pre-parsed from device payloads via `fast_server/parsing.py`. Keep this asymmetry in mind when touching time handling.
- Lab standard operating procedures (physical lab steps, SSH targets, IP addresses) live in the VitePress docs site under `web/docs/operations/` and `web/docs/expanding/` — e.g. `operations/running-a-test.md` and `expanding/swarm-nodes.md` — useful context for understanding *why* the session/backup/websocket flow is shaped the way it is, but not something to treat as generic developer docs. There is a separate, unrelated copy of some of this content baked into `web/public/info/` for the dashboard's in-app "Info" document library (see `docker/automations.md`'s "Dashboard document library generation") — don't confuse the two.
