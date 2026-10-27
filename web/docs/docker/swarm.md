# Swarm

[Docker Swarm mode](https://docs.docker.com/engine/swarm/) runs the **edge devices**: one container per IMU and camera, each on its own Raspberry Pi. The always-on AMS services aren't in Swarm; they run under [Compose](/docker/compose).

## The cluster

The **AMS host** (`IIoT`, 192.168.2.100) is the Swarm **manager**. Every IMU and camera Pi is a **worker**. On the AMS host:

```bash
docker node ls
```

| Node | Role | Runs |
| --- | --- | --- |
| IIoT | manager (leader) | nothing from the edge stack; it's where stacks are deployed from |
| RPIIMUJ1 … RPIIMUJ5 | worker | `imu-106` … `imu-110` |
| RPI-IMU-BENCH | worker | `imu-111` (bench node) |
| RPiCamFront | worker, label `camera=front` | `camera-front` |
| CameraPi2 | worker, label `camera=side` | `camera-side` |

## The edge stack

All edge devices are in one stack file, `deploy/swarm-edge-nodes.yml`, deployed as stack **`edge`** (so services are named `edge_imu-106`, `edge_camera-front`, …). Its `${VAR}`s come from `deploy/.env` (see [Two `.env` files](/docker/compose#two-env-files)).

**Nobody deploys it by hand in normal use.** Start Monitoring and Start Session make `fastapi-app` ask [stack-controller](/docker/stack-controller) to deploy only the selected devices (`--prune` removes the rest), with the settings for that mode ([PLC trigger](/operations/plc-auto-stop#imu-plc-trigger-monitor-vs-session), [run parameters](/operations/run-parameters)). Stopping removes the stack.

Each service has:

| | IMUs | Cameras |
| --- | --- | --- |
| Image | `smart-mfg-imu:latest` (local on the Pi) | `camera-edge:latest` (local on the Pi) |
| Placement | `node.hostname == ${IMU_<id>_HOSTNAME}` | `node.labels.camera == front` / `side` |
| Mounts from the Pi | `/run/imu-hw` (socket to `imu_host`), `/opt/smart-mfg-imu/data` | `/run/camera-hw`, `/opt/camera-sensor-fusion/data` |
| Labels | `smr.category: imu`, `smr.device: <id>` | `smr.category: camera`, `smr.device: <id>_<name>` |
| Health check | `python3 -m imu_edge healthcheck`, every 10 s, 15 s warm-up | `python3 -m camera_edge healthcheck`, every 10 s, 30 s warm-up |
| Restart | `on-failure` | `any` |

The `smr.*` labels are how the dashboard learns which devices exist. `--resolve-image never` is used on every deploy, so each Pi must already have the image locally.

## Manual deploy (debugging only)

```bash
cd /home/ubuntu/wku-smr-lab-middleware/deploy
set -a; source ./.env; set +a
docker stack deploy --resolve-image never -c swarm-edge-nodes.yml edge
docker stack rm edge
```

A manual deploy uses only `deploy/.env`, without the dashboard's run parameters or per-mode PLC trigger, and the dashboard doesn't know about it. Data from it is dropped unless the dashboard is monitoring or recording. Don't regenerate the stack file with an unquoted heredoc or `envsubst`; that expands the `${VAR}`s to empty strings.

Useful checks:

```bash
docker stack services edge
docker service ps edge_imu-106 --no-trunc
docker service logs edge_camera-front --since 5m
```

## Known limitation: I2C device access under Swarm (resolved)

Early on, IMU containers deployed under Swarm could see `/dev/i2c-1` but got `EPERM` trying to open it — a device-cgroup permission issue, not a missing file or bad code. Swarm on the Docker version in use doesn't expose `--device` or accept `device_cgroup_rules` in a stack spec, so there was no way to authorize I2C access directly from the stack file.

The fix was architectural, not a Swarm flag: **move I2C access out of the Swarm-managed container entirely.** The `imu_host` process now runs directly on the Pi (via systemd, outside Docker), where it has real permission to open `i2c-1`, and exposes a Unix socket. The Swarm-managed `imu_edge` container only ever talks to that socket — it never touches the I2C bus itself. This is why the [Hardware](/hardware/) page describes IMU nodes as two cooperating processes instead of one container.

## Troubleshooting

| Symptom | Likely cause |
| --- | --- |
| Node shows `Down` in `docker node ls` | The Pi is off or off the network, or its Docker daemon is down. |
| `This node is not a swarm worker` | The Pi fell out of the swarm. Rejoin it with a fresh worker token (`docker swarm join-token worker` on the AMS host). |
| `no suitable node (scheduling constraints not satisfied)` | No node matches the placement. For IMUs, compare the hostname in `deploy/.env` with `docker node ls`; for cameras, check the node's `camera` label (`docker node inspect --pretty <node>` lists its labels). |
| `No such image` | The image isn't on that Pi; build or load it there. |
| `ModuleNotFoundError: No module named 'lgpio'` | Pi-side `imu_host` dependencies are missing. Reinstall `requirements-host.txt`. |
| `PermissionError: /run/imu-hw` | Run `imu_host` through systemd, which creates the runtime directory, or `mkdir`/`chown` it for a manual test run. |
| `Could not establish MQTT connection` | Check `MQTT_BROKER_IP`/`MQTT_BROKER_PORT` in `deploy/.env` and that the Pi can reach 192.168.2.100:1883. |

More device-level symptoms are in [Stack controller & device selection](/docker/stack-controller#troubleshooting).

## History

Before October 2026 there were separate per-device stacks (`imu`, `smr`; files now in `deploy/depr/`), deployed by hand from an older manager at 192.168.1.76. IMUs were pinned by a `device_id` node label and scaled between 0 and 1 replicas from the CLI or Portainer. [Compose vs. Swarm parity](/network/compose-vs-swarm-parity) is a review from that period of a plan to run the whole AMS under Swarm.
