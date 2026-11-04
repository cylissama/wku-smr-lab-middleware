# Simulated PLC for monitoring

Oct 28, 2026

## Goal

A Raspberry Pi will act as a stand-in PLC: it serves `Data_Start`, `IMU_Tare`
and `Db_Stop` like the cell's L32E. The dashboard gets a **Simulated PLC IP**
field so Start Monitoring can run against it:

| Simulated PLC IP | Start Monitoring |
| --- | --- |
| empty or `0` | As today: the edge streams right away (`IMU_PLC_TRIGGER=false`) |
| a Pi's IP | IMUs and cameras wait for that Pi's `Data_Start`, tare on `IMU_Tare`, stop on `Db_Stop`, then wait for the next `Data_Start` |
| `192.168.1.103` (the real PLC) | Refused |

## User decisions (2026-10-28)

- **Monitoring only.** Recording sessions keep using the real PLC from the
  `.env` files (IMU/camera `*_PLC_PATH` and fastapi-app's `PLC_PATH` Db_Stop
  auto stop), whatever the field says.
- **IMUs and cameras** both follow the field (`IMU_PLC_PATH`, `CAMERA_PLC_PATH`).
- **In the Run Parameters panel**, as a new "PLC" group.

## Design

- `fast_server/run_params.py`: new parameter `MONITOR_PLC_IP`, type `ip`,
  `monitor_only`. `parse()` takes an IPv4 address; `""`, `0` and `0.0.0.0`
  mean none (stored as `""`). Default `""`.
- `stack_env(MONITOR)` with an IP set adds `IMU_PLC_TRIGGER=true`,
  `IMU_PLC_PATH`, `CAMERA_PLC_TRIGGER=true`, `CAMERA_PLC_PATH`. With none set
  it's unchanged. `stack_env(RECORD)` never sends PLC paths, so Monitor ->
  Record redeploys back onto the `.env` PLC (it already redeploys for
  `IMU_PLC_TRIGGER`).
- `stack_controller/stacks.yml`: add `IMU_PLC_PATH`, `CAMERA_PLC_TRIGGER`,
  `CAMERA_PLC_PATH` to the edge stack's `env_overrides`.
- Real PLC guard: `REAL_PLC_IP` (default: the host part of `PLC_PATH`, so
  `192.168.1.103`). `PUT /parameters` refuses it as the simulated IP, and
  `/listen/start` refuses to start if it's set anyway (e.g. a saved file, or
  `REAL_PLC_IP` changed).
- Monitor-only parameters are left out of `session.parameters` and the Start
  Session confirmation list, since a session doesn't use them.
- `PUT /parameters` while monitoring redeploys as for any edge parameter, so
  changing the IP takes effect live.
- Dashboard: `ParamRail` gets a text input for `ip` params, "None" when empty.

## Steps

1. Backend: run_params + main.py + stacks.yml + tests.
2. Dashboard: ParamRail input, confirmation list.
3. Docs: run-parameters.md, plc-auto-stop.md, CLAUDE.md, `.env.example`.
4. Deploy (fastapi-app, web; stack-controller re-reads stacks.yml per
   request) and check on prod with the simulated Pi.

## Caveat

The Pis only wait for the PLC if their `smart-mfg-imu` image has the
`plc_update` change (on 2026-10-13 it didn't). Without it, monitoring with a
simulated IP just streams right away. The camera image's
`CAMERA_PLC_TRIGGER`/`CAMERA_PLC_PATH` handling hasn't been checked here.
