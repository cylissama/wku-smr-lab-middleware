# Compose

[Docker Compose](https://docs.docker.com/compose/) is used to orchestrate (deploy) this entire project. We create containers for each service, such as the fast-api application, or the mqtt broker, then we 'spin' those containers up to run our services.


`project/docker-compose.yml` defines the always-on broker stack. It runs on a single host — the Data Broker Mini PC — and is brought up with a plain `docker compose up -d` from `project/`.

We plan to switch all orchestration to Docker Swarm in the future.

## Services

| Service | Image / build | Purpose |
| --- | --- | --- |
| `mqtt-broker` | `eclipse-mosquitto:2` | Receives IMU (`imu/#`) and camera (`camera/#`) messages. Config mounted from `mqtt_conf/`. |
| `fastapi-app` | built from `project/dockerfile` | HTTP API, WebSocket broadcast, MQTT subscriber, batched IMU/camera inserts, session + backup control. |
| `tcp` | built from `tcp_server/dockerfile` | Raw TCP listener for robot telemetry; batched robot inserts. |
| `web` | built from `web/dockerfile` | React/Vite dashboard + this VitePress docs site, served by nginx. |
| `ntp` | `cturra/ntp:latest` | Shared time source (see [Automations](/docker/automations)). |

Everything is driven by a single `.env` file in `project/` — database credentials, ports, batching tunables (`BATCHES`, `B_TIMEOUT`, `QUEUE_SIZE`), and the published image tags (`SMR_FASTAPI_IMAGE`, `SMR_WEB_IMAGE`, `SMR_TCP_IMAGE`).

### `mqtt-broker`

The mqtt-broker is hosted on the local port of the data broker machine, so the IP will stay the same. That IP is currently 192.168.2.100.
Exposes `MQTT_PORT` (device messaging, default `1883`) and `9001` (MQTT-over-WebSocket). Configuration is a bind-mounted directory rather than baked into the image, so broker settings can change without a rebuild.

### `fastapi-app`

Built locally from the repo (not a NAS/registry service). Connects out to Postgres on the NAS via `PGHOST=${DB_HOST}` and friends, and to the MQTT broker via the Compose service name `mqtt-broker`. Two volumes are NFS mounts back to the NAS rather than local Docker volumes:

- `nas_backups:/db_backups` — where `pg_dump` backups land.
- `logs:/fast_server/logs` — session logs.

### `web`

Built with a large set of build **args**, because Vite bakes environment values into the static bundle at build time rather than reading them at runtime: `HOST_IP`, `FASTAPI_PORT`, `VITE_API_URL`, `VITE_WS_URL`, `VITE_AI_URL`, `VITE_TWINS_URL`, `VITE_ROBOT_CAMERA_URL`, `VITE_DB_GUI_URL`. This means **the frontend must be rebuilt** any time one of these values changes — see the "SOP: Mockup to Production Cutover" document in the dashboard's Info library for the full list of environment-driven service links.

nginx inside this container (`web/nginx.conf`) does three things:

- proxies `/api/` to `fastapi-app:8000`
- serves `/docs/` (this site) with SPA fallback to `docs/index.html`
- serves everything else as the dashboard SPA, with `/info/manifest.json` explicitly marked no-cache so the document library always reflects the latest build

### `tcp`

Same `.env`-driven configuration pattern as `fastapi-app`, listening on `ROBOT_TCP_PORT` (default `5001`).

### `ntp`

Runs with `SYS_NICE`/`SYS_TIME` capabilities and mounts the host's `/etc/localtime` read-only. See [Automations](/docker/automations) for why this exists.

## Volumes

`nas_backups` and `logs` are both declared with an `nfs` driver pointing at the Synology NAS (`${DB_HOST}`), not local named volumes — backups and logs physically live on the NAS, not on the Data Broker Mini PC's disk.

## Typical operations

```bash
# Bring the stack up (detached)
docker compose up -d

# After a code or schema change — rebuild images and restart
docker compose down
docker compose up --build

# Check running services
docker compose ps
```

This stack is intentionally separate from the IMU edge nodes, which are deployed as a Docker **Swarm** stack instead — see [Swarm](/docker/swarm).

## Running outside the lab

`docker-compose.yml` assumes it's running on the Data Broker Mini PC: `DB_HOST` points at the NAS's Postgres instance, and the `nas_backups`/`logs` volumes are NFS mounts back to that same NAS. Neither is reachable from a laptop or CI runner. Two options exist for replicating the stack elsewhere, both driven by `project/.env` — copy `project/.env.example` to `project/.env` and fill in real values first.

### Option A — add a local DB alongside the lab stack

`docker-compose.yml` includes optional `postgres` and `pgadmin` services behind the `local-db` [Compose profile](https://docs.docker.com/compose/how-tos/profiles/), off by default:

```bash
docker compose --profile local-db up -d
```

This adds a bundled Postgres (`AMS-postgres`) and pgAdmin (`AMS-pgadmin`, default `http://localhost:5050`) to the same stack. To actually use them instead of the NAS, set `DB_HOST=postgres` and `DB_PORT=5432` in `.env`. Note the `nas_backups`/`logs` volumes are unaffected by this profile — they still require NFS access to `${DB_HOST}`'s NAS unless you're only using the local DB for something that doesn't touch backups.

### Option B — fully portable, no NAS required

`docker-compose.local.yml` is a self-contained copy of the full stack (mqtt, fastapi, tcp, web, ntp, plus the same `postgres`/`pgadmin` services) with `nas_backups`/`logs` replaced by plain local Docker volumes and `DB_HOST` hardcoded to the bundled Postgres. This is the option for running the entire system — ingestion, dashboard, database, backups — on any machine with nothing but Docker:

```bash
docker compose -f docker-compose.local.yml up -d --build
```

It's a separate file rather than an override merged with `docker-compose.yml`, kept manually in sync, so it has no dependency on the NAS-specific volume config at all.
