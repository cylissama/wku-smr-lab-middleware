# The dashboard

The dashboard is at [http://192.168.2.100/](http://192.168.2.100/) on the lab network. It's a React app (`web/src/`), served by nginx in the `web` container, that talks to `fastapi-app` through `/api/`. This page is a tour of what's on it and where each part is explained in detail. For the step-by-step procedure, see [Running a test session](/operations/running-a-test).

```text
┌────────────┐ ┌───────────────────────────────────────────┐ ┌────────────┐
│ Field      │ │ Session bar: status · mode badge · last    │ │ Run        │
│ Devices    │ │ session · type · Start Monitoring ·        │ │ Parameters │
│            │ │ Start Session · Stop Session · Fake Data   │ │            │
│ (≥1840 px) │ │ links · System Health strip                │ │ (≥1840 px) │
│            │ ├───────────────────────────────────────────┤ │            │
│            │ │ Devices (selection)                        │ │            │
│            │ │ Camera · IMU · Robot · Misc message boxes  │ │            │
│            │ │ Backups                                    │ │            │
│            │ │ Container Health · Logs                    │ │            │
└────────────┘ └───────────────────────────────────────────┘ └────────────┘
```

On screens narrower than 1840 px, the Field Devices card is hidden and the Run Parameters card moves under the Devices box.

## Session bar

| Control | What it does |
| --- | --- |
| Session indicator, mode badge | Whether a session is open, and the [capture mode](/overview/capture-modes): Idle, Monitoring, Recording or Stopping |
| Most Recent Session | Id of the newest session in the database |
| Session type dropdown | The session's category (`session_label`); needs the database |
| **Start Monitoring / Stop Monitoring** | Runs the selected devices and shows live data without storing anything |
| **Start Session** | Click twice: the first click asks you to confirm and lists any changed run parameters |
| **Stop Session** | Stops recording, drains the buffers, ends the session and takes a backup |
| **Fake Data** | Ticked marks the session as a test (`is_test_session`) |
| Enclosure Safety Camera, pgAdmin, Portainer | Links set at build time (`VITE_ROBOT_CAMERA_URL`, `VITE_DB_GUI_URL`, `VITE_PORTAINER_URL`); a button is greyed out when its URL isn't set |

The **System Health** strip under the buttons shows whether the API can reach the database, MQTT broker, stack-controller, robot TCP server, log and backup folders, and (with PLC auto stop on) the PLC. When something is down, a card with the error and retry time opens under it. See [Health & logs](/docker/health-and-logs).

## Devices

Every IMU, camera and the robot, with a checkbox and a status. Only the ticked devices are started, shown and recorded. The selection is locked while monitoring or recording. The statuses and colors are explained in [Running a test session](/operations/running-a-test#devices). How the selection works is in [Stack controller & device selection](/docker/stack-controller).

## Field Devices (left)

A card with a graphic per device, colored the same way as the Devices box: grey offline, blue standby, green sending (with its message rate), red fault. Unselected devices are dimmed. It only shows status; selection happens in the Devices box.

## Run Parameters (right)

Per-run settings such as the IMU sample rate. You edit, then click Apply. The panel is locked while a session is recording. See [Run parameters](/operations/run-parameters).

## Message boxes

Four live feeds over WebSockets (`/ws/camera`, `/ws/imu`, `/ws/robot`, `/ws/misc`):

- **Camera / IMU / Robot**: insert summaries and errors, plus one cyan `[live]` line per device per second while monitoring or recording.
- **Misc**: session and system events, such as session started or stopped, deploy failures, health changes, PLC stops and parameter changes.

Any service can post to these with `POST /send/{channel}`; that's how the robot's `tcp` container reports.

## Backups

Lists the `pg_dump` files on the NAS. You can take a backup or restore one from here. **Restoring replaces the whole database.** See [Database uses](/data/database-uses#backup-and-restore).

## Container Health and Logs

These two boxes are served by `stack-controller` through nginx (`/api/system/containers`, `/api/system/logs`), so they keep working when `fastapi-app` is down. They show each container's Docker state, health checks and restarts, and recent logs from every container. The **Important** tab shows only what needs attention. See [Health & logs](/docker/health-and-logs) and [Troubleshooting](/operations/troubleshooting).
