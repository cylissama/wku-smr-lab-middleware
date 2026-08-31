# Topology

The lab network spans two subnets — a `192.168.1.0/24` device/lab subnet and a `192.168.2.0/24` subnet the broker's own `HOST_IP` sits on — connecting the Data Broker Mini PC, the Synology NAS, edge device Raspberry Pis, and lab workstations.

## Known hosts

| Host | Address | Role |
| --- | --- | --- |
| Data Broker Mini PC | `192.168.1.76` | Runs the Compose broker stack; Swarm manager (`:2377`) |
| Synology NAS | `192.168.1.104` | PostgreSQL DB host; NFS backups/logs; DB GUI on `:8080` |
| Image analysis machine | `192.168.1.113` | Camera sensor-fusion / pi-stream processing |
| IMU node 83 | `192.168.1.83` | `imu_83_joint1` Swarm service |
| IMU node 84 | `192.168.1.84` | `imu_84_joint2` Swarm service |
| IMU node 85 | `192.168.1.85` | `imu_85_joint3` Swarm service |
| IMU node 86 | `192.168.1.86` | Reserved / not yet active (`imu_86_joint4`) |
| Camera node | `192.168.1.80` | `camera_sensor_fusion` container |
| Camera node | `192.168.1.92` | `camera_sensor_fusion/middleware` container |
| Broker host-side IP (`HOST_IP`) | `192.168.2.100` | Used for CORS origins and service URLs baked into the frontend build |
| Robot camera feed | `192.168.2.36` | `ROBOT_CAMERA_URL` viewer |

::: warning
IPs and hostnames above reflect the lab's current `.env`/SOP configuration and will drift as devices are re-provisioned — treat `project/.env` and `project/SOP/*` as the source of truth, this page as a snapshot.
:::

## Ports

| Port | Service | Notes |
| --- | --- | --- |
| `1883` | MQTT (`MQTT_PORT`) | Device messaging (IMU, camera) |
| `9001` | MQTT over WebSocket | Fixed, not `.env`-driven |
| `8000` | FastAPI (`FASTAPI_PORT`) | REST + WebSocket API |
| `5001` | Robot TCP (`ROBOT_TCP_PORT`) | Raw CSV-over-TCP from the robot |
| `80` | Web dashboard (`WEB_PORT`) | nginx: SPA, `/api/` proxy, `/docs/` |
| `123/udp` | NTP (`NTP_PORT`) | Shared time source |
| `5433` → `5432` | PostgreSQL (`DB_PORT` / `DB_PORTS`) | On the NAS |
| `8080` | DB GUI (`DB_GUI_URL`) | pgAdmin-style browser on the NAS |
| `2377` | Docker Swarm manager | IMU node join/management |
| `9000` | Portainer (`VITE_PORTAINER_URL`) | Container management UI |

## Data plane vs. control plane

- **Data plane**: edge devices → MQTT (`1883`) or TCP (`5001`) → `fastapi-app` / `tcp` → PostgreSQL (`5433`/`5432` on the NAS). This is the path that must stay reachable during a test session.
- **Control plane**: the dashboard (`80`) talks to the FastAPI REST/WebSocket API (`8000`, proxied through nginx at `/api/`) to start/stop sessions and manage backups. The Swarm manager (`2377`) is a separate control plane for deploying/restarting IMU edge containers and is unrelated to live telemetry flow.

## Operator access pattern

A typical test session (see the dashboard's "How to Run a Test" SOP) is orchestrated from a lab workstation that SSHes out to each machine in turn: into the Data Broker Mini PC to bring up the broker stack, into the image analysis machine to start camera processing, and into each IMU/camera Pi to start its device container — all over the `192.168.1.0/24` subnet, with the robot started manually by an operator standing at the hardware.
