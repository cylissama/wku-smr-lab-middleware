# What is this project?

The **Smart Manufacturing Research Lab** was created to perform research in smart manducating environments with the goal of creating a fault tolerant and scalable. The end goal of which is to reduce downtime and calculate when to do preventative maintained on industrial robotic units.

This project includes a data platform for collecting, monitoring, and storing telemetry (data) from distributed edge devices — IMUs, cameras, and a robot arm — in the WKU Smart Manufacturing Research (SMR) Lab. 

The system centers on a containerized **Active Middleware Services** or **AMS** alongside its edge nodes. The AMS receives data from the edge devices over MQTT and TCP, stores it in a session-scoped PostgreSQL database, and exposes a live web dashboard for monitoring sessions, device activity, and backups.

## What it does

- **Real-time data ingestion** — IMU and camera devices publish over MQTT; the robot streams over a raw TCP connection using socket programming.
- **Session-based data collection** — every reading is tied to an operator-started "session," so a single test run can be queried, exported, and reasoned about as one unit.
- **Live dashboard monitoring** — a React web UI shows device connection status, session state, and live log/message streams over WebSockets.
- **Database backup and restore** — every session automatically triggers a `pg_dump` backup, and backups can be listed and restored from the dashboard.
- **Time-synchronized data** — an NTP container keeps every service and edge device on the same clock so telemetry across devices can be correlated.
- **Modular deployment** — the AMS stack runs under Docker Compose on a single always-on host, while IMU edge nodes run under Docker Swarm across multiple Raspberry Pis.

## AMS high-level components/containers

| Component | Role |
| --- | --- |
| MQTT broker (Eclipse Mosquitto) | Receives IMU and camera device messages |
| FastAPI server | Ingestion, session control, backups, WebSocket broadcast |
| TCP server | Robot telemetry ingestion (CSV over raw TCP) |
| PostgreSQL | Sessioned telemetry storage, hosted on a Synology NAS |
| React + Vite dashboard | Live monitoring UI, session control, document/SOP library |
| NTP service | Shared time source for all containers and edge devices |

See [How is this structured?](/overview/structure) for the repository layout and how these pieces fit together, or jump straight to [Hardware](/hardware/), [Data](/data/database-uses), [Docker](/docker/compose), or [Network](/network/topology).
