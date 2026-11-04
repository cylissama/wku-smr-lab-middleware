# Back-to-back sessions: analysis and fix plan

Prompt: `plans/session-testing.md`. Written 2026-11-02 from the code on
`dev/sim-plc` and the prod logs (fastapi-app, stack-controller, mosquitto).

## Status (2026-11-02, branch `dev/session-readiness`)

- Step 1 (backup out of the lock): done, `b27af04`. The prod test then showed
  a session ending mid-backup got none, so now one follow-up backup runs
  (`46736cd`).
- Step 2 (remove waits for teardown): done, `145d7d3`. Verified on prod:
  each stop returned about 1 s after the last edge client left the broker.
- Steps 3–5, AMS side only (user decision: no edge-repo changes for now):
  done. Status counts only current-deploy tasks and reports `since`
  (`0f9e544`); unplaceable services are `unavailable`;
  health checks run every 1 s while starting; `edge_ready_monitor` announces
  "Edge ready" with the exact time; dashboard banner, Start held while busy.
- Step 6 (edge agents say when they're armed): not started, by decision.
  Without it, "ready" means healthy, which includes "can't reach PLC".
- imu-111 / RPI-IMU-BENCH: out of scope (user). Its service now shows as
  `unavailable` and doesn't hold readiness up.

## 1. Is the "edge containers aren't ready yet" idea right?

Partly. The edge containers do take time to come down and come back up, and
nothing in the system knows when they're done. But measured today, they're
not the main source of the lag.

Today's three sessions (525–527), timings from the logs:

| Step | Measured | Source |
|---|---|---|
| Stop: gate closed → `docker stack rm` returns → capture `idle` | **0.2 s** | fastapi `Capture mode ->` lines |
| Stop: edge clients actually leave the broker | **3–4 s** after the stop | mosquitto `disconnected` lines |
| Stop: `pg_dump` backup, **still holding `session_lock`** | **21–23 s** | `Session N stopped` → `DB backup written` |
| Start: `docker stack deploy` → edge clients on the broker | **~2 s** | mosquitto `New client connected` |
| Start: dashboard shows the device as `running` (Swarm healthcheck passed) | ~10–12 s (first check runs after `interval: 10s`) | `deploy/swarm-edge-nodes.yml` |

(Those were Stop-button stops. There's been no PLC `Db_Stop` pulse since
fastapi-app last restarted, but a PLC stop runs the same `_stop_session()`.)

### What actually causes the lag/freeze (most likely first)

1. **The backup holds `session_lock` (verified).** `_stop_session()` calls
   `try_backup()` (about 22 s of `pg_dump` to the NAS) before it returns, and
   both the PLC path and the button hold `session_lock` the whole time. Capture
   goes `idle` after 0.2 s, so the dashboard's next poll turns Start back on.
   A Start clicked in the next ~20 s just hangs on the lock with no feedback.
   After a PLC stop nobody pressed Stop, so the dashboard doesn't show
   "Stopping..." either. This matches "lag and freeze" well.
2. **The robot gets started before the IMUs are armed (likely, but not
   seen in the logs).** With `IMU_PLC_TRIGGER_ON_RECORD=true` (current root
   `.env`), a recording IMU only reacts to a `Data_Start` that comes *after*
   its container started. `start_session` returns "Session ready" as soon as
   `docker stack deploy` returns, which only means the service specs were
   created. If the robot starts during those ~2 s (or before the new task
   replaced the monitoring one), that IMU waits for a `Data_Start` that already
   happened. The dashboard then shows "running · no data", which looks like a
   freeze. Your readiness flag is the fix for this one.
3. **The teardown race you described (real, but hidden right now).**
   `docker stack rm` returns after deleting the services. The containers on the
   Pis stop 3–4 s later, and the overlay network is removed after that. A
   deploy inside that window starts new tasks while the old ones still hold the
   same MQTT client ID (IMUs use their device id), the `/run/imu-hw` socket and
   the camera. Today the 22 s backup lock always outlasts that window, so the
   race can't happen. **Fixing #1 on its own would expose it**, so #1 and #3
   have to ship together.

## 2. Readiness scaffolding we already have

| What | Where | Gap |
|---|---|---|
| Per-stack status: `not_deployed` / `deploying` / `running` / `error`, per service `desired`/`running` | `stack_controller/docker_ops.py:get_stack_status`, `GET /stacks/{name}/status` | **Never returns `removing`**: once `stack rm` deletes the services it says `not_deployed` while containers are still stopping. Counts *any* running task, so during the MONITOR→RECORD redeploy the old (shutting-down) task makes the new service look `running`. A service pinned to a Down node (`imu-111` → `RPI-IMU-BENCH`, Down right now) stays `deploying` forever. |
| Swarm healthchecks on every edge service (task stays `starting` until healthy) | `deploy/swarm-edge-nodes.yml` (`imu_edge healthcheck`, `camera_edge healthcheck`) | Healthy means "process alive", not necessarily "armed for `Data_Start`". Need to check what `imu_edge healthcheck` tests (IMU repo). |
| Per-device state + `receiving`/`rate`/`last_seen_s` | `GET /devices` (`fast_server/main.py:get_devices`), `LiveSampler.activity()` | No overall "edge ready" answer; the dashboard has to infer it. |
| Dashboard styles for `deploying` ("starting") and `removing` ("stopping") | `web/src/lib/deviceState.js` | `removing` is never sent, so that style never shows. |
| Per-stack lock in stack-controller (409 while an action runs) | `stack_controller/main.py:get_lock` | Released as soon as `stack rm` returns, before teardown is done. |
| `STOPPING` capture mode, `last_stop`, `session_lock` | `fast_server/main.py` | `STOPPING` ends before the backup; the lock is held through it. Nothing tells the dashboard the lock is busy. |
| `docker stack rm --detach=false` (waits until tasks and networks are gone) | stack-controller's CLI is 27.5.1, which has it | Unused. (`deploy --detach=false` exists too, but it waits for the *whole* stack to converge, which never happens while `RPI-IMU-BENCH` is Down, so don't use it.) |

## 3. Fix plan

Order matters: 1 and 2 ship together (see #3 above). Commit after each step.

### Step 1: take the backup out of the lock
- `_stop_session()`: once capture is `idle`, start the backup with
  `start_background(...)` instead of awaiting it. A module-level `backup_task`
  stops two backups overlapping (a second stop while one runs is logged and skipped).
- The stop response returns `"backup": {"started": true}`. The result already
  reaches the dashboard via `/ws/misc` ("DB Backup Completed"/"Failed to backup").
  `DataDashboard.jsx` doesn't read `data.backup`, so nothing else changes.
- `POST /backup` and `restore_backup` check `backup_task` and refuse while it's running.
- `pg_dump` takes a consistent snapshot, so the next session's inserts during a
  backup are fine (they just aren't in that dump).
- Tests: `tests/sessions_test.py`: stop returns before a slow mocked
  `create_backup` finishes; a start right after the stop isn't blocked by it.

### Step 2: make "removed" mean removed
- `docker_ops.remove_stack`: `docker stack rm --detach=false`, timeout 60 s
  (expected ~4 s). On timeout, return success with `"teardown_confirmed": false`
  rather than failing the stop.
- stack-controller tracks the action in progress per stack (`_actions[name] =
  "deploying" | "removing"`, set under the existing lock), and `GET .../status`
  reports `state: "removing"` while a remove runs. The dashboard's existing
  "stopping" style then shows up with no frontend change.
- Because `remove_managed_stacks()` now waits for teardown inside
  `_stop_session()` (under `session_lock`), a start can't overlap a teardown.
  The extra ~4 s happens with the gate already closed, so no data is affected.
- Tests: stack-controller tests for the `--detach=false` arg and the
  `removing` state while the lock is held.

### Step 3: honest per-device readiness
- `get_stack_status`: count only tasks with `DesiredState == "running"`
  (the old task during a redeploy has desired `shutdown`). Also report
  `UpdateStatus.State == "updating"` as `deploying`.
- A service whose newest task is `pending` with a placement error ("no suitable
  node") becomes `state: "unavailable"` with the error. That's distinct from
  `deploying`, so a Down Pi doesn't block readiness forever. Add an
  `unavailable` style to `deviceState.js` (grey, "node down").
- Tests: `get_stack_status` against fake task lists (old+new task, pending on
  Down node, healthy).

### Step 4: one "edge ready" answer
- `GET /capture` gains `busy` (`session_lock.locked()`, plus what's running:
  `starting`/`stopping`/`redeploying`) and `edge`:
  `{"ready": bool, "waiting_for": [device keys], "unavailable": [...], "since": ts}`.
  It's computed from the step 3 states for the selected stack devices. The
  robot is excluded: it connects to tcp on its own.
- fastapi-app broadcasts one `/ws/misc` message when `ready` flips to true in
  RECORD, e.g. "Edge ready: start the robot". This replaces today's "start the
  robot once they show as running" message, which goes out before anything is up.
  Log it with `log_event(category="session")` so the start→ready time is in the logs.
- Tests: readiness computed from mocked `/devices` data for each mode.

### Step 5: dashboard
- Start/Monitor buttons disabled while `capture.busy` (no more clicks that silently hang).
- A readiness banner in the session panel: amber "Edge starting (3/5),
  waiting for imu/106, camera/113_front", green "Edge ready: start the robot",
  grey "Stopping edge nodes...". Use `unavailable` devices as a warning line,
  not a blocker.
- Poll `/capture` at the faster 3 s rate while `busy` or not yet ready.

### Step 6 (optional, edge repos): "armed" instead of "healthy"
- Healthy ≠ armed. For the exact moment the robot may start, the IMU node
  should report it: either make `imu_edge healthcheck` fail until the PLC is
  connected and it's waiting for `Data_Start`, or publish a retained
  `status/imu/<id>` (`armed`/`streaming`, with an MQTT will of `offline`).
  The second also gives readiness in ~2 s instead of the healthcheck's ~10 s.
- Further option, needs the lab's sign-off: write an `AMS_Ready` BOOL to the
  PLC so the robot program interlocks on it. Writing to the real cell PLC
  is a safety decision, not just a code change.

## 4. Test procedure (the "session testing" itself)

Run on prod in a free lab slot, with the real stacks:
1. Baseline (before step 1): start → PLC stop → Start immediately. Expect the
   start to hang about 20 s (backup). Record the times from the logs.
2. After steps 1–2: the same sequence. Expect Start disabled for about 4 s
   (teardown), then a normal start. Check mosquitto shows no client-ID takeover
   (`already connected`) and stack-controller shows no deploy errors.
3. After steps 3–5: start → wait for "Edge ready" → start the robot. Then
   start the robot *before* ready on purpose and confirm the banner explains
   the missing IMU data.
4. MONITOR → RECORD with `IMU_PLC_TRIGGER_ON_RECORD=true`: confirm the IMUs
   show `starting` (not `running`) until the new tasks are healthy.
5. Five stop/start cycles back to back with `PLC_FAKE=true` and
   `PLC_FAKE_SPEED` turned up. Nothing should hang, and every session should
   get IMU rows.

## 5. Open questions

- What does `imu_edge healthcheck` actually check? (Decides whether step 6 is needed.)
- Is `RPI-IMU-BENCH` (imu-111) supposed to be in "all devices"? Right now it
  keeps the edge stack `deploying` permanently.
- After a PLC stop, should the dashboard offer an automatic "ready for next
  run" chime/notification, or is the banner enough?
