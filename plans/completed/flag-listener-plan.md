# PLC Flag Listener: Stop the Session When the Robot Finishes

> Plan for the ask in `flag-listener.md`. The cell's PLC raises a tag when the
> robot finishes its move. The AMS should watch that tag and, when it turns 1,
> stop the current session the same way the dashboard's **Stop** button does.

> **Status (2026-10-13):** built on `dev/monitor-mode`, not yet deployed. Decisions:
> `Db_Stop` is a **brief pulse** (not latched); it does **not** end monitor mode;
> no `stop_source` column (logs/broadcast only). Differences from the draft below:
> a pulse during a session *start* is **ignored** instead of queued behind it
> (§3.3), and a Stop click just after a PLC stop answers "already stopped"
> instead of erroring (§3.3). Tests: `tests/plc_listener_test.py` (18). The
> watcher has been checked read-only against the real PLC. Operator doc:
> `web/docs/operations/plc-auto-stop.md`.

---

## 1. What already exists

### The edge-node implementation (`wku-smr-lab-imu-edge-node@plc_update`)

`imu_edge/plc_signals.py` (commits `a9ece73` "pycomm3" and `19fed9a`, Oct 7 and 9):

- **Library:** `pycomm3.LogixDriver(path, init_connection=False, large_packets=False)`.
  This is EtherNet/IP (CIP) over TCP 44818, reading tags by name. The PLC does not
  broadcast anything. It is **polled**, by default every 50 ms.
- **Tags:** `Data_Start` (start a run), `IMU_Tare` (tare), `Db_Stop` (end of run).
  The names can be changed through `IMU_PLC_TAG_*` env vars.
- **Edge detection:** `PLCSignalWatcher` runs in a daemon thread. It counts
  **rising edges** (OFF→ON) per tag and ignores ON→OFF. A tag that is already ON
  on the first read is not counted. After a reconnect the last known values are
  kept, so the reconnect itself never looks like a new edge. Consumers compare
  `stop_count` to the count they saw earlier.
- **Fake PLC:** `FakePLC` replays a timeline (`Data_Start` pulse at 3 s,
  `IMU_Tare` pulse at 10 s, `Db_Stop` ON at 25 s and *stays on*) so the logic can
  be tested without the robot.
- **Use on the node:** `agent._run_plc_triggered` waits for `Data_Start`, streams
  IMU data, tares on `IMU_Tare`, and ends the node's run on `Db_Stop` (or after
  `IMU_PLC_MAX_RUN_S`). The node ends only its *own* run. It never tells the
  AMS, so the session stays open.

### Verified from the AMS host (2026-10-13)

| Check | Result |
|---|---|
| Route AMS (`192.168.2.100`) → PLC `L32E` (`192.168.1.103`) | ping OK, ~2.7 ms |
| TCP 44818 from the host | open |
| Read from a throwaway container on a Docker bridge network (same NAT path fastapi-app uses) | works |
| PLC identity | `1769-L32E/A LOGIX5332E`, rev 17.4, keyswitch **RUN** |
| `Data_Start`, `IMU_Tare`, `Db_Stop` | all exist, type **DINT** (not BOOL), currently `0` |

The tags are DINTs, so "reads as 1" means `value != 0`. The watcher's
`bool(result.value)` already handles that.

### The stop path we have to reproduce

`GET /session/stop` → `stop_session()` in `fast_server/main.py:796`:
`STOPPING` → `remove_managed_stacks()` → `drain_queues()` → `end_session()` →
`IDLE` → logs/broadcast → `try_backup()`. It already handles a DB outage
(`pending_session_end`). Nothing serializes it: two overlapping calls (button +
PLC, or a double click) would both remove stacks, both end the session and both
take a backup.

The dashboard polls `GET /capture` every 5 s (`DataDashboard.jsx:170`), so it
will see a stop it didn't start without any frontend change.

---

## 2. Where to put it: inside `fastapi-app` (recommended)

| Option | Verdict |
|---|---|
| **A. Background task in `fastapi-app`** (new `fast_server/plc_listener.py`) | **Recommended.** fastapi-app owns `capture` and `stop_session`, so the PLC calls the *same function* the button route calls, under the same lock. Status goes into the existing `HealthRegistry` and `/health`, and the dashboard's health box shows it with a one-line label change. pycomm3's blocking socket runs in the watcher's own thread, so a hung PLC connection can't stall the event loop (same reasoning as the logger thread). Cost: one small pure-Python dependency in the fastapi image. |
| B. New `plc-listener` container that calls `GET /session/stop` | Workable, but it adds another service, healthcheck, env block and Docker Hub image. It would have to poll `/capture` to know whether a session is recording, and it still needs the lock inside fastapi-app. Worth it only if the PLC later drives many more things. |
| C. Edge nodes POST to the AMS on `Db_Stop` | Rejected. Every selected IMU would fire, so N stop requests per run. The stop tears down the edge stacks that sent it. And whether a session gets stopped would depend on which devices are selected. |
| D. In `tcp_server` | Rejected. It's unrelated to the robot TCP feed and doesn't own capture state. |

---

## 3. Design

### 3.1 `fast_server/plc_listener.py` (new)

Port `PLCSignalWatcher`, `FakePLC` and `build_plc_factory` from the edge repo
almost verbatim, with these changes:

- The tag list is a constructor argument (`tags: tuple[str, ...]`) instead of the
  fixed start/tare/stop triple. We only watch `Db_Stop` now, and adding
  `Data_Start` later costs nothing.
- `counts()`, `values()`, `connected` and `last_error` are exposed for `/health`.
- The "tag doesn't exist" error is kept separate from connection loss, so health
  can say *which* one it is.
- A short header comment credits the edge-repo origin so the two copies stay
  recognisably the same.

### 3.2 `plc_supervisor()` in `main.py`

Started from `startup()` with `start_background(run_forever("plc_supervisor", ...))`,
only when `PLC_AUTO_STOP` is on. It does not depend on the DB, the same as the
MQTT supervisor.

```text
watcher.start()
seen = watcher.count("Db_Stop")
loop every 0.1 s:
    if watcher.count("Db_Stop") > seen:
        seen = watcher.count("Db_Stop")
        if capture.mode == RECORD:
            log_event("PLC Db_Stop ON -> stopping session N", category="session", important)
            broadcast misc: "Robot finished (PLC Db_Stop) -- stopping session N"
            await stop_session_locked(source="plc", expect_session=capture.session_id)
        else:
            log_event("PLC Db_Stop ON ignored (capture is <mode>)", important=False)
    every HEALTH_INTERVAL: health.ok/down("plc", connected, last_error, path, tag value)
```

### 3.3 Serialize start and stop (fixes the double-stop race)

Add `session_lock = asyncio.Lock()`:

- The `/session/start` and `/session/stop` routes take the lock around their
  current bodies. Move the bodies into `_start_session(...)` and
  `_stop_session(source)` so the behavior doesn't change.
- The PLC path takes the lock, then **re-checks** `capture.mode == RECORD and
  capture.session_id == expect_session` before calling `_stop_session("plc")`.
  If the operator already pressed Stop, or a new session started in between, the
  PLC edge does nothing.
- **As built:** a `Db_Stop` pulse that arrives while the lock is held (a start
  is still deploying its stacks, or a stop is already running) is **ignored and
  logged**, not queued. A pulse during a start belongs to the robot's previous
  run, not the session being started.
- **As built:** `last_stop` remembers the last successful stop. A Stop click
  within 30 s of it, while capture is still `IDLE`, returns
  `{"success": true, "already_stopped": true}` instead of failing with "no
  active session". This covers the up-to-5 s dashboard lag after a PLC stop.

`_stop_session` takes a `source` (`"dashboard"` | `"plc"`) used only in log and
broadcast text: "Session 42 stopped (PLC Db_Stop)" vs "Session 42 stopped". No
schema change (see open question 3).

### 3.4 Rules for when an edge counts

| Situation | Behavior |
|---|---|
| `RECORD` | stop the session (backup included, same as the button) |
| `MONITOR` / `IDLE` / `STOPPING` | log it (not important), do nothing |
| `Db_Stop` already 1 when fastapi-app starts | not counted (first-read rule) |
| `Db_Stop` latched at 1 from the last run when a new session starts | not counted until it drops to 0 and rises again |
| PLC unreachable during a pulse | missed (`Db_Stop` is a pulse, not latched): health shows `plc` down and the operator uses the button |
| `PLC_AUTO_STOP` off | no thread, no `plc` health component, button-only as today |

### 3.5 Config (env, documented in `.env.example`)

| Var | Default | Notes |
|---|---|---|
| `PLC_AUTO_STOP` | `false` in code, `true` in prod `.env` | master switch |
| `PLC_PATH` | `192.168.1.103` | pycomm3 path, so `ip/slot` also works |
| `PLC_TAG_STOP` | `Db_Stop` | |
| `PLC_POLL_S` | `0.05` | same as the edge |
| `PLC_RETRY_S` | `1.0` | reconnect delay |
| `PLC_FAKE`, `PLC_FAKE_SPEED` | `false`, `1.0` | use `FakePLC`, for `docker-compose.local.yml` and tests |

`requirements.txt`: `pycomm3==1.2.16` (the current release, same library as the edge).

### 3.6 Dashboard

- `web/src/lib/systemHealth.js`: add `plc: "PLC (robot done)"` to `COMPONENT_LABELS`.
  The health box already renders whatever components `/health` returns.
- Optional: a small "Auto-stop: armed / PLC unreachable" hint next to the Stop
  button, from `/health` `components.plc`. Skip this in the first cut unless wanted.

---

## 4. Work breakdown

1. **`fast_server/plc_listener.py`**: watcher, fake PLC, factory (§3.1).
2. **`main.py`**: `session_lock`, the `_start_session` / `_stop_session(source)`
   split, `plc_supervisor`, `"plc"` added to the `HealthRegistry` when enabled,
   startup wiring (§3.2–3.3).
3. **Config**: `requirements.txt`, `.env.example`, compose `environment`
   pass-through, `PLC_FAKE=true` in `docker-compose.local.yml`.
4. **Tests** (`unittest`, run in the `smr-test` image):
   - `tests/plc_listener_test.py`: rising edges counted once; already-ON at start
     not counted; ON→OFF ignored; reconnect gives no false edge; DINT `1` counts
     as ON; a missing tag shows up in `last_error`.
   - `tests/plc_autostop_integral_test.py` (TestClient + fake watcher): an edge in
     RECORD calls the stop exactly once; an edge in MONITOR/IDLE does nothing; a
     button stop and a PLC edge at the same time give one stop and one backup; an
     edge during a start waits, then stops that session.
5. **Dashboard label** (§3.6) and `npm run lint`.
6. **Docs**: a new `web/docs/operations/plc-auto-stop.md` (what the tag is, how to
   turn it off, what the health entry means), a line in `running-a-test.md`, and
   a CLAUDE.md architecture bullet.
7. **Prod rollout**: no session running → tag `:pre-plc-autostop` rollback images
   → build → you recreate `fastapi-app` (and `web` for the label). Verify:
   `/health` shows `plc ok`, and the startup log shows the watcher connected
   and reading `Db_Stop=0`.
8. **Live test with the robot**: start a short test session → robot run →
   `Db_Stop` rises → session ends, backup taken, dashboard flips to idle within
   about 5 s. Repeat with `MONITOR` to confirm it's ignored.

---

## 5. Decisions and remaining questions

1. ~~Pulse or latch?~~ **Pulse** (brief). It is polled at 50 ms, so a pulse
   shorter than about 100 ms could be missed; the edge nodes see ~1 s pulses.
2. ~~Stop monitor mode too?~~ **No**: only a recording session is stopped.
3. ~~Record who stopped it?~~ **No**: logs and broadcast only, no schema change.
4. **Later: `Data_Start` → auto-start?** Not in scope, but the watcher is built
   for it. It would need a rule for the session label and device selection (for
   example "use the last selection, label = timestamp").
5. **Edge nodes in `IMU_PLC_TRIGGER` mode** also end their own run on `Db_Stop`.
   That's harmless: the AMS then removes their stacks as part of the stop. They do
   wait for `Data_Start` *after* the AMS deploys them, so a session opened after
   the robot has already started would record nothing from them until the next
   `Data_Start`.

---

## 6. Follow-up: IMU PLC trigger per capture mode (2026-10-13)

**Ask:** monitoring should run the IMU edge nodes with `IMU_PLC_TRIGGER=false`
so devices can be checked without waiting for the PLC; a real session should
run them with `IMU_PLC_TRIGGER=true` so the robot's `Data_Start` / `IMU_Tare` /
`Db_Stop` drive what they send.

**Where the value comes from today:** `deploy/swarm-edge-nodes.yml` passes
`IMU_PLC_TRIGGER: "${IMU_PLC_TRIGGER:-false}"` to each IMU service. stack-controller
fills that in from `deploy/.env` (`env_file` in `stacks.yml`) when it runs
`docker stack deploy`. One fixed value, whatever the mode.

**Design (built):**

| Piece | Change |
|---|---|
| `stack_controller/main.py` | `DeployRequest.env` holds per-deploy overrides layered over `env_file`. Only the names in the stack's `env_overrides` list are accepted; anything else gets a **400**, so the token can't rewrite arbitrary stack config. The response echoes the `env` applied. |
| `stack_controller/stacks.yml` | `edge: env_overrides: [IMU_PLC_TRIGGER]` |
| `fast_server/main.py` | `MONITOR_STACK_ENV = {IMU_PLC_TRIGGER: false}` and `RECORD_STACK_ENV = {IMU_PLC_TRIGGER: true}` (`IMU_PLC_TRIGGER_ON_RECORD=false` turns the latter off). `/listen/start` deploys with the monitor env; `/session/start` deploys with the record env. |
| Monitor → session | Used to skip the redeploy when the selection was unchanged. Now it redeploys whenever the settings differ, which they do by default. `docker stack deploy` only updates services whose spec changed. Rendering both modes with `docker stack config` shows exactly the 5 IMU services differ, so only the IMUs restart and the cameras keep running. If that redeploy fails, the session is rolled back and capture returns to **MONITOR** (it used to drop to IDLE with the stacks still up). |
| Operator message | When a session starts with IMUs selected and the trigger on, `/ws/misc` says the IMUs are restarting and to start the robot once they're running. |

**The catch, and why the message:** an IMU only counts a `Data_Start` that rises
*after* its watcher's first read (`plc_signals.py` first-read rule). A robot
started while the IMU containers are still restarting is missed by those IMUs,
which then send nothing for that run. Until the robot starts, the dashboard
shows the IMUs as not receiving; that's expected.

**Tests:** `tests/stack_controller_test.py` (override applied, env_file kept,
unlisted var refused) and `tests/capture_test.py` (monitor deploys with false,
session with true, monitor→session redeploys, a skip only when the settings
match, a failed redeploy returns to MONITOR).

**Prerequisite:** the IMU image on the Pis (`smart-mfg-imu:latest`) has to be
built from the edge repo's `plc_update` branch, or `IMU_PLC_TRIGGER` does nothing.
