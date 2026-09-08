# The hardware behind the project

The system spans lab machines, edge Raspberry Pis, and a robot arm. Everything below is tied together over the lab network described in [Network Topology](/network/topology).

## Core infrastructure

| Machine | Role |
| --- | --- |
| **Data Broker Mini PC** | Always-on host for the `docker-compose.yml` stack (MQTT broker, FastAPI server, TCP server, web dashboard, NTP). |
| **Synology NAS** | Hosts the PostgreSQL database and provides NFS volumes for DB backups and logs. |
| **Alienware dev PC** | Used to SSH into the broker and orchestrate test sessions from the upstairs lab. |
| **Image analysis machine** | Runs the camera sensor-fusion / pi-stream container that processes camera feeds. |

## IMU nodes

Each IMU joint is a Raspberry Pi running a BNO08x 9-DoF IMU over I2C, split into two cooperating processes:

1. **`imu_host`** — a Pi-local (non-containerized) hardware service that talks to the IMU directly over I2C and exposes a Unix socket at `/run/imu-hw/imu.sock`. It's installed as a `systemd` service so it survives reboots.
2. **`imu_edge`** — a containerized service, deployed via Docker Swarm, that connects to `imu_host` through that socket and publishes readings over MQTT (`imu/<device_id>`).

This host-service-plus-container split exists specifically because Docker Swarm on these nodes cannot grant a task sandbox usable device-cgroup access to `i2c-1` — see [Docker \> Swarm](/docker/swarm) for the full story. The `imu_host` process, running directly on the Pi, is what actually has permission to open the I2C bus.

Each IMU Pi is joined to the Swarm as a worker and labeled with its own device ID (`device_id=<node-ip>`) so the matching `imu_edge` Swarm service is always scheduled onto the correct physical node.

## Camera nodes

Raspberry Pis fitted with cameras run the camera sensor-fusion pipeline (ArUco/marker pose detection) and publish frame + marker pose data to MQTT under `camera/<device_id>`. A separate image-analysis machine consumes and processes the camera stream.

## The robot

A robot arm streams joint angles and TCP (tool center point) pose as CSV lines over a raw TCP connection to the `tcp_server`, rather than over MQTT. Unlike the other devices, the robot is started manually by a human operator in the lab — it is not remotely orchestrated.

## Time synchronization hardware/software

All containers share time via an NTP container (`cturra/ntp`) syncing from Google's public NTP pool. On hosts where this matters, the system's own `chrony` / `systemd-timesyncd` are stopped, disabled, and masked so the container's time source is authoritative and telemetry timestamps stay comparable across devices.

## Related repositories

- [Data Broker Middleware](https://github.com/Mseavers1/CS560-Smart-Manufacturing-Data) — this repo; also holds the Swarm config files and setup SOPs.
- [Revised IMU Node](https://github.com/cylissama/imu_node_smr) — the current `imu_host` / `imu_edge` code, restructured for Swarm.
- [Previous IMU Node](https://github.com/mcbuckle/smart-mfg-imu) — the original IMU node implementation.
- [Camera Node](https://github.com/mcbuckle/smart-mfg-imu) — camera sensor-fusion node code.
- [Docker Hub](https://hub.docker.com/repositories/cylissama) — published images: `smr-robot-tcp-communication`, `smr-frontend-webui`, `smr-backend-fastapi`, `imu_node`.
