# Keep the edge stacks running between sessions

Branch: `dev/keep-edge-running` (off `dev/camera-edge-save-flags`). Revert = drop the branch.

## Why

Back-to-back sessions redeploy the edge stack every time. No image pulls happen
(`--resolve-image never`), but each cycle pays:

- start: 3-11 s until "Edge ready" (RPICAM4 is always last, 8-11 s);
- stop: `docker stack rm` + up to `REMOVE_WAIT_S` (30 s) teardown wait; RPICAM4
  hit the 30 s limit in sessions 539, 546, 547, 548 (2026-11-12).

## Decisions (user, 2026-11-13)

1. A **toggle** run parameter, `KEEP_EDGE_RUNNING` (AMS-side, default off,
   root `.env` default).
2. Stacks stay up **only when the PLC's `Db_Stop` ended the session**. A
   manual Stop tears down as before: the edge agents may still be mid-run
   (they stop on `Db_Stop` or their max-run timeout), and a session started in
   that window would record the old run's tail.

## Why the edge agents allow it

`imu_edge/agent.py` (IMU repo, `plc_update`): after `Db_Stop` it stops sending
and waits for the next `Data_Start`. `camera_edge` does the same with a new
`run_id` per run. So the agents are armed for the next run without a restart.

## Design

- `_stop_session(reason, keep_edge=False)`; `stop_session_from_plc()` passes
  `keep_edge=KEEP_EDGE_RUNNING`. With it: close the gate (STOPPING), skip
  `remove_managed_stacks()`, drain, end the session, then go to **MONITOR**
  with the recorded selection and `edge_standby = True` (instead of IDLE).
  The DB-down path and the error path go to the same mode.
- The next Start already skips the redeploy: from MONITOR, same selection,
  `deployed_env == stack_env(RECORD)` (`_start_session`). The
  "start the robot after Edge ready" hint is only sent when it redeployed.
- `edge_standby` is set through `set_capture(..., standby=)` (any other change
  clears it) and is reported as `standby` in `GET /capture`.
- `PUT /parameters` in standby redeploys with the **record** env (not the
  monitor one), so the stacks stay armed for the next session.
- Stop monitoring (`/listen/stop`) takes the stacks down as before.
- A Stop click just after a PLC stop still gets `already_stopped` (the check
  accepts MONITOR as well as IDLE).
- Dashboard: badge "Edge standby", readiness line says the edge is waiting for
  the next PLC `Data_Start`, and the monitor button reads "Take edge down".

Not handled: a fastapi-app restart in standby comes back IDLE with the stacks
still up; the next start redeploys in place (as today).

## Steps

1. Plan (this file).
2. Backend: run parameter, stop/standby logic, `/capture` field, tests.
3. Dashboard.
4. Docs (`operations/run-parameters.md`, `operations/plc-auto-stop.md`,
   `operations/running-a-test.md`), `.env.example`, CLAUDE.md.
5. Build, recreate fastapi-app + web (user), test two PLC runs back to back.
