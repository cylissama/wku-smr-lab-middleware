# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A smart manufacturing data platform (WKU SMR Lab) that ingests telemetry from distributed edge devices (IMUs, cameras, robot arm) over MQTT and TCP, stores it in PostgreSQL, and exposes a live dashboard. All backend code lives under `project/`.

## Repository layout

```text
project/
├── db/                    # asyncpg pool + all database read/write logic (shared by fastapi-app and tcp)
│   ├── database.py        # DatabaseSingleton — one pool per container
│   └── migrations.md      # hand-applied SQL migration log (no migration tool)
├── fast_server/           # FastAPI app: HTTP + WebSocket + MQTT ingestion
│   ├── main.py            # routes, MQTT subscriptions, batch workers, startup/shutdown
│   ├── parsing.py         # MQTT payload → dict parsing for imu/camera topics
│   ├── connection_manager.py  # WebSocket broadcast managers (camera/imu/robot/misc)
│   └── loggers.py
├── tcp_server/tcp_server.py   # raw asyncio TCP listener for robot telemetry (own process/container)
├── mqtt_conf/mosquitto.conf   # Mosquitto broker config
├── SOP/                   # lab standard operating procedures (test runs, swarm ops, network notes)
├── tests/                 # unittest-based tests, run as a package from repo root (see below)
├── deploy/                # standalone Swarm/Portainer stack manifests for the edge-node cluster
├── docker-compose.yml     # the always-on broker stack (single host: mqtt, fastapi, tcp, web, ntp)
├── Dockerfile             # fastapi-app image
└── web/                   # React + Vite dashboard AND a separate VitePress docs site
    ├── src/                # dashboard SPA (sessions, device status, message streams, backups)
    ├── public/info/        # SOP/diagram files served in-app, indexed by a generated manifest.json
    ├── docs/               # VitePress reference docs, built separately, served under /docs/
    └── nginx.conf          # serves the SPA, proxies /api/ to fastapi-app, serves /docs/
```

For a deeper walkthrough with data-flow diagrams, read `project/web/docs/overview/structure.md` — it's kept current and is the best single orientation doc in the repo.

## Architecture

- **Two ingestion paths, one database.** IMU and camera data arrive via MQTT (`fastapi-app` subscribes to `imu/#` and `camera/#`, see `fast_server/main.py`); robot data arrives via a raw TCP line protocol (`tcp_server/tcp_server.py`, comma-separated fields). Both paths parse into dicts, push onto an `asyncio.Queue`, and are flushed to Postgres in batches by a background worker (`camera_worker`/`imu_worker` in `fast_server/main.py`, `robot_worker` in `tcp_server.py`). Batch size/flush interval are controlled by `BATCHES` and `B_TIMEOUT` env vars.
- **`DatabaseSingleton`** (`db/database.py`) wraps a single asyncpg pool per container — `fastapi-app` and `tcp` are separate containers/processes and each holds their own singleton instance, but both talk to the same Postgres. All inserts require an active session (`SessionNotStarted` is raised otherwise); the TCP server has no way to start a session itself, so it depends on `fastapi-app`'s `/session/start/{label}` having been called first. The TCP process reports status back to the dashboard by POSTing to `fastapi-app`'s `/send/robot` endpoint (`send_to_fastapi` in `tcp_server.py`), since it has no WebSocket of its own.
- **Sessions gate everything.** All data is scoped to a session row (`session` table); `get_latest_session()` caches the current session id for ~10s to avoid hammering the DB. Starting/stopping a session also rotates the file loggers (`loggers.create_loggers()`) and triggers an automatic DB backup on stop.
- **Live updates** flow to the dashboard over four separate WebSocket channels (`/ws/camera`, `/ws/imu`, `/ws/robot`, `/ws/misc`), each backed by a `ConnectionManager` in `connection_manager.py`. `POST /send/{channel}` lets any service (including the standalone TCP process) push a message onto one of these channels.
- **Backups** are `pg_dump`/`pg_restore` shelled out from `DatabaseSingleton` to an NFS-mounted volume (`/db_backups`), not a Postgres extension or managed service. Restoring drops and recreates the database, then reopens the pool — it is destructive and only intended for lab recovery workflows.
- **Two deployment surfaces**: the always-on broker stack (`project/docker-compose.yml`, one host: mqtt broker, fastapi, tcp, web, ntp) and the IMU edge cluster (`project/deploy/swarm-imu-edge-nodes.yml`, a Docker Swarm across several Raspberry Pis, one per physical IMU via node labels). Related device-node repos (IMU, camera) are separate GitHub repos — see `REPOS.MD`.
- **`project/web` builds two independent frontends** served by the same nginx container: the operational dashboard SPA (`src/`) and the VitePress docs site (`docs/`), built with separate `npm run build` / `npm run docs:build` commands and mounted at `/` and `/docs/` respectively by `nginx.conf`.
- **No schema migration tool.** Schema changes are hand-run SQL logged chronologically in `project/db/migrations.md`. When changing table shape, add an entry there and update the SQL in `db/database.py` together.

## Commands

All backend commands assume Python 3.13 with `pip install -r project/requirements.txt`.

### Backend tests
Tests import as `project.fast_server...`, so run them from the **repository root** (not from inside `project/`):
```bash
python -m unittest project.tests.sessions_test
python -m unittest discover -s project/tests -t .
```
Tests are split into unit tests (mock the DB/managers, e.g. `channel_test.py`) and "integral" tests that exercise the FastAPI app via `TestClient` (e.g. `channel_integral_test.py`). There is no pytest config; plain `unittest` is used throughout.

### Frontend (`project/web`)
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
docker compose -f project/docker-compose.yml up -d
```
Requires a `.env` file next to `docker-compose.yml` (not committed) providing `DB_HOST`, `DB_USER`, `DB_PASSWORD`, `DB_NAME`, `MQTT_PORT`, `FASTAPI_PORT`, `WEB_PORT`, `ROBOT_TCP_PORT`, `NTP_PORT`, `HOST_IP`, `QUEUE_SIZE`, `BATCHES`, `B_TIMEOUT`, and the `VITE_*`/`*_URL` build args consumed by `web/dockerfile`.

## Notes for changes in this repo

- `db/database.py` is imported by both `fast_server` (FastAPI process) and `tcp_server.py` (separate process/container) — changes to its interface affect both call sites, and `DatabaseSingleton` state (device/session caches) is **not** shared between the two processes.
- Timestamps: the TCP robot protocol is parsed assuming `US/Eastern` local time and converted to UTC epoch (`tcp_server.py`); IMU/camera timestamps come pre-parsed from device payloads via `fast_server/parsing.py`. Keep this asymmetry in mind when touching time handling.
- `SOP/` documents describe real physical lab procedures (SSH targets, IP addresses, physical device steps) for running a data-collection session — useful context for understanding *why* the session/backup/websocket flow is shaped the way it is, but not something to treat as generic developer docs.
