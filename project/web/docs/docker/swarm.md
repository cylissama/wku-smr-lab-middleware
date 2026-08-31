# Swarm

`project/swarm.yml` deploys the **IMU edge nodes** — separately from the `docker-compose.yml` broker stack described in [Compose](/docker/compose). Where Compose runs on one host, this stack runs one service per IMU, each pinned to a specific Raspberry Pi across a Docker Swarm cluster.

## Why Swarm, and why it's split from Compose

Each IMU Pi needs its own container instance talking to its own physical sensor. Swarm's placement constraints let one stack definition describe "run this service on that specific Pi" for as many IMUs as the lab has, instead of hand-managing `docker compose up` on each Pi individually.

## Services

Each active IMU (`imu_83_joint1`, `imu_84_joint2`, `imu_85_joint3`, with `imu_86_joint4` present but commented out/reserved) is defined almost identically:

- **Image**: `${IMU_EDGE_IMAGE}` (e.g. `cylissama/imu_node:v2`), running `python3 -m imu_edge`.
- **Environment**: per-device ID, session ID, MQTT topic, CSV output path, and health-check path — all sourced from `.env` (`IMU_83_DEVICE_ID`, `IMU_83_SESSION_ID`, `IMU_83_MQTT_TOPIC`, …).
- **Volumes**: the IMU data directory and `/run/imu-hw` (the Unix socket directory shared with the Pi-local `imu_host` service — see [Hardware](/hardware/)).
- **Healthcheck**: `python3 -m imu_edge healthcheck`, every 30s.
- **Placement constraint**: `node.labels.device_id == <that IMU's IP>` — this is what pins the service to the correct physical Pi.
- **Restart policy**: `condition: on-failure`.

## Bringing a node online

Full step-by-step is in `project/SOP/IMU_SETUP.md`; the shape of it:

1. Join the Pi to the Swarm as a worker: `docker swarm join --token <worker-token> <manager-ip>:2377`.
2. From the manager, label the node so placement constraints can match it: `docker node update --label-add device_id=<pi-ip> <node-name>`.
3. On the Pi, install and start the `imu-hw` systemd service (the `imu_host` process — see [Hardware](/hardware/)) and confirm `/v1/readyz` reports healthy over the Unix socket.
4. From the manager, deploy or refresh the stack:

   ```bash
   set -a; source ./.env; set +a
   docker stack deploy --resolve-image never -c swarm.yml imu
   ```

5. Verify scheduling and health:

   ```bash
   docker service ps imu_imu_83_joint1
   docker service logs -f imu_imu_83_joint1
   ```

To tear the IMU stack down: `docker stack rm imu`.

## Known limitation: I2C device access under Swarm (resolved)

Early on, IMU containers deployed under Swarm could see `/dev/i2c-1` but got `EPERM` trying to open it — a device-cgroup permission issue, not a missing file or bad code. Swarm on the Docker version in use doesn't expose `--device` or accept `device_cgroup_rules` in a stack spec, so there was no way to authorize I2C access directly from `swarm.yml`.

The fix was architectural, not a Swarm flag: **move I2C access out of the Swarm-managed container entirely.** The `imu_host` process now runs directly on the Pi (via systemd, outside Docker), where it has real permission to open `i2c-1`, and exposes a Unix socket. The Swarm-managed `imu_edge` container only ever talks to that socket — it never touches the I2C bus itself. This is why the [Hardware](/hardware/) page describes IMU nodes as two cooperating processes instead of one container.

## Troubleshooting

| Symptom | Likely cause |
| --- | --- |
| `This node is not a swarm worker` | Node fell out of the swarm — rejoin with a fresh worker token. |
| `no suitable node (scheduling constraints not satisfied)` | Node label doesn't match `node.labels.device_id` in `swarm.yml` — compare the node's labels (`docker node inspect <node> --format`, Go-template `.Spec.Labels`) against the constraint. |
| `ModuleNotFoundError: No module named 'lgpio'` | Pi-side `imu_host` dependencies missing — reinstall `requirements-host.txt`. |
| `PermissionError: /run/imu-hw` | Run via systemd (creates the runtime dir automatically) or `mkdir`/`chown` it manually for a manual test run. |
| `Could not establish MQTT connection` | Check `MQTT_BROKER_IP`/`MQTT_BROKER_PORT` and reachability from the container. |
