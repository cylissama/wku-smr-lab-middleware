# Stack Controller — Next Steps & Fixes

> Follow-up to `swarm-stack-agent-plan.md`, after implementing M1–M3 (agent skeleton,
> deploy/remove/status/health, whitelist config, `docker-compose.yml` wiring,
> `start_session`/`stop_session` integration with the session-first / stacks-first
> ordering, and best-effort IMU/camera queue draining). This doc covers what's left
> and the two gaps found since: robot queue visibility, and the missing camera
> compose file.
>
> **Update:** §1, §2, and M4 (§3) are now done -- see the status note at the top
> of each section below.

> **Update (2026-09-25):** the separate `imu`/`camera` stacks are superseded by a
> single `edge` stack, `deploy/swarm-edge-nodes.yml` (IMUs 106-110 pinned by
> hostname `RPIIMUJ1`-`RPIIMUJ5`, cameras by `node.labels.camera` front/side).
> Its values come from `deploy/.env` (gitignored), which `stack-controller` now
> loads per deploy via the new `env_file` key in `stack_controller/stacks.yml`.
> `MANAGED_STACKS=edge`. The Swarm manager moved to the AMS host (`IIoT`,
> `192.168.2.100`); the camera hosts are `RPiCamFront` (`192.168.1.113`) and
> `CameraPi2` (`192.168.1.114`), not `.80`/`.92` as noted in §2 below.

---

## 1. Fix needed: robot queue has no visibility before a session stops (P0)

> **Status: done.** `tcp_server.py` now exposes `GET /queue/status` via
> `aiohttp.web` (`queue_status`/`start_status_server`, started alongside
> `asyncio.start_server` in `start_tcp_server()`), backed by a new `robot_pending`
> counter set in `robot_worker`. `ROBOT_STATUS_PORT` (default `8090`) is wired
> into `docker-compose.yml`/`docker-compose.local.yml` for the `tcp` service, not
> published. `drain_queues()` in `fast_server/main.py` now polls it via
> `get_robot_queue_status()` alongside the IMU/camera queues, and the secondary
> gap below is fixed too -- `imu_pending`/`camera_pending` counters are checked
> the same way. `drain_queues()` returns which queue(s) are still non-empty, and
> `stop_session`'s warning now names them explicitly instead of a generic
> "IMU/camera" message. Verified with ad hoc scripts (not a checked-in test):
> immediate drain when everything's empty, correct timeout+report when the robot
> endpoint reports non-empty, correct timeout+report when an in-flight batch
> (`*_pending`) is the only thing outstanding, and fail-safe "not empty" when the
> `tcp` service is unreachable.

**Problem.** `stop_session()` in `fast_server/main.py` now removes the IMU/camera
Swarm stacks, then calls `drain_queues()` to wait for `imu_queue`/`camera_queue` to
empty before ending the session — see `fast_server/main.py`'s `drain_queues()`. But
robot telemetry doesn't go through `fastapi-app` at all: it's parsed, queued, and
batch-inserted entirely inside the separate `tcp_server` process
(`tcp_server/tcp_server.py`'s `robot_queue` and `robot_worker`, lines 10 and 35–60).
`fastapi-app` has no handle on that queue — it's a different Python process in a
different container. So today, `stop_session` can report success while robot data
is still sitting unflushed in `tcp_server`'s memory. This directly violates the
"no data left in the buffer before stopping the session" requirement from the
original plan.

**Proposed fix — give `tcp_server` a small HTTP status surface**, mirroring the
same pattern just built for `stack-controller` (`fastapi-app` calling out to a
sibling service over the default Compose network):

- Add `GET /queue/status` to `tcp_server`, returning something like
  `{"depth": robot_queue.qsize(), "pending": <in-flight count>, "empty": bool}`.
- Run it via `aiohttp.web` inside `tcp_server.py`'s existing event loop (`aiohttp`
  is already a dependency here — it's what `send_to_fastapi()` uses as a client —
  so this reuses the same library as a server instead of introducing a new one).
  Start the `AppRunner`/`TCPSite` alongside `asyncio.start_server(...)` in
  `start_tcp_server()`, e.g. via `asyncio.gather()`.
- New env var `ROBOT_STATUS_PORT` (suggest default `8090`), added to the `tcp`
  service in `docker-compose.yml` — **no published port**, same reasoning as
  `stack-controller`: only `fastapi-app` needs to reach it, over the default
  network by service name (`tcp`).
- Extend `drain_queues()` in `fast_server/main.py` to also poll
  `http://tcp:{ROBOT_STATUS_PORT}/queue/status` on the same timeout/poll loop it
  already uses for `imu_queue`/`camera_queue`, via `aiohttp` (already imported
  there now for `call_stack_controller`).

**Secondary correctness gap — applies to IMU/camera too, not just robot.**
`drain_queues()` only checks `asyncio.Queue.empty()`. That's not the same as "all
data is durably stored": there's a window, inside every worker
(`camera_worker`/`imu_worker`/`robot_worker`), between pulling an item off the
queue into the local `batch` list and that batch actually landing in Postgres —
during that window the queue is already empty, but the item isn't stored yet.
Recommend each worker track a small `pending` counter (items pulled but not yet
successfully inserted) and expose `qsize() + pending` as the real "unflushed"
count; drain logic should wait for that to hit zero, not just `qsize()`. Worth
doing for all three queues at the same time as the robot fix, since it's the same
change shape in three places.

**Interim mitigation if the full fix doesn't land immediately:** don't claim a
guarantee we don't have. Extend the existing "stopping session with data still
buffered" warning path (already added for the IMU/camera timeout case) to also
explicitly log/broadcast that robot data isn't checked at all yet, so it's a known
visible gap to operators rather than a silent assumption.

---

## 2. Camera edge-node stack file (blocked on you)

> **Status: done.** The file landed at `project/deploy/swarm-camera-edge-nodes.yml`
> (two services, `camera-front`/`camera-side`, placed via
> `node.labels.camera == front/side`, values pulled from env vars). Added the new
> env vars it needs (`MQTT_BROKER_IP`, `CAMERA_FRONT_*`, `CAMERA_SIDE_*`,
> `CAMERA_MARKER_LENGTH_M`) to `.env.example` -- `docker stack deploy` interpolates
> `${VAR}` from the calling process's environment, not a `.env` file next to the
> compose file, so these need to be real values in the AMS host's own `.env` for
> `stack-controller`'s `env_file: .env` to pick them up. **Still open, ops-side,
> not code:** confirm the two camera hosts (`192.168.1.80`, `192.168.1.92`) have
> the Swarm node labels `camera=front`/`camera=side` set
> (`docker node update --label-add camera=front <node>`) before the first real
> deploy -- they were previously reached via SSH + plain `docker compose up -d`,
> so likely don't have these yet.

`stack_controller/stacks.yml` already has a `camera` entry expecting
`project/deploy/swarm-camera-edge-nodes.yml` (stack name `camera`) — same shape as
the existing `imu` entry. You mentioned that file currently lives on a separate
machine and you'll move it into the repo soon. Once it's in `project/deploy/`,
deploy/remove should work with no code changes on our end.

Until then:

- `.env.example`'s `MANAGED_STACKS=imu,camera` means `start_session` will try to
  deploy `camera` immediately and — per the "block on failed deploy" decision —
  fail (and roll back) the whole session start, since the compose file won't
  exist yet. **Consider setting `MANAGED_STACKS=imu` in the real `.env` until the
  camera file lands**, so session start isn't broken in the meantime.
- When the file does land, worth double-checking before the first real deploy:
  - Swarm placement constraints for the two camera hosts (`192.168.1.80`,
    `192.168.1.92` per `camera-ops.md`) are expressed as Swarm node labels the
    way `swarm-imu-edge-nodes.yml` does it — those hosts were previously reached
    via SSH + plain `docker compose up -d`, not Swarm, so they may not have node
    labels assigned in this cluster yet.
  - The stack name Docker Swarm assigns internally doesn't collide with `imu`'s
    (should be fine since `docker stack deploy` namespaces by the name we pass,
    `camera`, but worth a sanity check on first deploy).

---

## 3. Remaining rollout milestones (from the original plan)

- **M4** — End-to-end test in `docker-compose.local.yml`: **wired in.**
  `stack-controller` (docker.sock + `./deploy` + `stacks.yml` mounts, no
  published port) and the matching `fastapi-app`/`tcp` env vars
  (`STACK_CONTROLLER_*`, `TCP_HOST`, `ROBOT_STATUS_PORT`) now mirror
  `docker-compose.yml`. Documented at the top of the file that this needs
  `docker swarm init` on the dev machine first, and that
  `swarm-imu-edge-nodes.yml`'s hostname constraints and
  `swarm-camera-edge-nodes.yml`'s node-label constraints won't be satisfied by a
  single dev-machine swarm -- `deploy` will succeed and create the stack, but
  services will sit at 0/N replicas unless constraints are relaxed or a matching
  label/hostname is set for a manual smoke test. Still exercises the real
  `start_session`/`stop_session` -> stack-controller -> `docker stack
  deploy/rm/services` -> queue-drain code path end to end, which is what
  actually needed verifying. Not yet run against a real single-node swarm on an
  actual dev machine (only smoke-tested with FastAPI's `TestClient` against
  `stack_controller` directly, off swarm -- see §4).
- **M5** — Staging/lab cutover, one full test-session cycle before trusting it
  for a live run. Still not started -- needs the real AMS host.
- **M6** — Camera stack: done via §2 above, modulo the node-label ops task noted
  there.

---

## 4. Test environment gap

> **Status: mostly resolved.** A `.venv` was created at the repo root (gitignored
> already; not committed) with `project/requirements.txt`,
> `stack_controller/requirements.txt`, plus `httpx`/`pandas` (test-only deps the
> suite needed but that weren't in either requirements file). Full suite run from
> repo root with `PYTHONPATH=project` (needed because `fast_server/main.py` does
> `from fast_server import loggers`, an absolute import that requires `project/`
> itself on `sys.path`, not just the repo root -- pre-existing, unrelated to this
> feature).
>
> Result: `channel_test.py` and `channel_integral_test.py` pass clean (3/3 each)
> and cover code adjacent to what changed. Several **pre-existing, unrelated**
> failures surfaced that predate this branch and aren't touched by any of this
> work: `sessions_test.py`/`backup_integral_test.py` patch a
> `fast_server.main.log_system_logger` name that doesn't exist (the code calls
> `loggers.log_system_logger(...)`, never imports it by that bare name);
> `parse_test.py`/`parse_test_integral.py` have fixtures/assertions out of sync
> with `parsing.py`'s current field-count check; `backup_test.py` hardcodes
> `LOG_DIR = Path("/fast_server/logs")`, which only exists inside the container;
> `tcp_test.py` does `from logging_config import ...`, which only resolves when
> run from inside `project/tests/` directly, not as `project.tests.tcp_test`.
> Worth a separate cleanup pass, but out of scope here since none of it is
> new behavior from this feature.
>
> The new `stack_controller` and `drain_queues()`/robot-status code has **no
> checked-in test coverage yet** (there was none to begin with for
> `start_session`/`stop_session`, despite the name `sessions_test.py`). It was
> verified with throwaway scripts instead: `stack_controller`'s FastAPI app via
> `TestClient` (health, missing/bad bearer token, unknown stack name all return
> clean responses; `/status` against a non-swarm-manager Docker daemon returned
> an unhandled 500 until `docker_ops.get_stack_status` was fixed to catch
> `docker.errors.APIError`/`DockerException` and return a clean `state: "error"`
> body -- same fix shape as the existing deploy/remove error handling), and
> `drain_queues()`/`get_robot_queue_status()` against fake `aiohttp.web` status
> servers (immediate drain when clear, correct timeout+report when robot is
> stuck, correct timeout+report when only an in-flight `*_pending` batch is
> outstanding, fail-safe "not empty" when `tcp` is unreachable). Recommend adding
> real `unittest` coverage for these before M5 if this is meant to stay
> maintainable -- flag if you want that written up now.
