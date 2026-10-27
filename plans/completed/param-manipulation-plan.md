# Run Parameters: Edit Edge/Session Settings From the Dashboard

> Plan for the ask in `param-manupulation.md`. Settings like `IMU_SAMPLE_HZ` and
> the IMU PLC trigger currently live in the two `.env` files and
> `deploy/swarm-edge-nodes.yml`, so changing them between runs means SSH and an
> editor. The goal is a **Run Parameters** panel in the dashboard's right gutter
> (styled like the left Device Rail) that shows each parameter's current value,
> can be edited between runs, and is locked while a session is recording.

> **Status (2026-10-22):** built, deployed and committed on `dev/device-graphics` (`ed4e035`).
> Decisions: edits allowed in MONITOR with an immediate redeploy; the §3 list
> minus `CAMERA_MARKER_LENGTH_M` (dropped: never changed);
> `IMU_SAMPLE_HZ` capped at 200 (not load-tested); values stay set between runs.
> Kept smaller than the draft below:
> - Definitions and value checks live only in `fast_server/run_params.py`, the
>   point where browser input arrives. `stacks.yml` `env_overrides` stays a
>   plain list (now 4 names), and a test checks the two agree. No typed
>   mapping.
> - stack-controller gained `GET /stacks/{name}/env` (only `env_overrides`
>   values) instead of `/parameters`.
> - No revision/stale-write check: last save wins, and only the edited keys
>   are sent.
> - While recording, the panel shows the current values. They can't change
>   then, so they match the session snapshot unless `deploy/.env` is edited
>   mid-session.
> - Same component in both places: the right gutter at ≥1840px, under the
>   Devices box below that.
>
> Also: `/listen/start` and `/listen/stop` now hold `session_lock`, so a
> parameter save can't race a monitor start/stop. Tests:
> `tests/run_params_test.py` (20) plus 2 in `stack_controller_test.py`.
> Operator doc: `web/docs/operations/run-parameters.md`.

---

## 1. What already exists

### How values reach the edge nodes today

```
deploy/.env ──(read fresh on every deploy)──▶ stack-controller ──▶ docker stack deploy
                                                   ▲                (interpolates ${VAR}s
fastapi-app ── POST /stacks/edge/deploy ───────────┘                 in swarm-edge-nodes.yml)
               body: {services, env: {IMU_PLC_TRIGGER: "true"}}
```

- **`deploy/.env`** (gitignored, mounted read-only into stack-controller as
  `/stacks/.env`) holds everything the edge stack interpolates: device IDs and
  hostnames, `MQTT_BROKER_IP`, `IMU_SAMPLE_HZ`, camera calibration paths, etc.
- **Per-deploy overrides already exist.** `DeployRequest.env` in
  `stack_controller/main.py` is layered over the `env_file` for that one deploy.
  `check_env_overrides()` refuses (400) any variable not listed under the stack's
  `env_overrides` in `stack_controller/stacks.yml`. Today the list is just
  `[IMU_PLC_TRIGGER]`.
- **fastapi-app picks the overrides per mode.** `MONITOR_STACK_ENV` /
  `RECORD_STACK_ENV` in `fast_server/main.py:221` are fixed at import time, and
  `RECORD_STACK_ENV` comes from `IMU_PLC_TRIGGER_ON_RECORD` in the root `.env`.
  `_start_session()` skips the redeploy from MONITOR only if the selection is
  unchanged **and** `RECORD_STACK_ENV == MONITOR_STACK_ENV`.
- **Every monitor start and every session start redeploys** the edge stack
  (except the MONITOR→RECORD case above). So "per run" values need no new
  delivery path. They only need to go into that `env` dict.
- **`session.devices` (JSONB)** already records a per-session choice (the
  device selection) and is restored on startup. A parameter snapshot can follow
  the same pattern.

### What `IMU_SAMPLE_HZ` actually does (edge repo, `plc_update` branch)

- `imu_edge/config.py`: `sample_hz = max(1, int(IMU_SAMPLE_HZ))`. **No upper
  bound.**
- The edge agent sends `sample_hz` to the host IMU daemon (`imu_host`) in its
  `start_session` request over `/run/imu-hw/imu.sock`. `imu_host/manager.py`
  sleeps `1/sample_hz` between reads. If a read takes longer than that interval,
  the loop just runs as fast as the hardware allows.
- **Caveat:** in PLC mode the agent ignores `SESSION_ALREADY_ACTIVE`
  (`agent.py` ~L170). If the host daemon still has a session open from the
  previous container, the **old rate stays**. `IMU_STOP_SESSION_ON_EXIT=true`
  (the value in `deploy/.env`) ends the host session when the container stops,
  so a redeploy should pick up the new rate. This needs a check on a real Pi
  (§7).
- **Load:** 6 IMUs × 100 Hz is about 600 rows/s into the NAS Postgres. 200 Hz
  doubles that. The bound we set is the only thing that stops someone from
  typing 5000.

### The dashboard

- `web/src/DataDashboard.jsx` switches to a 3-column grid
  `grid-cols-[1fr_minmax(0,80rem)_1fr]` at `min-[1840px]` (uncommitted, on this
  branch). The left column holds the sticky `DeviceRail` (`dev-rail` styles in
  `App.css`). **The right column is empty.** The new panel goes there.
- Below 1840px the rail is hidden. That's fine for a status display, but a
  panel you have to use to change settings must stay reachable on smaller
  screens (§5.3).
- The dashboard has no login. Anyone who can open it can already start/stop
  sessions and restore backups. The parameter panel doesn't make that worse,
  but it's another reason to keep strict bounds on every value.

---

## 2. Do parameters and environment variables live in the same place? **No.**

They change at different rates, are changed by different people, and carry
different risks. Split them into three layers:

| Layer | Examples | Where it lives | Who changes it | Takes effect |
|---|---|---|---|---|
| **Infrastructure & secrets** | `DB_*`, ports, `HOST_IP`, `STACK_CONTROLLER_TOKEN`, device IDs/hostnames, `MQTT_BROKER_IP`, calibration paths, PLC path/tag names | The two `.env` files, **unchanged** | Admin, over SSH | Recreate / next deploy |
| **Parameter definitions** (the allowlist: name, type, bounds, unit, label) | "`IMU_SAMPLE_HZ` is an int, 1–200, Hz" | Committed config: `stack_controller/stacks.yml` for edge params, `fast_server/run_params.py` for AMS-side params | Developer, through a PR | Container restart |
| **Run values** (what the next run uses) | `IMU_SAMPLE_HZ=200` | fastapi-app: a small JSON file on a local volume, **plus a snapshot in `session.parameters`** for each session | Operator, from the dashboard, while not recording | Next deploy (monitor start / session start) |

The `.env` value stays the **default**. The dashboard only stores
**overrides**. "Reset" deletes the override, so the run falls back to `.env`.
That keeps the current behavior when nobody touches the panel, and a manual
`docker stack deploy` from the shell still works (it uses the defaults).

### Options considered for storing run values

| Option | Verdict |
|---|---|
| **A. Dashboard writes back into `deploy/.env`** | **Rejected.** `deploy/` is mounted read-only on purpose. The file also holds infrastructure values and hostnames, so one bad write breaks every deploy. Rewriting it loses comments, keeps no history, and two writers can race. |
| **B. Overrides in a JSON file on a local volume owned by fastapi-app, snapshotted into `session.parameters`** | **Recommended.** Works with the DB down, which matches "nothing waits on the DB": monitor mode still deploys with your values. It survives container restarts and image rebuilds. Writes are atomic (temp file + `os.replace`). The DB snapshot is the permanent record of what each session actually ran with. |
| C. Overrides in a Postgres table | Workable, but with the DB down, monitor mode would quietly fall back to `.env` defaults, and the panel couldn't show what's set. The DB still gets the per-session snapshot under option B, which is the part researchers need. |
| D. In-memory only | Rejected. A fastapi-app restart (watchdog, crash, rebuild) would quietly revert someone's 200 Hz to 100 Hz between runs. |

---

## 3. Which parameters (v1)

Two kinds of parameter, depending on who acts on the value:

- **edge**: passed straight through as a stack env override and interpolated
  into `swarm-edge-nodes.yml`. stack-controller defines and validates these.
- **ams**: read by fastapi-app itself when it decides what to send. fastapi-app
  defines and validates these.

| Key | Kind | Panel label | Type / bounds | Default from | Notes |
|---|---|---|---|---|---|
| `IMU_SAMPLE_HZ` | edge | IMU sample rate | int, 1–200, Hz | `deploy/.env` | Upper bound to confirm by load test (§8). Shared by all IMUs. |
| `IMU_PLC_TRIGGER_ON_RECORD` | ams | IMUs wait for PLC start (record) | bool | root `.env` (current behavior) | This is what "change `IMU_PLC_TRIGGER`" means in practice. Monitor mode always sends `IMU_PLC_TRIGGER=false`, or monitoring would show nothing until the robot runs. The panel controls the **record** value. |
| `IMU_PLC_MAX_RUN_S` | edge | IMU max run (PLC mode) | int, 30–3600, s | `deploy/.env` (`600`) | Safety timeout if `Db_Stop` never arrives. Useful for long runs. |
| `CAMERA_MARKER_LENGTH_M` | edge | ArUco marker size | float, 0.005–0.5, m | `deploy/.env` (`0.0485`) | Changes when the markers are swapped. |

`IMU_PLC_TRIGGER` stays in `env_overrides` but is marked `managed: true`, so
it's hidden from the panel because fastapi-app sets it per mode.

**Not in v1, but easy to add later:** `PLC_AUTO_STOP` as a per-run toggle (the
watcher keeps running, and the toggle only decides whether a pulse stops the
session), `IMU_REQUEST_TARE`, and `IMU_PLC_FAKE` (a test aid, risky to leave
on). Adding one is a few lines of config (§6).

**Out of scope:** per-device values (e.g. only IMU 106 at 200 Hz). The compose
file has a single `${IMU_SAMPLE_HZ}` for every IMU. Per-device values would
need `IMU_106_SAMPLE_HZ`-style variables with a fallback, and we'd first have
to confirm that `docker stack deploy` supports nested `${A:-${B}}`
interpolation. Robot settings are also out of scope: the robot isn't deployed
by us.

---

## 4. Backend design

### 4.1 stack-controller: typed `env_overrides` + a read endpoint

`stacks.yml` `env_overrides` grows from a list into a mapping. A plain list
still means "any string", so the change is backward compatible:

```yaml
    env_overrides:
      IMU_PLC_TRIGGER: {type: bool, managed: true}   # set by fastapi-app per mode
      IMU_SAMPLE_HZ:   {type: int,   min: 1,     max: 200,  unit: Hz, group: imu,    label: IMU sample rate}
      IMU_PLC_MAX_RUN_S: {type: int, min: 30,    max: 3600, unit: s,  group: imu,    label: IMU max run (PLC mode)}
      CAMERA_MARKER_LENGTH_M: {type: float, min: 0.005, max: 0.5, unit: m, group: camera, label: ArUco marker size}
```

- `check_env_overrides()` also **validates values**: type, bounds, bools
  normalized to `"true"`/`"false"`, and no newlines or control characters.
  A bad value returns 400 with the key named. This is the last gate before
  `docker stack deploy`, so it holds even if fastapi-app has a bug.
- **New `GET /stacks/{name}/parameters`** (token-protected like the other
  `/stacks` routes) returns each `env_overrides` entry's definition plus its
  current value from `env_file`. **Only keys listed in `env_overrides`.** This
  route must never return the rest of `.env`, and a test checks that.
- `stacks.yml` is already read on every request (`load_stacks()`), so
  definition changes apply without a restart.

### 4.2 fastapi-app: parameter store + API

New `fast_server/run_params.py` (small, pure, unit-testable):

- `AMS_PARAMS`: definitions for the ams-kind params (just
  `IMU_PLC_TRIGGER_ON_RECORD` in v1), with the same fields as above. Defaults
  come from the root `.env` as they do today.
- `ParamStore`: loads/saves `{"revision": n, "values": {...}, "updated_at": ...}`
  at `RUN_PARAMS_PATH` (default `/state/run_parameters.json`). It writes
  atomically and bumps `revision` on every change. A missing file means no
  overrides. A corrupt file is logged with `log_event(WARNING)` and treated as
  no overrides, never as a crash.
- `effective(defs, defaults, overrides)` returns the merged values.
- `stack_env(mode)` builds the deploy env: the edge overrides, plus
  `IMU_PLC_TRIGGER` = `false` for MONITOR, or the effective
  `IMU_PLC_TRIGGER_ON_RECORD` for RECORD. This replaces the
  `MONITOR_STACK_ENV`/`RECORD_STACK_ENV` constants.

Routes in `main.py`:

| Route | Behavior |
|---|---|
| `GET /parameters` | Definitions (edge ones from stack-controller, with `.env` defaults, plus `AMS_PARAMS`), the current override and effective value for each, `revision`, `editable` + `locked_reason`. While recording, it also returns the **session's snapshot** (`session_parameters`), which is what is actually running. Works without the DB. If stack-controller is down, edge defaults show as unknown. |
| `PUT /parameters` | Body `{revision, values: {KEY: value \| null}}` (`null` = reset to default). Runs **under `session_lock`**: 409 if `capture.mode` is RECORD or STOPPING, 409 if `revision` is stale (another dashboard saved first), 400 with per-key errors on unknown keys or bad values. On success it saves, logs `log_event("Run parameters changed: IMU_SAMPLE_HZ 100→200", category="parameters")` and broadcasts on `/ws/misc` so other open dashboards refresh. In MONITOR it then redeploys (§4.3). |

### 4.3 Locking and timing (the "safe" part)

- **Server-enforced lock, not just a disabled input.** Two dashboards can be
  open, and the dashboard only polls. `PUT /parameters` and
  `/session/start` both hold `session_lock`, so a save can't land between a
  session start reading the values and deploying them.
- **Values are read once per session start.** `_start_session()` takes the
  snapshot (effective values for the record mode) under the lock and uses
  **the same dict** for the deploy `env` and for `session.parameters`. What's
  recorded is exactly what was deployed.
- **IDLE:** edit freely. Values apply on the next monitor/session start.
- **MONITOR (recommended, decision 1):** allowed. Saving redeploys the current
  monitored selection with the new monitor env, which restarts only the
  services whose env changed. You can watch the effect, e.g. the `rate` column
  in `/devices` going from ~100 to ~50 msg/s. If the redeploy fails, the values
  stay saved, the error is broadcast, and capture stays in MONITOR.
- **RECORD / STOPPING:** locked. The panel shows the session's snapshot values,
  which are the ones in use.
- **Deciding whether to redeploy from MONITOR to RECORD:** keep a module-level
  `deployed_env` (set after each successful `deploy_managed_stacks`, cleared on
  remove). The redeploy is skipped only if the selection is unchanged **and**
  `deployed_env == stack_env(RECORD)`. This replaces the constant comparison
  at `main.py:806`.
- A failed session start (deploy failure → rollback) doesn't touch the stored
  values.

### 4.4 Database

`db/migrations.md` entry + `db/schema.sql` + `create_session()`:

```sql
-- Run parameters per session: the effective values this session was deployed
-- with, e.g. {"IMU_SAMPLE_HZ": 200, "IMU_PLC_TRIGGER": true, ...}.
-- NULL for sessions before this change. Apply BEFORE deploying the matching
-- fastapi-app, whose create_session() writes it.
ALTER TABLE IF EXISTS public.session
    ADD COLUMN IF NOT EXISTS parameters JSONB;
```

Store **all** effective values, not just the overrides, so a row still makes
sense after `.env` defaults change. Researchers can then query it, e.g.
`SELECT id, parameters->>'IMU_SAMPLE_HZ' FROM session`, which isn't possible
today. Add `parameters` to `GET /sessions` too.

### 4.5 Compose

- New local named volume `fastapi_state:/state` on `fastapi-app` in
  `docker-compose.yml` and `docker-compose.local.yml`. **Local, not NFS.** It's
  tiny, and a hung soft NFS mount must not block a save.
- `RUN_PARAMS_PATH` env var, defaulting to `/state/run_parameters.json`.

---

## 5. Dashboard design

### 5.1 `ParamRail` in the right gutter

New `web/src/components/ParamRail.jsx`, placed in the empty third grid column
of `DataDashboard.jsx` (`justify-self-start`, `sticky top-14`, `w-64`, same as
the left rail). It reuses the `dev-rail` frame and adds `param-*` styles in
`App.css` that follow the same industrial look.

```
┌ // RUN PARAMETERS ──── IDLE ┐      ┌ // RUN PARAMETERS ── RECORD ┐
│ IMU                         │      │ ▣ LOCKED · SESSION 412       │
│ ┌─────────────────────────┐ │      │ IMU                          │
│ │ SAMPLE RATE    ● CHANGED│ │      │ SAMPLE RATE        200 Hz ▣  │
│ │ [  200  ] Hz            │ │      │ WAIT FOR PLC START     ON ▣  │
│ │ default 100 · 1–200     │ │      │ MAX RUN (PLC)      600 s  ▣  │
│ └─────────────────────────┘ │      │ CAMERA                       │
│ ┌─────────────────────────┐ │      │ MARKER SIZE    0.0485 m   ▣  │
│ │ WAIT FOR PLC START      │ │      └──────────────────────────────┘
│ │ [■■ ON ]  record only   │ │
│ └─────────────────────────┘ │
│ CAMERA …                    │
│ [ RESET ALL ]   [ APPLY ]   │
└─────────────────────────────┘
```

- One tile per parameter, grouped by `group`, showing label, value + unit,
  default and range, and a **CHANGED** marker when an override is set. The
  marker uses the left rail's accent colors.
- **Edits are drafts until Apply.** One PUT for all changes, so a half-typed
  value never goes out. Inputs validate against the min/max from
  `GET /parameters` before submitting, and the server re-checks. Per-key 400
  errors show on the matching tile.
- In MONITOR, the Apply button reads **APPLY · RESTARTS IMUs** (or whichever
  groups changed).
- Locked state comes from `captureMode` (already polled) plus `editable` from
  the API.
- Refreshes on load, after Apply, when a `/ws/misc` "parameters changed"
  message arrives, and when `captureMode` changes. No extra polling loop.
- A 409 for a stale revision shows: "Changed from another dashboard. Reloaded."

### 5.2 Start-session confirmation

The existing confirm step (`isConfirmingSession`) lists the **non-default**
parameters, e.g. "Recording with IMU sample rate 200 Hz (default 100)". This is
the last chance to catch a value left over from someone else's run.

### 5.3 Narrow screens (< 1840px)

The same component renders as a collapsible **Run parameters** card in the
main column, next to the device selector (`variant="card"`). One component,
two placements, so the panel is reachable at every width.

### 5.4 API client

Add `getParameters()` / `saveParameters(revision, values)` to a new
`web/src/api/paramsApi.js`, following `captureApi.js`.

---

## 6. Adding a parameter later (the workflow this enables)

1. Reference it in `deploy/swarm-edge-nodes.yml` (`FOO: "${FOO}"`).
2. Add its default to `deploy/.env` and `deploy/.env.example`.
3. Add a typed entry under `env_overrides` in `stack_controller/stacks.yml`.
   That's all: the panel picks it up on its next load.

An ams-kind param is one `AMS_PARAMS` entry plus the code that reads it.

---

## 7. Phases, tests, rollout

| Phase | Work | Tests |
|---|---|---|
| **A** stack-controller | Typed `env_overrides` (list form still accepted), value validation, `GET /stacks/{name}/parameters` | `tests/stack_controller_test.py`: bounds/type/bool normalization, list-form compat, unknown key 400, **parameters endpoint never leaks non-allowlisted `.env` keys** |
| **B** fastapi-app | `run_params.py`, `GET/PUT /parameters`, `stack_env()` replacing the constants, `deployed_env`, snapshot into `create_session()`, migration, compose volume | New `tests/run_params_test.py`: store round-trip + corrupt file + atomic write, merge, stack_env per mode. Integral: PUT 409 in RECORD/STOPPING, stale revision 409, MONITOR save redeploys, start-session passes the same dict to deploy and `create_session`, MONITOR→RECORD skip/redeploy decision. Update `sessions_test.py` for the new `create_session` arg |
| **C** dashboard | `ParamRail` (rail + card variants), confirm-dialog summary, `parameters` in session history | `npm run lint`, `npm run build`. Manual check in all four capture modes |
| **D** docs | New `web/docs/operations/run-parameters.md` (operator view), update `docker/compose.md#two-env-files` (the `.env` value is now the default), `.env.example` comments, CLAUDE.md architecture bullet | — |

**Rollout on prod** (this host; you run the recreates):

1. Apply the `session.parameters` migration on the NAS Postgres.
2. Rebuild and recreate stack-controller with the new `stacks.yml`.
3. Rebuild and recreate fastapi-app (new volume), then web.
4. **Verify on a Pi**, with no override set: start monitoring and confirm
   nothing changed. Set `IMU_SAMPLE_HZ=50` while monitoring and check that the
   IMUs restart and `/devices` `rate` reads ~50 msg/s. This also covers the
   `SESSION_ALREADY_ACTIVE` caveat from §1. Start a test session, confirm the
   panel locks and that `session.parameters` holds 50. Stop it, reset to
   default, run again.
5. Commit after prod passes.

---

## 8. Decisions needed

1. **Editable during MONITOR, with an immediate redeploy?** Recommended: yes,
   because it lets you tune and watch the result. The alternative is IDLE-only,
   which is simpler but means stopping and restarting monitoring to see a
   change.
2. **v1 parameter list.** Recommended: the four in §3. Add or drop any?
3. **`IMU_SAMPLE_HZ` upper bound.** Proposed: 200 until a load test (6 IMUs ×
   rate into the NAS Postgres, plus checking what the IMU hardware actually
   sustains). What rate do you expect to need?
4. **Do values stay set between runs, or reset to defaults after each
   session?** Recommended: they stay set (the confirm dialog flags anything
   non-default). Reset-after-each-session is safer against leftovers but means
   re-entering values for repeated runs.
