# Run parameters

The **Run Parameters** panel on the dashboard sets per-run values for the edge devices without editing a `.env` file. On wide screens (1840px or more) it's in the right-hand gutter; on narrower screens it's under the Devices box.

| Parameter | Key | Range | Default from |
| --- | --- | --- | --- |
| IMU sample rate | `IMU_SAMPLE_HZ` | 1–200 Hz | `deploy/.env` |
| Wait for PLC start | `IMU_PLC_TRIGGER_ON_RECORD` | on/off | repo-root `.env` |
| Max PLC run | `IMU_PLC_MAX_RUN_S` | 30–3600 s | `deploy/.env` |
| Simulated PLC IP | `MONITOR_PLC_IP` | IPv4, or empty/`0` for none | none |

## How it behaves

- **The `.env` value is the default.** The panel only stores what you change. **Reset** on a tile goes back to the `.env` value.
- **Values stay set between runs** until someone changes or resets them. Before a session starts, the Start Session confirmation lists every changed parameter.
- **Edit, then Apply.** Nothing is sent until you click Apply. Out-of-range values are refused and the tile says why.
- **Idle:** the values apply on the next Start Monitoring or Start Session.
- **Monitoring:** Apply redeploys the edge stack right away, which restarts the devices whose settings changed. Watch the IMU rate on the Devices box to check the change. *Wait for PLC start* only affects recording, so changing it doesn't restart anything.
- **Recording / stopping:** the panel is locked and shows the values the session is running with.
- **Every session records its values** in `session.parameters` (JSONB), defaults included:

```sql
SELECT id, label, parameters->>'IMU_SAMPLE_HZ' AS imu_hz FROM session ORDER BY id DESC;
```

*Wait for PLC start* (PLC group) sets `IMU_PLC_TRIGGER` and `CAMERA_PLC_TRIGGER` for recording sessions only, so it covers the IMUs and the cameras. Monitoring streams without waiting. See [PLC auto stop](/operations/plc-auto-stop#imu-plc-trigger-monitor-vs-session).

*Simulated PLC IP* is the other way round: it only affects monitoring, which then waits for that PLC's `Data_Start`. The real PLC (`192.168.1.103`) is refused. Sessions don't use it, so it's left out of `session.parameters` and the Start Session confirmation. See [Monitoring with a simulated PLC](/operations/plc-auto-stop#monitoring-with-a-simulated-plc).

## Where things live

| What | Where |
| --- | --- |
| Definitions (label, type, range) | `fast_server/run_params.py`. Values are checked here. |
| Changed values | `/state/run_parameters.json` in fastapi-app (`fastapi_state` volume, local) |
| Allowlist for edge deploys | `env_overrides` in `stack_controller/stacks.yml` |

A manual `docker stack deploy` from the shell uses only `deploy/.env`. It doesn't see values set in the panel.

## Adding a parameter

1. Use it in `deploy/swarm-edge-nodes.yml` (`FOO: "${FOO}"`) and give it a default in `deploy/.env` and `deploy/.env.example`.
2. Add it to `env_overrides` in `stack_controller/stacks.yml`. stack-controller reads that file on every request, so this needs no restart.
3. Add its definition to `PARAMS` in `fast_server/run_params.py`, then rebuild fastapi-app. `tests/run_params_test.py` fails if step 2 was missed.
