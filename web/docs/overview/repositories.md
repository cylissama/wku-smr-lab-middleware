# Github Repos

All repositories that make up the system.

## GitHub

### [Active Middleware Services (AMS)](https://github.com/cylissama/wku-smr-lab-middleware)

This repository: every service on the AMS host and their Docker setup.

- `fastapi-app` (FastAPI backend: ingestion, sessions, backups, WebSockets)
- `tcp` (robot TCP server)
- `web` (dashboard and this documentation site)
- `stack-controller` (Swarm deploy agent, watchdog, logs)
- MQTT broker, NTP and pgAdmin configuration
- The edge Swarm stack file, `deploy/swarm-edge-nodes.yml`

Active work happens on `dev/*` branches and is merged into `main` by pull request.

### [IMU Edge Node](https://github.com/cylissama/wku-smr-lab-imu-edge-node)

The code on each IMU Raspberry Pi, a revision of the original IMU node by Masion and Cing:

- `imu_host`, the Pi-local hardware service
- `imu_edge`, the container that publishes over MQTT and handles the PLC trigger

The `plc_update` branch has the PLC tag logic (`imu_edge/plc_signals.py`). See [IMU nodes](/hardware/imu).

### [Camera Edge Node](https://github.com/UmarKhattab09/camera_sensor_fusion)

Camera sensor-fusion code: ArUco marker pose detection, published over MQTT. See [Camera nodes](/hardware/camera).

::: info Placeholder
TODO: which branch the camera Pis run, and how the `camera-edge:latest` image is built on them.
:::

### Older repositories

- [Data Broker Middleware (original)](https://github.com/Mseavers1/CS560-Smart-Manufacturing-Data): the first version of the middleware.
- [Previous IMU Node](https://github.com/mcbuckle/smart-mfg-imu): the original IMU node implementation.

## Docker Hub

[Cy's Docker Hub account](https://hub.docker.com/repositories/cylissama) has published images (`smr-robot-tcp-communication`, `smr-frontend-webui`, `smr-backend-fastapi`, `imu_node`).

::: info Placeholder
TODO: confirm whether these images are still published and used. Today the AMS images are built on the AMS host (`docker compose build`), and the edge images (`smart-mfg-imu:latest`, `camera-edge:latest`) exist locally on each Pi (deployed with `--resolve-image never`).
:::
