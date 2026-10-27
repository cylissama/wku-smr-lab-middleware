# Compose

[Docker Compose](https://docs.docker.com/compose/) is used to orchestrate (deploy) this entire project. We create containers for each service, such as the fast-api application, or the mqtt broker, then we 'spin' those containers up to run our services.


`docker-compose.yml` defines the always-on broker stack. It runs on a single host, the [AMS host](/hardware/data-broker-mini-pc) (`192.168.2.100`), and is brought up with `docker compose up -d` from the repo root (`/home/ubuntu/wku-smr-lab-middleware`). The edge devices are a separate Swarm stack that the dashboard starts per run; see [Swarm](/docker/swarm).

## Services

| Service | Image / build | Purpose |
| --- | --- | --- |
| `mqtt-broker` | `eclipse-mosquitto:2` | Receives IMU (`imu/#`) and camera (`camera/#`) messages. Config mounted from `mqtt_conf/`. |
| `fastapi-app` | built from `Dockerfile` | HTTP API ([reference](/docker/api)), WebSocket broadcast, MQTT subscriber, batched IMU/camera inserts, sessions, capture state, backups, PLC auto stop, run parameters. |
| `tcp` | built from `tcp_server/dockerfile` | Raw TCP listener for robot telemetry; batched robot inserts. |
| `web` | built from `web/dockerfile` | React/Vite dashboard + this VitePress docs site, served by nginx. |
| `stack-controller` | built from `stack_controller/Dockerfile` | Deploys/removes the edge Swarm stack for `fastapi-app`; container watchdog; read-only container status and logs. See [Stack controller](/docker/stack-controller). |
| `ntp` | `cturra/ntp:latest` | Shared time source (see [Automations](/docker/automations)). |
| `pgadmin` | `dpage/pgadmin4:9` | Multi-user pgAdmin for querying the database (see [Accessing the database](/data/accessing-database)). |

This stack is driven by the `.env` file in the repo root — database credentials, ports, batching tunables (`BATCHES`, `B_TIMEOUT`, `QUEUE_SIZE`), and the published image tags (`SMR_FASTAPI_IMAGE`, `SMR_WEB_IMAGE`, `SMR_TCP_IMAGE`). The edge nodes have their own, separate file; see below.

### Two `.env` files

There are two `.env` files on the AMS host. They configure different stacks, are read by different processes, and take effect at different times. Each starts with a banner saying which one it is.

| | Broker stack `.env` | Edge stack `.env` |
| --- | --- | --- |
| Path | `.env` (repo root, next to `docker-compose.yml`) | `deploy/.env` (next to `swarm-edge-nodes.yml`) |
| Template | `.env.example` | `deploy/.env.example` |
| Configures | the always-on stack: `fastapi-app`, `tcp`, `web`, `stack-controller`, `pgadmin` | the IMU and camera services on the Pis |
| Read by | `docker compose` (`env_file` / `${VAR}`) | `stack-controller` on every edge deploy (mounted at `/stacks/.env`), or your shell for a manual `docker stack deploy` |
| Takes effect | after recreating the container (`docker compose up -d --force-recreate <service>`) | on the next deploy (Start Monitoring / Start Session); nothing to restart |
| Examples | `DB_*`, ports, `BATCHES`, `PLC_AUTO_STOP`, `IMU_PLC_TRIGGER_ON_RECORD`, `STACK_CONTROLLER_TOKEN` | `IMU_10x_DEVICE_ID`, `IMU_SAMPLE_HZ`, `CAMERA_*`, `MQTT_BROKER_IP`, `IMU_PLC_TRIGGER` |

The PLC trigger is the easy one to mix up. Whether a session waits for the PLC is set by `IMU_PLC_TRIGGER_ON_RECORD` in the **root** `.env`. fastapi-app uses it to choose the `IMU_PLC_TRIGGER` value it sends with each edge deploy, and that value replaces the `IMU_PLC_TRIGGER` line in `deploy/.env`. So editing `IMU_PLC_TRIGGER` in `deploy/.env` changes nothing for monitoring or sessions; it only applies to a manual `docker stack deploy`. See [PLC auto stop](/operations/plc-auto-stop#imu-plc-trigger-monitor-vs-session).

Some edge values (`IMU_SAMPLE_HZ`, `IMU_PLC_MAX_RUN_S`, and `IMU_PLC_TRIGGER_ON_RECORD` from the root file) are only **defaults** now: the dashboard's [Run Parameters](/operations/run-parameters) panel can override them per run, and those overrides win over the `.env` line.

### `mqtt-broker`

The mqtt-broker is hosted on the local port of the data broker machine, so the IP will stay the same. That IP is currently 192.168.2.100.
Exposes `MQTT_PORT` (device messaging, default `1883`) and `9001` (MQTT-over-WebSocket). Configuration is a bind-mounted directory rather than baked into the image, so broker settings can change without a rebuild.

### `fastapi-app`

Built locally from the repo (not a NAS/registry service). Connects out to Postgres on the NAS via `PGHOST=${DB_HOST}` and friends, and to the MQTT broker via the Compose service name `mqtt-broker`. Two volumes are NFS mounts back to the NAS rather than local Docker volumes:

- `nas_backups:/db_backups` — where `pg_dump` backups land.
- `logs:/fast_server/logs` — session logs.

A third volume, `fastapi_state:/state`, is a normal local volume. It holds `run_parameters.json`, the values set in the dashboard's [Run Parameters](/operations/run-parameters) panel. It's local rather than NFS so that saving can't hang on the NAS.

### `web`

Built with a large set of build **args**, because Vite bakes environment values into the static bundle at build time rather than reading them at runtime: `HOST_IP`, `FASTAPI_PORT`, `VITE_API_URL`, `VITE_WS_URL`, `VITE_AI_URL`, `VITE_TWINS_URL`, `VITE_ROBOT_CAMERA_URL`, `VITE_DB_GUI_URL`, `VITE_PORTAINER_URL` (and the non-`VITE_` `ROBOT_CAMERA_URL`, `DB_GUI_URL`, `PORTAINER_URL` fallbacks). This means **the frontend must be rebuilt** any time one of these values changes — see the "SOP: Mockup to Production Cutover" document in the dashboard's Info library for the full list of environment-driven service links.

nginx inside this container (`web/nginx.conf`) does four things:

- proxies `/api/` to `fastapi-app:8000`, looking the name up **per request** (Docker's DNS at `127.0.0.11`), so `web` starts and keeps serving even while `fastapi-app` is down; API calls then get a JSON 503 saying so
- proxies the two read-only routes `/api/system/containers` and `/api/system/logs` to `stack-controller:8080` for the dashboard's Container Health and Logs boxes (GET only; stack-controller's deploy routes are not exposed)
- serves `/docs/` (this site) with SPA fallback to `docs/index.html`
- serves everything else as the dashboard SPA, with `/info/manifest.json` explicitly marked no-cache so the document library always reflects the latest build

### `tcp`

Same `.env`-driven configuration pattern as `fastapi-app`, listening on `ROBOT_TCP_PORT` (default `5001`) for the robot, and on an internal status port `8090` (not published) that `fastapi-app` uses for the capture state and queue status. Its log files go to `LOG_DIR=/tcp-server/logs`, which is where the `logs` NFS volume is mounted. See [TCP Server](/docker/tcp-server).

### `pgadmin`

The lab's pgAdmin, moved off the NAS into this stack. Published on `PGADMIN_PORT` (default `5050`), so it lives at `http://192.168.2.100:5050`, and the dashboard's pgAdmin button defaults to `http://${HOST_IP}:${PGADMIN_PORT}` unless `DB_GUI_URL` is set. It connects to whatever `DB_HOST` points at.

- **Server mode, one account per person.** Everyone gets their own pgAdmin login and their own Postgres role, as either a viewer (read-only) or an admin, created with `pgadmin/provision-users.sh`. The full workflow is in [Accessing the database](/data/accessing-database#managing-accounts-admins).
- **Tuned for speed.** pgAdmin can only run one gunicorn worker, so concurrency comes from threads: `GUNICORN_THREADS` is raised from the image default of 25 to `PGADMIN_THREADS` (default `50`). The upgrade check, per-request access log and bundled postfix are all disabled. The service has no CPU or memory limits.
- **Local volume.** `pgadmin_data` is a normal Docker volume on the mini PC's disk, not NFS. pgAdmin stores users, saved servers and query history in SQLite, which is slow and prone to locking problems over NFS. Back it up with `docker run --rm -v <project>_pgadmin_data:/d -v $PWD:/out alpine tar czf /out/pgadmin_data.tgz -C /d .` if needed.

### `ntp`

Runs with `SYS_NICE`/`SYS_TIME` capabilities and mounts the host's `/etc/localtime` read-only. See [Automations](/docker/automations) for why this exists.

## Health, restarts and logs

Every container is set up to come back by itself and to say why it isn't working. The details are in [Health & logs](/docker/health-and-logs). In short:

- **Nothing waits on the database, NAS or broker to start.** `fastapi-app` and `tcp` connect in the background and keep retrying; `web` has no `depends_on` and doesn't need `fastapi-app` to be up.
- **`restart: unless-stopped`** on every service, so a crashed container is restarted.
- **Docker health checks** on `mqtt-broker`, `fastapi-app`, `tcp`, `web` (plus the existing ones on `stack-controller`, `pgadmin`, `ntp`), all sharing the `x-healthcheck-timing` settings. "Healthy" means the container itself works, not that its dependencies are up.
- **Labels**: `smr.monitor: "true"` shows a container in the dashboard's Container Health and Logs boxes; `smr.autoheal: "true"` lets stack-controller's watchdog restart it when it goes `unhealthy` (plain Compose never does). `stack-controller` itself is monitored but not auto-restarted.
- **Log rotation**: `x-logging` caps Docker's own logs at 5 × 10 MB per container.

## Volumes

| Volume | Kind | Holds |
| --- | --- | --- |
| `nas_backups` | NFS → NAS `/volume1/docker/postgres/backups` | `pg_dump` backups |
| `logs` | NFS → NAS `/volume1/docker/postgres/logs` | log files from `fastapi-app` and `tcp` |
| `fastapi_state` | local | run parameters |
| `pgadmin_data` | local | pgAdmin users, servers, query history |
| `chrony-state` | local | NTP state |
| `postgres_data` | local | only with the `local-db` profile |

The two NFS volumes point at the Synology NAS (`${DB_HOST}`), so backups and logs physically live on the NAS, not on the AMS host's disk. If the NAS is down when a container that mounts them starts, that container can't start; see [Troubleshooting](/operations/troubleshooting#log-files-or-backup-folder-down).

## Typical operations

```bash
# Bring the stack up (detached)
docker compose up -d

# After a code change — rebuild and recreate just the changed services
docker compose up -d --build --no-deps fastapi-app web

# Check running services
docker compose ps
```

Check that no session is recording (`GET /capture` says `idle`) before recreating `fastapi-app` or `tcp`. A schema change also needs its migration applied first; see [Updating the schema](/data/schema-changes).

This stack is intentionally separate from the edge nodes, which are deployed as a Docker **Swarm** stack instead — see [Swarm](/docker/swarm).

## Running outside the lab

`docker-compose.yml` assumes it's running on the Data Broker Mini PC: `DB_HOST` points at the NAS's Postgres instance, and the `nas_backups`/`logs` volumes are NFS mounts back to that same NAS. Neither is reachable from a laptop or CI runner. Two options exist for replicating the stack elsewhere, both driven by `.env` — copy `.env.example` to `.env` and fill in real values first.

### Option A — add a local DB alongside the lab stack

`docker-compose.yml` includes an optional `postgres` service behind the `local-db` [Compose profile](https://docs.docker.com/compose/how-tos/profiles/), off by default (`pgadmin` is always on and follows `DB_HOST`):

```bash
docker compose --profile local-db up -d
```

This adds a bundled Postgres (`AMS-postgres`) to the same stack. To actually use them instead of the NAS, set `DB_HOST=postgres` and `DB_PORT=5432` in `.env`. Note the `nas_backups`/`logs` volumes are unaffected by this profile — they still require NFS access to `${DB_HOST}`'s NAS unless you're only using the local DB for something that doesn't touch backups.

### Option B — fully portable, no NAS required

`docker-compose.local.yml` is a self-contained copy of the full stack (mqtt, fastapi, tcp, web, ntp, plus the same `postgres`/`pgadmin` services) with `nas_backups`/`logs` replaced by plain local Docker volumes and `DB_HOST` hardcoded to the bundled Postgres. This is the option for running the entire system — ingestion, dashboard, database, backups — on any machine with nothing but Docker:

```bash
docker compose -f docker-compose.local.yml up -d --build
```

It's a separate file rather than an override merged with `docker-compose.yml`, kept manually in sync, so it has no dependency on the NAS-specific volume config at all.

### Accessing pgAdmin locally

Both Option A and Option B bring up a `pgadmin` container at `http://localhost:${PGADMIN_PORT}` (default `5050`).

- **pgAdmin login** — `PGADMIN_EMAIL` / `PGADMIN_PASSWORD` from your `.env` (falls back to `admin@example.com` / `admin` if left unset — see `docker-compose.yml`/`docker-compose.local.yml`).
- **Connecting to the database inside pgAdmin** — add a new server using:
  - Host: `postgres` (the Compose service name, not `localhost`)
  - Port: `5432`
  - Maintenance database: `${DB_NAME}`
  - Username: `${DB_USER}`
  - Password: `${DB_PASSWORD}`

  All four come from the same `.env` used to bring up the stack.
