# Bringing a node online

This covers the full Raspberry Pi host setup for an IMU node and the Swarm steps needed to add it to the cluster. See [Hardware](/hardware/) for why IMU nodes are split into two cooperating processes, and [Docker &gt; Swarm](/docker/swarm) for the Swarm service definitions this node setup feeds into.

The IMU architecture has two parts:

1. A Pi-local hardware service started with `python -m imu_host` — this is what actually has permission to open the I2C bus.
2. A containerized edge service (`imu_edge`), deployed via Swarm, that talks to the host service over the Unix socket at `/run/imu-hw/imu.sock`.

The host service must be working before the Docker container can use the IMU.

## Active IMU nodes

| IMU | Host IP | Swarm Service | Session ID | CSV Output |
| --- | --- | --- | --- | --- |
| IMU 83 | `192.168.1.83` | `imu_83_joint1` | `imu-node-83` | `/app/data/imu-83-joint1.csv` |
| IMU 84 | `192.168.1.84` | `imu_84_joint1` | `imu-node-84` | `/app/data/imu-84-joint1.csv` |
| IMU 85 | `192.168.1.85` | `imu_85_joint1` | `imu-node-85` | `/app/data/imu-85-joint1.csv` |
| IMU 86 | `192.168.1.86` | `imu_86_joint1` | `imu-node-86` | `/app/data/imu-86-joint1.csv` |

IMU 83 is the working reference node; 84, 85, and 86 should be brought online the same way.

## 1. Prepare the Pi

The physical node is assumed to already be a Raspberry Pi connected to the SMR lab network. Clone or copy the [`imu_node_smr`](/overview/repositories) repo onto it and move into the project directory:

```bash
cd /home/admin/imu_node_smr
```

Create and activate a virtual environment if needed:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Install Docker if it isn't already present:

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker admin
newgrp docker
docker version
```

Join the Pi to the Swarm as a worker, using the worker token from the manager:

```bash
docker swarm join-token worker
docker swarm join --token <worker-token> 192.168.1.76:2377
```

From the manager, confirm the node appears:

```bash
docker node ls
```

Then label the node so Swarm's placement constraints can pin the correct IMU service to the correct host:

```bash
docker node update --label-add device_id=192.168.1.83 <node-name-for-83>
docker node update --label-add device_id=192.168.1.84 <node-name-for-84>
docker node update --label-add device_id=192.168.1.85 <node-name-for-85>
docker node update --label-add device_id=192.168.1.86 <node-name-for-86>
```

Check the labels after updating:

```bash
docker node inspect <node-name> --format '{{ .Spec.Labels }}'
```

## 2. Install host dependencies

```bash
python3 -m pip install -r requirements-host.txt
```

The host requirements include `Adafruit-Blinka`, `adafruit-circuitpython-bno08x`, `numpy`, and `lgpio`. If `board` import errors mention `lgpio` specifically, reinstalling the same requirements file usually resolves it.

## 3. Start the hardware service manually

The host service creates and listens on the Unix socket at `/run/imu-hw/imu.sock`. For a first manual test:

```bash
sudo mkdir -p /run/imu-hw
sudo chown admin:admin /run/imu-hw
IMU_SOCKET_PATH=/run/imu-hw/imu.sock python3 -m imu_host
```

If `sudo` reports `unable to resolve host <hostname>: Name or service not known`, it's a `/etc/hosts` issue — edit `/etc/hosts` and change the `127.1.1.1` entry to match the Pi's actual hostname.

Expected startup output includes `IMU connection successfully initialized`. Leave this process running while testing.

## 4. Verify the host service

In a second terminal on the Pi, confirm the socket exists:

```bash
ls -l /run/imu-hw/imu.sock
```

Check readiness and status:

```bash
curl --unix-socket /run/imu-hw/imu.sock http://localhost/v1/readyz
curl --unix-socket /run/imu-hw/imu.sock http://localhost/v1/status
```

When the service is healthy, `readyz` should report `"ready": true`.

## 5. Install the host service with systemd

After manual testing succeeds, install the Pi-local service so it starts automatically. The template unit file lives at `deploy/systemd/imu-hw.service` in the `imu_node_smr` repo. Before installing it on a given Pi, make sure `User`, `Group`, `WorkingDirectory`, and `ExecStart` match that machine. For a repo at `/home/admin/imu_node_smr`:

```ini
[Unit]
Description=Smart Manufacturing IMU Hardware Service
After=network.target

[Service]
Type=simple
User=admin
Group=admin
SupplementaryGroups=i2c gpio
WorkingDirectory=/home/admin/imu_node_smr
Environment=IMU_SOCKET_PATH=/run/imu-hw/imu.sock
ExecStart=/home/admin/imu_node_smr/.venv/bin/python -m imu_host
Restart=always
RestartSec=3
RuntimeDirectory=imu-hw
RuntimeDirectoryMode=0755

[Install]
WantedBy=multi-user.target
```

Install and start it (from the `imu_node_smr` directory):

```bash
sudo cp deploy/systemd/imu-hw.service /etc/systemd/system/imu-hw.service
sudo systemctl daemon-reload
sudo systemctl enable --now imu-hw
sudo systemctl status imu-hw
```

Verify the socket again:

```bash
ls -l /run/imu-hw/imu.sock
curl --unix-socket /run/imu-hw/imu.sock http://localhost/v1/readyz
```

Repeat sections 1 through 5 on every IMU Pi before deploying the full Swarm stack.

## 6. Start the container layer from the manager

Once the host service is ready, the Docker container can connect through the socket mount. The container needs `/run/imu-hw:/run/imu-hw` mounted, `IMU_SOCKET_PATH=/run/imu-hw/imu.sock` set, MQTT settings provided, and runs `python3 -m imu_edge`.

From the Swarm manager, load the repo `.env` and deploy:

```bash
set -a
source ./.env
set +a
docker stack deploy --resolve-image never -c swarm.yml imu
```

Check each IMU service after deployment:

```bash
docker service ps imu_imu_83_joint1
docker service ps imu_imu_84_joint1
docker service ps imu_imu_85_joint1
docker service ps imu_imu_86_joint1
```

Tail logs for any node that isn't starting cleanly:

```bash
docker service logs -f imu_imu_83_joint1
```

If a task stays in `Rejected`, `Pending`, or `Starting`, verify: the Pi joined the Swarm, the node label matches the service placement constraint exactly, the `imu-hw` systemd service is healthy on that Pi, and the image tag in `.env` exists locally or is reachable from that node.

## 7. Bring up a new IMU node end-to-end

Checklist for `192.168.1.84`, `192.168.1.85`, and `192.168.1.86`:

1. Copy or clone the repo to `/home/admin/imu_node_smr`.
2. Create `.venv` and install `requirements-host.txt`.
3. Install Docker if it isn't already present.
4. Join the Pi to the Swarm as a worker.
5. Label the Swarm node from the manager with `device_id=<node-ip>`.
6. Start `python3 -m imu_host` manually and confirm `/v1/readyz` is healthy.
7. Install and enable the `imu-hw` systemd service.
8. Deploy or refresh the stack from the manager with `docker stack deploy --resolve-image never -c swarm.yml imu`.
9. Confirm `docker service ps` schedules the correct service to the correct node.
10. Watch `docker service logs -f` until the container begins sampling and publishing.

## 8. Stopping the system

Tear down the Swarm deployment:

```bash
docker stack rm imu
```

Stop the Pi-local hardware service — `Ctrl+C` if running manually, or `sudo systemctl stop imu-hw` if running under systemd.

## Troubleshooting

| Symptom | Likely cause / fix |
| --- | --- |
| `This node is not a swarm worker` | Rejoin with a current worker token: `docker swarm join --token <worker-token> 192.168.1.76:2377` |
| `no suitable node (scheduling constraints not satisfied on N nodes)` | Node label doesn't match the placement constraint. Compare `docker node inspect <node-name> --format`, Go-template `.Spec.Labels`, against the `node.labels.device_id == ...` line in `swarm.yml`. |
| `ModuleNotFoundError: No module named 'lgpio'` | Reinstall host requirements: `python3 -m pip install -r requirements-host.txt` |
| `PermissionError: [Errno 13] Permission denied: '/run/imu-hw'` | Create the runtime directory manually for a manual test run, or run via systemd — `RuntimeDirectory=imu-hw` creates it automatically. |
| `No such image` | Make sure `IMU_EDGE_IMAGE` matches an image that actually exists on the target node. |
| `Could not establish MQTT connection` | Check `MQTT_BROKER_IP`, `MQTT_BROKER_PORT`, and network reachability from the container. |
