# Keep edge running → automatic next session + 10 ms Pi PLC polling

## Context
With **Keep edge running** on, a PLC `Db_Stop` ends the session and leaves the edge
stacks up, but capture drops to `MONITOR` ("Edge standby"). Nothing opens a new session, so
the next robot run either isn't stored or waits for someone to click Start (prod logs
2026-11-19: 563 → 564 → 565 each started by hand; a `Db_Stop` at 19:45:07 was ignored
"capture is monitor"). What we want: on `Db_Stop`, end the current session, **immediately open
a new session** with the same settings, and keep the edge containers running. The next
`Data_Start` run then lands under the new session id.

Separately, every Pi polls the PLC every 50 ms (`IMU_PLC_POLL_S` / `CAMERA_PLC_POLL_S`
default `0.05`). The request is 10 ms.

## Change 1: roll over to a new session on a PLC stop (`fast_server/main.py`)
- Add a global `session_meta: tuple[str, bool] | None` holding the current session's
  `(session_label, is_test_session)`. Set it in `_start_session` after `create_session`
  succeeds. Clear it on a failed start rollback.
- In `stop_session_from_plc()`, when `keep_edge_running()`:
  1. `result = await _stop_session(reason=..., keep_edge=True)` (no change; still under `session_lock`).
  2. If `result["success"]` and not `result.get("degraded")` and `session_meta` is set and
     capture is the standby MONITOR: build a new label the same way the dashboard does
     (`DataDashboard.jsx:414`: `<slug>_<ISO ms Z>`). Take the old label's prefix before the
     last `_` and add `datetime.now(UTC).isoformat(timespec="milliseconds")` + `Z`.
  3. `await _start_session(new_label, session_label, is_test_session, sorted(devices) or None)`.
     It already skips the redeploy from standby when the selection and `deployed_env ==
     stack_env(RECORD)` match (`main.py:1167`), so the containers aren't touched. It also
     rotates the loggers, stores `session.parameters` and opens the RECORD gate.
  4. Log/broadcast "Session N started automatically after PLC stop (edge kept running)".
     If the auto-start fails, `_start_session` already falls back to MONITOR standby
     (`was_standby`), so the user can still click Start.
  5. Return the stop result with the new `session_id` added.
- When `session_meta` is missing (fastapi restarted mid-session, so the session was restored from
  the DB), skip the rollover and keep today's standby behaviour, logged as a warning. No new DB query.
- Manual Stop, and Keep edge running off, stay as they are (full teardown → IDLE).
- Update the comments on `_stop_session`/`stop_session_from_plc` and the `KEEP_EDGE_RUNNING`
  help text in `fast_server/run_params.py`: "…a new session starts right away with the same
  type/devices, and the edge stays up…".
- Dashboard: no code change needed. It polls `/capture` and will show RECORD again. Check
  that the session-id display picks up the new id from `/capture` and not only from the Start
  response. If it doesn't, read `capture.session_id` in `DataDashboard.jsx` around line 248.

## Change 2: Pi PLC polling 50 ms → 10 ms (`deploy/swarm-edge-nodes.yml`)
- Change the default from `0.05` to `0.01` in every `IMU_PLC_POLL_S` entry (6 IMU services) and every
  `CAMERA_PLC_POLL_S` entry (4 camera services). Neither is set in `deploy/.env`, so the yml default
  is what runs. It takes effect on the next edge deploy.
- The AMS's own `PLC_POLL_S` (fastapi `Db_Stop` watcher, root `.env`) stays at 0.05 unless asked.
- Risk to flag: 10 Pis at 100 Hz is about 1000 CIP reads/s on the L32E (5× today). Watch the PLC's
  connection or comm load on the first run. If needed, back off with `IMU_PLC_POLL_S`/`CAMERA_PLC_POLL_S`
  in `deploy/.env`, with no code change.

## Tests (`tests/plc_listener_test.py`)
- Update `test_keep_edge_running_leaves_the_stacks_up_after_a_plc_stop`: after the pulse,
  capture is RECORD with a **new** session_id, `create_session` was called with the same
  session_label/is_test/devices, and `remove_managed_stacks`/`deploy_managed_stacks` were **not** called.
- New: auto-start failure leaves MONITOR standby. Without `session_meta`, it stays in standby.
- Leave the manual-stop-teardown and DB-down tests unchanged. When the DB is down, there's no
  rollover and it stays in standby.
- Run: `python -m unittest discover -s tests -t . -p '*_test.py'` (16 known pre-existing failures).

## Docs
`web/docs/operations/plc-auto-stop.md` and `run-parameters.md` (Keep edge running section):
describe the auto next session. Change the poll defaults wherever docs quote `IMU/CAMERA_PLC_POLL_S`.

## Verification
1. Unit tests above.
2. Commit on a new branch `dev/keep-edge-rollover` (per commit-each-step). Build the fastapi-app
   image with a `:pre-rollover` rollback tag. The user recreates fastapi-app.
3. On prod with Keep edge running on: start a Full System session. The robot runs and `Db_Stop`
   fires. Logs show "Session N stopped (robot finished…)" and then "Session N+1 started
   automatically". There's no stack redeploy (edge tasks keep their uptime) and the dashboard
   shows Recording. The second robot run's rows have `session_id = N+1`
   (`SELECT session_id, count(*) FROM imu_data WHERE session_id IN (N, N+1) GROUP BY 1`).
4. After an edge deploy, `docker service inspect edge_imu-106 --format '{{json .Spec.TaskTemplate.ContainerSpec.Env}}'`
   shows `IMU_PLC_POLL_S=0.01`. Same check for a camera service.
