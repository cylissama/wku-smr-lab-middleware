# API reference (fastapi-app)

`fastapi-app` serves everything the dashboard uses. From a browser on the lab network it's reached through nginx at `http://192.168.2.100/api/…`, or directly at `http://192.168.2.100:8000/…` (`FASTAPI_PORT`). There's no authentication. The code is in `fast_server/main.py`.

Most routes answer `200` with `{"success": true, …}` or `{"success": false, "error": "…"}`. Routes that need the database answer **503** `{"success": false, "error": "Database unavailable: …"}` while it's down (see [Health & logs](/docker/health-and-logs)).

## Sessions and capture

| Method & path | What it does | Needs DB |
| --- | --- | --- |
| `GET /capture` | Current [capture mode](/overview/capture-modes), session id and device selection | no |
| `POST /listen/start` | Start monitor mode. Body `{"devices": [...]}` or `null` for all. Only from idle. | no |
| `POST /listen/stop` | Stop monitor mode and remove the edge stack | no |
| `GET /session/start/{label}?session_label=…&is_test_session=…&devices=…` | Start a recording session. `devices` is repeated per key; leave it out for all devices. | yes |
| `GET /session/stop` | Stop the session: drain, end, back up. Works with the DB down. | no |
| `GET /session` | The open session, if any | yes |
| `GET /sessions` | All sessions (`id`, `label`) | yes |
| `GET /session/labels` | Session types for the dropdown | yes |

## Devices and run parameters

| Method & path | What it does | Needs DB |
| --- | --- | --- |
| `GET /devices` | Device catalog with Swarm state and live activity ([details](/docker/stack-controller#get-devices-fastapi-app)) | no |
| `GET /parameters` | [Run parameters](/operations/run-parameters): definition, default, value, `editable` | no |
| `PUT /parameters` | Body `{"values": {"IMU_SAMPLE_HZ": 200, "IMU_PLC_MAX_RUN_S": null}}`; `null` resets to the default. Refused while recording or stopping. | no |

## Data

| Method & path | What it does | Needs DB |
| --- | --- | --- |
| `GET /imu/{label}` | All IMU rows for a session label | yes |
| `GET /camera/{label}` | All camera rows for a session label | yes |
| `GET /robot/{label}` | All robot rows for a session label, plus a `twins` array for the digital twin | yes |

These return a whole session at once. For analysis, query the database directly ([Accessing the database](/data/accessing-database)).

## Backups

| Method & path | What it does | Needs DB |
| --- | --- | --- |
| `GET /backup` | Take a `pg_dump` backup now | yes |
| `GET /backup/list` | Backup files on the NAS | no |
| `POST /backup/restore/{filename}` | **Replace the whole database** with a backup | yes |

## Live feeds and health

| Method & path | What it does |
| --- | --- |
| `WS /ws/camera`, `/ws/imu`, `/ws/robot`, `/ws/misc` | Live message feeds for the dashboard's message boxes |
| `POST /send/{channel}` | Post a message to one of those feeds. Body `{"text": "…", "type": "normal|info|error"}`; used by `tcp`. |
| `GET /health` | Dependency report; always `200` while the process is alive ([details](/docker/health-and-logs#get-health)) |

## Other services' APIs

- **stack-controller** (internal only, token-protected, except `/containers` and `/logs`): see [Stack controller](/docker/stack-controller#endpoints) and [Health & logs](/docker/health-and-logs#reading-logs).
- **tcp** status server (internal port 8090): see [TCP Server](/docker/tcp-server#how-the-container-listens).
