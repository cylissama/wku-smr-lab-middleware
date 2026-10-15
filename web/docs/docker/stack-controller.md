# Stack Controller & Device Selection

This page explains how the dashboard decides **which edge devices run**, how that choice travels from a checkbox in the browser to containers starting on specific Raspberry Pis, and how the `stack-controller` container drives Docker Swarm on the AMS host to make it happen. It also covers how the same selection gates which data is shown and stored.

If you only need to *use* the feature, the operator steps are in [Running a test session](/operations/running-a-test). This page is the "how it works" reference for anyone changing the code, adding a device, or debugging a device that won't come up.

::: tip Where things live
| Piece | Code |
|---|---|
| Device checklist (UI) | `web/src/components/DeviceSelector.jsx`, wired up in `web/src/DataDashboard.jsx` |
| Dashboard API calls | `web/src/api/captureApi.js`, `web/src/api/sessionApi.js` |
| Selection logic, capture state, `/devices` | `fast_server/main.py`, `fast_server/capture.py` |
| Swarm control agent | `stack_controller/main.py`, `stack_controller/docker_ops.py`, `stack_controller/auth.py` |
| Which stacks the agent may touch | `stack_controller/stacks.yml` |
| The edge stack itself | `deploy/swarm-edge-nodes.yml` + `deploy/.env` (the edge stack's own `.env`, not the repo-root one; see [Two `.env` files](/docker/compose#two-env-files)) |
| Robot gate | `tcp_server/tcp_server.py` |
:::

## The big picture

There are three separate questions, answered in three different places:

1. **Which devices exist?** — read from labels on the services in `deploy/swarm-edge-nodes.yml`, plus a fixed entry for the robot.
2. **Which of them should run?** — Docker Swarm starts only the selected services, via `stack-controller`.
3. **Whose data do we accept?** — the capture state in `fastapi-app` (mirrored into `tcp_server`) drops anything from an unselected device, and only stores data while a session is recording.

```text
 Browser (dashboard)
   │  ticks devices: imu/106, camera/113_front, robot/main
   │
   │  POST /listen/start {"devices": [...]}            ← monitor (nothing stored)
   │  GET  /session/start/{label}?...&devices=...      ← record
   ▼
 fastapi-app  (AMS host, container AMS-fastapi)
   │  1. resolve_selection(): device keys → capture filter + {stack: [services]}
   │  2. capture.set(mode, devices)  ──── PUT /capture ────►  tcp_server (robot gate)
   │  3. deploy_managed_stacks(plan)
   │
   │  POST http://stack-controller:8080/stacks/edge/deploy
   │       Authorization: Bearer $STACK_CONTROLLER_TOKEN
   │       {"services": ["imu-106", "camera-front"]}
   ▼
 stack-controller  (AMS host, container AMS-stack-controller)
   │  writes a filtered copy of swarm-edge-nodes.yml (only those services)
   │  runs:  docker stack deploy --resolve-image never --prune -c /tmp/stack-XXXX.yml edge
   │         (Docker CLI inside the container → host's /var/run/docker.sock)
   ▼
 Docker daemon on the AMS host  =  Swarm manager (IIoT, 192.168.2.100)
   │  creates/updates services edge_imu-106, edge_camera-front
   │  removes the rest of the stack's services (--prune)
   │  schedules each task onto its Pi using placement constraints
   ▼
 Raspberry Pis (Swarm workers)
     RPIIMUJ1 runs edge_imu-106  ──MQTT imu/106──►  mosquitto ──► fastapi-app
     RPiCamFront runs edge_camera-front ──MQTT camera/113_front──► ...
     (RPIIMUJ2..5, CameraPi2: nothing scheduled)
```

## Device keys: one name for a device everywhere

Every device is identified by a **device key** of the form `<category>/<device>`:

| Device | Key | Where the key comes from |
|---|---|---|
| IMU 106 | `imu/106` | its MQTT topic, `imu/${IMU_106_DEVICE_ID}` |
| Front camera | `camera/113_front` | its MQTT topic, `camera/<device_id>_<name>` with `CAMERA_FRONT_DEVICE_ID=113`, `CAMERA_FRONT_NAME=front` (the `smr.device` label is `${CAMERA_FRONT_DEVICE_ID}_${CAMERA_FRONT_NAME}` to match) |
| Robot arm | `robot/main` | fixed — the robot isn't a Swarm service (see [The robot is different](#the-robot-is-different)) |

The key deliberately **matches the MQTT topic**, because that's the only thing the ingestion side ever sees: when `fastapi-app` receives a message on `imu/106`, `parse_imu_message()` takes `106` from the topic as `device_label`, and the gate checks `"imu/106"` against the selection. No lookup table is needed at message time.

The Swarm **service name** (`imu-106`, `camera-front`) is a different thing — it's what `stack-controller` deploys. The device catalog (next section) is what connects a key to its service.

::: warning Keys must match the real topic
If a device publishes on a topic that doesn't match its `smr.device` label (say the camera actually published `camera/front`), the dashboard will still list it and Swarm will still start it, but every message will be dropped as "unselected" and the device will show **running · no data**. That's the symptom to look for.
:::

## Step 1 — The device catalog

### Labels on the services

Each service in `deploy/swarm-edge-nodes.yml` carries two Swarm **service labels** under `deploy.labels`:

```yaml
  imu-106:
    image: smart-mfg-imu:latest
    deploy:
      replicas: 1
      labels:
        smr.category: imu
        smr.device: "${IMU_106_DEVICE_ID}"
      ...
  camera-front:
    image: camera-edge:latest
    deploy:
      replicas: 1
      labels:
        smr.category: camera
        smr.device: "${CAMERA_FRONT_DEVICE_ID}"
```

`smr.device` uses the **same variable** the service already uses for its MQTT topic, so the two can't drift apart. Because they're real Swarm labels, they also show up on the running service:

```bash
docker service inspect edge_imu-106 --format '{{json .Spec.Labels}}'
# roughly: {"com.docker.stack.image":"smart-mfg-imu:latest","com.docker.stack.namespace":"edge",
#           "smr.category":"imu","smr.device":"106"}
```

A service without these labels is still deployed with the stack, but it isn't selectable and never appears in the checklist.

### `GET /stacks/{name}/services` (stack-controller)

`stack-controller` reads the compose file and resolves the labels the same way `docker stack deploy` would:

1. `load_compose()` parses the YAML.
2. The environment for interpolation is `os.environ` overlaid with the stack's `env_file` (`/stacks/.env`, i.e. `deploy/.env`), loaded fresh with `python-dotenv` on every call — so editing `deploy/.env` takes effect without restarting anything.
3. `interpolate()` substitutes `${VAR}`, `${VAR:-default}` and `${VAR-default}` in the two label values.

Response:

```json
{
  "stack": "edge",
  "services": [
    {"service": "imu-106", "category": "imu", "device_label": "106"},
    {"service": "camera-front", "category": "camera", "device_label": "113_front"},
    ...
  ],
  "success": true
}
```

### `GET /devices` (fastapi-app)

`load_device_catalog()` calls the endpoint above for every stack in `MANAGED_STACKS` (an env var on `fastapi-app`, currently `edge`), keeps the services that have both labels, and appends the robot:

```json
{"key": "imu/106", "category": "imu", "device_label": "106", "stack": "edge", "service": "imu-106", ...}
{"key": "robot/main", "category": "robot", "device_label": "main", "stack": null, "service": null, ...}
```

`GET /devices` then adds live status to each entry (see [Status indicators](#status-indicators)) and returns the list plus the currently captured selection. The dashboard calls it on load and then every **3 s** while monitoring or recording, every **10 s** when idle.

## Step 2 — The selection leaves the browser

The checklist keeps a `Set` of ticked keys. Everything is ticked when the page first loads. When an action is sent:

- **All devices ticked → `null` is sent**, meaning "every device". This is also what's sent if the device list couldn't be loaded, so the dashboard still works if `stack-controller` is down. `null` deploys the whole stack file (no filtering, no pruning) — exactly the pre-selection behaviour.
- **A subset ticked → the list of keys is sent.**
- **Starting a session while monitoring → the *monitored* selection is sent**, not the checkboxes (which are locked anyway), so recording continues with exactly the devices already running.

The two calls carry the selection differently:

```http
POST /listen/start
Content-Type: application/json

{"devices": ["imu/106", "camera/113_front", "robot/main"]}
```

```http
GET /session/start/Full_System_2026-10-08T17%3A00%3A00.000Z?is_test_session=true&session_label=Full%20System&devices=imu%2F106&devices=camera%2F113&devices=robot%2Fmain
```

`/session/start` stays a `GET` for backward compatibility, so the selection is a **repeated query parameter**; the `/` inside each key is URL-encoded as `%2F`. Omitting `devices` entirely means "every device", so older clients keep working unchanged.

## Step 3 — fastapi-app turns keys into a deploy plan

`resolve_selection(devices)` in `fast_server/main.py` returns two things:

| Return value | Example | Used for |
|---|---|---|
| capture filter | `{"imu/106", "camera/113_front", "robot/main"}` | the ingest gate — which messages are accepted |
| deploy plan | `{"edge": ["camera-front", "imu-106"]}` | which Swarm services to run, per stack |

It validates **before anything changes**: an empty list or an unknown key raises an error, and `start_session` resolves the selection *before* creating the session row, so a bad request leaves no half-started session behind. `None` (no selection) returns `(None, None)` — no catalog lookup at all.

Then, in order:

**Monitor** (`POST /listen/start`, only allowed from `idle`):

1. `set_capture(MONITOR, devices=filter)` — opens the gate for the selected devices (nothing is stored in this mode) and pushes the state to `tcp_server`.
2. `deploy_managed_stacks(plan)`.
3. If any deploy fails → back to `idle` and an error is returned.

**Record** (`GET /session/start/...`):

1. Resolve and validate the selection.
2. `db.create_session(..., devices=filter)` — the selection is saved in `session.devices` (JSONB; `NULL` = every device).
3. `set_capture(RECORD, session_id, devices=filter)` — the gate opens *before* devices start, so their first messages are stored.
4. Deploy — **skipped** if we were already monitoring with the same selection (the devices are already up); otherwise `deploy_managed_stacks(plan)`.
5. If a deploy fails → the gate closes and the session is ended (rolled back).

**`deploy_managed_stacks(plan)`** makes one call per managed stack, in parallel:

| Plan entry for the stack | Call to stack-controller |
|---|---|
| no plan (`None`) | `POST /stacks/edge/deploy` with no body → whole stack |
| a list of services | `POST /stacks/edge/deploy` with `{"services": [...]}` |
| an **empty** list (e.g. robot-only run) | `POST /stacks/edge/remove` → the whole stack is taken down, since none of it should run |

Every call goes through `stack_controller_request()`: an `aiohttp` request to `http://${STACK_CONTROLLER_HOST}:${STACK_CONTROLLER_PORT}` (defaults `stack-controller:8080`) with header `Authorization: Bearer ${STACK_CONTROLLER_TOKEN}`. It never raises — failures come back as `{"success": false, "error": "..."}` and are logged to the system logger.

## Step 4 — Inside the stack-controller container

### What the container is

| Property | Value |
|---|---|
| Compose service | `stack-controller` (container `AMS-stack-controller`) in `docker-compose.yml` |
| Image | built from `stack_controller/Dockerfile`: `FROM docker:27-cli` + Python 3, `fastapi`, `uvicorn`, `docker` (SDK), `pyyaml`, `python-dotenv` |
| Process | `uvicorn stack_controller.main:app --host 0.0.0.0 --port 8080` |
| Network | the Compose default network only — **no published port**. Only other containers on that network (in practice `fastapi-app`) can reach `http://stack-controller:8080`. |
| Health | `GET /health` → `{"status": "ok"}`, polled by the Compose healthcheck every 30 s |

It's a deliberately small agent: `fastapi-app` never gets the Docker socket itself — it can only ask this container to run a whitelisted set of operations.

### Mounts — how a container controls the host's Swarm

```yaml
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock        # the host's Docker daemon
      - ./deploy:/stacks:ro                              # compose files + deploy/.env
      - ./stack_controller/stacks.yml:/config/stacks.yml:ro   # the whitelist
```

- **`/var/run/docker.sock`** is the key one. The `docker` CLI and the Python Docker SDK inside the container talk to this socket, which is the **AMS host's** Docker daemon. That daemon is the **Swarm manager**, so `docker stack deploy` run "inside" the container is really a manager-level command for the whole cluster. (Anything with this socket effectively has root on the host, which is why the agent is whitelisted and token-protected and has no published port.)
- **`./deploy` → `/stacks` (read-only)** — the stack files and `deploy/.env`. Because it's a bind mount, edits to `deploy/swarm-edge-nodes.yml` or `deploy/.env` on the host apply on the **next deploy** without rebuilding or restarting the container.
- **`stacks.yml` → `/config/stacks.yml` (read-only)** — which stacks may be touched, and how.

### The whitelist: `stack_controller/stacks.yml`

```yaml
stacks:
  edge:
    compose_file: /stacks/swarm-edge-nodes.yml
    env_file: /stacks/.env
    stack_name: edge
    deploy_flags: ["--resolve-image", "never"]
```

The URL's `{name}` must be a key here, or the request gets a `404`. `stack_name` is the Swarm stack namespace (services become `edge_<service>`). `--resolve-image never` makes Swarm use the image tags already present on each Pi instead of contacting a registry. The file is re-read on every request — but it's a single-file bind mount, so if an editor *replaces* the file instead of editing it in place, the container keeps seeing the old copy until `stack-controller` is restarted.

### Authentication

`verify_token()` (`stack_controller/auth.py`) requires `Authorization: Bearer <token>` where the token equals the container's `STACK_CONTROLLER_TOKEN`. Both `fastapi-app` and `stack-controller` get the same value from the host's `.env`. Missing/wrong token → `401`; token not configured on the agent → `500`. `/health` is the only unauthenticated route.

### Endpoints

| Method & path | What it does |
|---|---|
| `GET /health` | liveness |
| `GET /stacks/{name}/services` | the device catalog for that stack (see Step 1) |
| `POST /stacks/{name}/deploy` | deploy the whole stack, or only `{"services": [...]}` |
| `POST /stacks/{name}/remove` | `docker stack rm <stack_name>` |
| `GET /stacks/{name}/status` | per-service running/desired counts, rolled up into a state |

Deploy and remove take a **per-stack lock**: a second deploy/remove for the same stack while one is running gets `409 Conflict` instead of queueing behind it.

### What a selective deploy actually runs

For `POST /stacks/edge/deploy` with `{"services": ["imu-106", "camera-front"]}`:

1. **Validate** — an empty list → `400` ("remove the stack instead"); a name not in the compose file → `400` listing the unknown names. Nothing is run.
2. **Build the environment** — `os.environ` overlaid with `deploy/.env`. This matters because `docker stack deploy` interpolates `${VAR}` **from the environment of the process that runs it**, not from a `.env` file beside the compose file.
3. **Write a filtered compose file** — `write_filtered_compose()` loads `swarm-edge-nodes.yml`, keeps only the selected entries under `services:` (top-level `networks`, `volumes`, `x-` keys are kept as-is), and writes it to a temp file such as `/tmp/stack-k2j9.yml` inside the container. `${VAR}` references are written back **unexpanded** — the real deploy does the interpolation, exactly as for the unfiltered file.
4. **Run the CLI** (`docker_ops.deploy_stack`, 120 s timeout):
   ```bash
   docker stack deploy --resolve-image never --prune -c /tmp/stack-k2j9.yml edge
   ```
   `--prune` is added **only** for selective deploys: it removes any service in stack `edge` that isn't in the file. That's how de-selected devices stop — e.g. switching from all IMUs to just `imu-106` removes `edge_imu-107`..`edge_imu-110`.
5. **Clean up** — the temp file is deleted whether the deploy succeeded or not.
6. **Reply** — `200 {"success": true, "stack": "edge", "services": [...], "output": "..."}`, or `500` with the CLI's stderr, or `504` on timeout.

Bind-mount `source:` paths in the compose file (e.g. `/run/imu-hw`) refer to paths **on the Pi** that runs the task, so writing the filtered copy to `/tmp` in the controller doesn't affect them.

A deploy with **no body** is the same minus steps 1, 3 and 5: the original `/stacks/swarm-edge-nodes.yml` is deployed as-is, without `--prune`.

### Removing

`POST /stacks/edge/remove` runs `docker stack rm edge` (60 s timeout). This returns as soon as Swarm accepts the removal; containers on the Pis shut down over the next few seconds. `stop_session` and `/listen/stop` call this, then `stop_session` waits for the ingestion queues to drain.

## Step 5 — Swarm puts each service on its Pi

Once `docker stack deploy` hands the service specs to the manager, Swarm takes over:

- **Placement.** IMU services are pinned by hostname (`node.hostname == ${IMU_106_HOSTNAME}` → `RPIIMUJ1`, …); cameras by node label (`node.labels.camera == front` → `RPiCamFront`, `== side` → `CameraPi2`). A service whose constraint matches no node stays at `0/1` with "no suitable node" in `docker service ps`.
- **Task lifecycle.** Each service gets one task (`replicas: 1`): `new → pending → assigned → accepted → preparing → starting → running`. Because every edge service has a **healthcheck**, Swarm keeps the task in *starting* until the first check passes. Checks run every **10 s** (`interval`), with a warm-up (`start_period`) of 15 s for IMUs and 30 s for cameras during which failures don't count. This is the delay you see as **starting** in the dashboard.
- **Restarts.** IMUs restart `on-failure`, cameras on `any` exit.

Useful commands on the AMS host:

```bash
docker stack services edge                        # replicas per service, e.g. edge_imu-106 1/1
docker service ps edge_imu-106 --no-trunc         # task history, node, and errors
docker service logs edge_camera-front --since 5m  # the container's output, from the manager
docker node ls                                    # are all Pis Ready/Active?
```

## Step 6 — The selection gates the data

Starting only the selected services is half the job. The other half is in the **capture state** (`fast_server/capture.py`), which every incoming message passes through:

```text
MQTT imu/106 message ──► handle_sensors()
   not monitoring/recording?          → drop (not even parsed)
   parse → device key "imu/106"
   capture.accepts("imu", "106")?     → no: drop (unselected)
   live sampler: ≤1 "[live]" line/s to the dashboard's IMU panel
   capture.should_store()?            → only in RECORD: tag with session_id, queue for Postgres
```

`capture.devices` is the filter from Step 3 (`None` = accept every device). This gate catches anything Swarm didn't stop — a node started by hand over SSH, a leftover container, or a device publishing on the wrong topic.

### The robot is different

The robot arm isn't a container: it's started by an operator and streams CSV lines to `tcp_server` on its own. So the selection **can't stop the robot** — it only decides what happens to its data:

- `fastapi-app` pushes every capture change to `tcp_server` with `PUT http://tcp:8090/capture` (the same JSON as `GET /capture`, including `devices`). `tcp_server` also re-pulls `GET /capture` every 5 s in case a push was missed, and ignores stale copies using a version number.
- `handle_robot()` keeps the TCP connection open and keeps reading. If `robot/main` isn't selected, each line is **dropped** after parsing: no live line in the Robot panel, nothing queued, nothing stored.
- In a robot-only run, the plan for `edge` is empty, so the whole edge stack is removed and no Pi runs anything.

## Status indicators

Each device row in the checklist shows one status, in this order of precedence:

| Shown | Meaning | Source |
|---|---|---|
| **receiving · N msg/s** | a message from this device arrived in the last 3 s (`RECEIVING_TIMEOUT`) | `LiveSampler.activity()` in `fastapi-app`; for the robot, the `activity` field of `tcp_server`'s `GET /queue/status` |
| **running · no data** (amber) | monitoring/recording, the service is up, but nothing is arriving | Swarm says running, sampler says silent |
| **running** | Swarm has the desired number of running tasks | `GET /stacks/edge/status` |
| **starting** | fewer running than desired, nothing failed yet (usually waiting on the healthcheck) | same |
| **error** | fewer running than desired and a task has failed | same |
| **not deployed** | no such service in the stack | same |
| **connected / not connected** | robot only: whether a TCP connection to `tcp_server` is open | `connections` in `GET /queue/status` |
| **unknown** | couldn't reach stack-controller / tcp_server | — |

How the Swarm part is computed (`docker_ops.get_stack_status`): the Docker SDK lists services labelled `com.docker.stack.namespace=edge`; for each, it counts tasks in state `running` against the desired replica count. **receiving** is only tracked while monitoring or recording, because in `idle` messages are dropped before they're even parsed. Hover a status to see how long ago the last message arrived.

The receiving check is cheap by design: it reuses the per-device bookkeeping the live sampler already does for every accepted message (one extra dictionary write, measured at ~0.13 µs per message), and the status is only computed when the dashboard asks for `/devices`.

## Configuration reference

| Variable | Set on | Default | Purpose |
|---|---|---|---|
| `MANAGED_STACKS` | fastapi-app | `edge` | comma-separated stacks to deploy/remove/list (must exist in `stacks.yml`) |
| `STACK_CONTROLLER_HOST` / `_PORT` | fastapi-app | `stack-controller` / `8080` | where to reach the agent |
| `STACK_CONTROLLER_TOKEN` | fastapi-app **and** stack-controller | — | shared bearer token (host `.env`) |
| `STACKS_CONFIG_PATH` | stack-controller | `/config/stacks.yml` | the whitelist |
| `TCP_HOST` / `ROBOT_STATUS_PORT` | fastapi-app (and tcp) | `tcp` / `8090` | tcp_server's status + capture endpoints |
| `CAPTURE_SYNC_INTERVAL` | tcp | `5` | seconds between tcp_server's re-syncs of the capture state |
| `LIVE_SAMPLE_INTERVAL` | fastapi-app, tcp | `1` | seconds between `[live]` lines per device |
| `RECEIVING_TIMEOUT` | fastapi-app, tcp | `3` | seconds of silence before a device stops counting as receiving |
| `IMU_10x_DEVICE_ID`, `CAMERA_*_DEVICE_ID`, `IMU_10x_HOSTNAME`, … | `deploy/.env` | — | device IDs (→ topics and `smr.device`) and placement |

## Adding or changing a device

No application code changes are needed:

1. Add the service to `deploy/swarm-edge-nodes.yml` with its placement constraint, its MQTT topic, and the two labels — `smr.category` (`imu` or `camera`) and `smr.device` set to the **same value the topic uses**.
2. Add any new variables to `deploy/.env` on the AMS host.
3. Make sure the Pi has joined the Swarm and matches the constraint ([Bringing a node online](/expanding/swarm-nodes)).

The device appears in the checklist on the dashboard's next refresh (the catalog is read live). A whole new *stack* additionally needs an entry in `stack_controller/stacks.yml` (see the single-file mount caveat above) and its name added to `MANAGED_STACKS` on `fastapi-app` (recreate `fastapi-app` to pick up the env change).

## Troubleshooting

| Symptom | Likely cause / what to check |
|---|---|
| Checklist shows "Unable to load devices" | `stack-controller` down or token mismatch — `docker ps` for `AMS-stack-controller` (healthy?), and that `STACK_CONTROLLER_TOKEN` is identical for both services. The dashboard falls back to "every device". |
| Device missing from the checklist | service has no `smr.category`/`smr.device` labels, or the label's variable is empty in `deploy/.env` |
| Stuck on **starting** for over a minute | healthcheck failing — `docker service ps edge_<service> --no-trunc` and `docker service logs edge_<service>` |
| Stays at `0/1`, "no suitable node" | placement constraint doesn't match any node — check `docker node ls` and the node's hostname/labels |
| **running · no data** | the device is up but not publishing (e.g. a camera with no marker in view), or its topic doesn't match its `smr.device` label |
| Deploy returns `409` | another deploy/remove of the same stack is still running — wait and retry |
| Deploy returns `400 Unknown service(s)` | the dashboard's catalog is stale relative to the compose file — reload the page |
| Starting a session fails with `column "devices" does not exist` | the `session.devices` migration (Oct 8 2026 in `db/migrations.md`) hasn't been applied to the database |
| Robot shows **connected** but never **receiving** | robot not selected, not monitoring/recording yet, or tcp_server hasn't synced — check `GET /capture` and the robot logger file |
