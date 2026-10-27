# What is this project?

The **Smart Manufacturing Research Lab** was created to research smart manufacturing environments, with the goal of building a fault-tolerant and scalable system. The end goal is to reduce downtime and work out when to do preventive maintenance on industrial robots.

This project includes a data platform for collecting, monitoring, and storing telemetry (data) from distributed edge devices — IMUs, cameras, and a robot arm — in the WKU Smart Manufacturing Research (SMR) Lab. 

The system centers on a containerized **Active Middleware Services** or **AMS** alongside its edge nodes. The AMS receives data from the edge devices over MQTT and TCP, stores it in a session-scoped PostgreSQL database, and exposes a live web dashboard for monitoring sessions, device activity, and backups.

## What it does

- **Real-time data ingestion** — IMU and camera devices publish over MQTT; the robot streams over a raw TCP connection using socket programming.
- **Session-based data collection** — every stored reading is tied to an operator-started "session," so a single test run can be queried, exported, and reasoned about as one unit. Each session also records which devices and which [run parameters](/operations/run-parameters) it used.
- **Monitor before you record** — [monitor mode](/overview/capture-modes) runs the devices and shows live data without storing anything.
- **Device selection** — the dashboard starts only the IMUs and cameras you tick, through the `stack-controller` agent and Docker Swarm.
- **PLC auto stop** — when the robot finishes, the cell's PLC stops the session by itself ([PLC auto stop](/operations/plc-auto-stop)).
- **Live dashboard monitoring** — a React web UI shows device connection status, session state, and live log/message streams over WebSockets.
- **Database backup and restore** — every session automatically triggers a `pg_dump` backup, and backups can be listed and restored from the dashboard.
- **Time-synchronized data** — an NTP container keeps every service and edge device on the same clock so telemetry across devices can be correlated.
- **Self-healing** — containers start without waiting on the database or NAS, restart when they fail, and report their health and logs on the dashboard ([Health & logs](/docker/health-and-logs)).
- **Modular deployment** — the AMS stack runs under Docker Compose on a single always-on host, while the IMU and camera edge nodes run under Docker Swarm across multiple Raspberry Pis.

## AMS high-level components/containers

| Component | Role |
| --- | --- |
| MQTT broker (Eclipse Mosquitto) | Receives IMU and camera device messages |
| FastAPI server | Ingestion, session control, backups, WebSocket broadcast |
| TCP server | Robot telemetry ingestion (CSV over raw TCP) |
| PostgreSQL | Sessioned telemetry storage, hosted on a Synology NAS |
| React + Vite dashboard | Live monitoring UI, session control, document/SOP library ([tour](/overview/dashboard)) |
| stack-controller | Deploys/removes the edge Swarm stack for `fastapi-app`; container health, watchdog, logs |
| pgAdmin | Per-person database access for the lab |
| NTP service | Shared time source for all containers and edge devices |

See [How is this structured?](/overview/structure) for the repository layout and how these pieces fit together, or jump straight to [Hardware](/hardware/), [Data](/data/database-uses), [Docker](/docker/compose), or [Network](/network/topology).
