# PLC auto stop

When the robot finishes its move, the cell's PLC pulses the tag `Db_Stop` (a brief 0 → 1 → 0). With PLC auto stop on, `fastapi-app` watches that tag and stops the recording session exactly as the **Stop Session** button does: it closes the capture gate, removes the edge stacks, drains the buffers, ends the session and takes a backup.

| | |
| --- | --- |
| PLC | `L32E` (1769-L32E), `192.168.1.103`, EtherNet/IP port 44818 |
| Tag | `Db_Stop` (DINT; anything non-zero counts as ON) |
| Read by | `fastapi-app`, polling every 50 ms with [pycomm3](https://github.com/ottowayi/pycomm3) (`fast_server/plc_listener.py`) |
| Same tag logic | the IMU edge nodes' `imu_edge/plc_signals.py` (`plc_update` branch) |

## What a pulse does

| Capture mode when the pulse arrives | Result |
| --- | --- |
| **Recording** | Session stops. The Messages box shows "Robot finished (PLC Db_Stop): stopping session N", and the log line reads "Session N stopped (robot finished, PLC Db_Stop)". |
| **Monitoring** | Ignored. Monitoring keeps running. |
| **Idle** | Ignored. |
| A session start or stop is already in progress | Ignored. A pulse during a start belongs to the robot's previous run. |

Only a *change* from 0 to 1 counts. If `Db_Stop` is already 1 when `fastapi-app` starts, nothing happens until it drops to 0 and rises again.

If someone clicks **Stop Session** right after the PLC stopped the session (the dashboard can lag up to 5 s), the click is answered with "Session N was already stopped" instead of an error.

## IMU PLC trigger: monitor vs. session

The IMU edge nodes read the same PLC. With `IMU_PLC_TRIGGER=true`, an IMU waits for a `Data_Start` pulse before sending, tares on `IMU_Tare`, and stops sending on `Db_Stop`. `fastapi-app` sets that variable on every edge deploy:

| Mode | `IMU_PLC_TRIGGER` | IMUs |
| --- | --- | --- |
| **Monitoring** | `false` | stream immediately, so you can check the devices without the robot |
| **Recording** (session) | `true` | wait for the robot's `Data_Start` |

Going from monitoring to a session redeploys the edge stack. Only the IMU services restart, because nothing else changed; the cameras keep running. Start the robot only after the IMUs are back up: an IMU ignores a `Data_Start` that arrived before it started.

To record without the robot (IMUs streaming as soon as the session starts), set `IMU_PLC_TRIGGER_ON_RECORD=false` in the repo-root `.env` (the broker stack's, not `deploy/.env`) and recreate `fastapi-app`. Then starting a session from monitoring with the same devices doesn't redeploy anything.

How it gets there: stack-controller only lets a deploy request set the variables listed under `env_overrides` for the stack in `stack_controller/stacks.yml` (`IMU_PLC_TRIGGER` for `edge`). They are layered over `deploy/.env` for that deploy only, and anything else is refused with a 400. The `IMU_PLC_TRIGGER` line in `deploy/.env` only applies to a manual `docker stack deploy`. See [Two `.env` files](/docker/compose#two-env-files).

## Checking it

The dashboard's **System Health** box has a **PLC (robot done)** entry. It's also under `components.plc` in `GET /api/health`:

```json
"plc": {"status": "ok", "detail": {"path": "192.168.1.103", "tag": "Db_Stop", "value": 0, "pulses": 3, "fake": false}}
```

`pulses` is how many times `Db_Stop` has turned on since `fastapi-app` started.

| Health message | Meaning |
| --- | --- |
| `can't reach PLC at 192.168.1.103: ...` | No connection. Check the PLC is powered and on the network (`ping 192.168.1.103` from the AMS). |
| `no answer from PLC ... for Ns` | Connected, but reads have stalled. |
| `PLC tag problem: Db_Stop: Tag doesn't exist` | The PLC program doesn't have that tag (renamed, or a different program downloaded). |

While the PLC is unreachable, a pulse is missed. The session keeps recording until someone clicks **Stop Session**.

## Turning it on or off

It's controlled by the repo-root `.env` next to `docker-compose.yml` (not `deploy/.env`), then a recreate of `fastapi-app`:

```bash
PLC_AUTO_STOP=true         # false = button only, no PLC health entry
PLC_PATH=192.168.1.103
PLC_TAG_STOP=Db_Stop
PLC_POLL_S=0.05
```

```bash
docker compose up -d --no-deps fastapi-app
```

For testing without the robot, `PLC_FAKE=true` replays one fake `Db_Stop` pulse about 20 s after `fastapi-app` starts (`PLC_FAKE_SPEED` scales that time).
