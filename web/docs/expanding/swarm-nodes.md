# Bringing a node online

How to add a Raspberry Pi to the edge stack, from a bare Pi to a device you can tick on the dashboard. See [IMU nodes](/hardware/imu) for why an IMU Pi runs two processes, and [Swarm](/docker/swarm) for the stack this feeds into.

An IMU node has two parts:

1. **`imu_host`**, a Pi-local hardware service (systemd unit `imu-hw`), the only thing that opens the I2C bus. It listens on `/run/imu-hw/imu.sock`.
2. **`imu_edge`**, the container the edge stack runs (image `smart-mfg-imu:latest`), which talks to `imu_host` over that socket.

The host service must work before the container can use the IMU.

## 1. Prepare the Pi

The Pi should be on the lab network with a fixed address (see the [IP Address Table](/network/ip-addresses)) and a **unique hostname**, because the stack pins each IMU service by hostname. Existing IMU Pis are `RPIIMUJ1` … `RPIIMUJ5`.

Put the [IMU edge repo](https://github.com/cylissama/wku-smr-lab-imu-edge-node) at `/opt/smart-mfg-imu` (the stack mounts `/opt/smart-mfg-imu/data`), and create a virtual environment:

```bash
cd /opt/smart-mfg-imu
python3 -m venv .venv
source .venv/bin/activate
```

::: info Placeholder
TODO: which branch the Pis run (`plc_update` has the PLC trigger), and who owns `/opt/smart-mfg-imu` on the Pi.
:::

## 2. Set up the hardware service

### Install host dependencies

```bash
python3 -m pip install -r requirements-host.txt
```

The host requirements include `Adafruit-Blinka`, `adafruit-circuitpython-bno08x`, `numpy`, and `lgpio`. If `board` import errors mention `lgpio` specifically, reinstalling the same requirements file usually resolves it.

### Start the hardware service manually

The host service creates and listens on the Unix socket at `/run/imu-hw/imu.sock`. For a first manual test:

```bash
sudo mkdir -p /run/imu-hw
sudo chown admin:admin /run/imu-hw
IMU_SOCKET_PATH=/run/imu-hw/imu.sock python3 -m imu_host
```

If `sudo` reports `unable to resolve host <hostname>: Name or service not known`, it's a `/etc/hosts` issue — edit `/etc/hosts` and change the `127.1.1.1` entry to match the Pi's actual hostname.

Expected startup output includes `IMU connection successfully initialized`. Leave this process running while testing.

### Verify the host service

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

### Install the host service with systemd

After manual testing succeeds, install the Pi-local service so it starts automatically. The unit file is `deploy/systemd/imu-hw.service` in the edge repo. Make sure `User`, `Group`, `WorkingDirectory` and `ExecStart` match the Pi. For the repo at `/opt/smart-mfg-imu`:

```ini
[Unit]
Description=Smart Manufacturing IMU Hardware Service
After=network.target

[Service]
Type=simple
User=admin
Group=admin
SupplementaryGroups=i2c gpio
WorkingDirectory=/opt/smart-mfg-imu
Environment=IMU_SOCKET_PATH=/run/imu-hw/imu.sock
ExecStart=/opt/smart-mfg-imu/.venv/bin/python -m imu_host
Restart=always
RestartSec=3
RuntimeDirectory=imu-hw
RuntimeDirectoryMode=0755

[Install]
WantedBy=multi-user.target
```

Install and start it (from `/opt/smart-mfg-imu`):

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


## 3. Install Docker and the image

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker admin
newgrp docker
docker version
```

The stack deploys with `--resolve-image never`, so `smart-mfg-imu:latest` must exist on the Pi itself.

::: info Placeholder
TODO: the command used to build or load `smart-mfg-imu:latest` on a Pi (for example `docker build -t smart-mfg-imu:latest .` in `/opt/smart-mfg-imu`, if that's how it's done).
:::

## 4. Join the Swarm

On the AMS host (the manager), get the worker token:

```bash
docker swarm join-token worker
```

On the Pi:

```bash
docker swarm join --token <worker-token> 192.168.2.100:2377
```

Back on the AMS host, check that the Pi is `Ready`:

```bash
docker node ls
```

IMUs need no node label; they're placed by hostname. Cameras are placed by label:

```bash
docker node update --label-add camera=front <node-name>   # or camera=side
```

## 5. Add the device to the edge stack

On the AMS host, in `/home/ubuntu/wku-smr-lab-middleware`:

1. In `deploy/swarm-edge-nodes.yml`, copy an existing `imu-1xx` service block and change every `IMU_1xx_` variable to the new id. Keep the `smr.category` / `smr.device` labels; they put the device on the dashboard.
2. Add `IMU_<id>_DEVICE_ID` and `IMU_<id>_HOSTNAME` to `deploy/.env`, and to `deploy/.env.example` (with the real hostname, no secrets).
3. Reload the dashboard. The new device shows up in the Devices box; no restart is needed because stack-controller reads both files on each request.

## 6. Test it

1. On the dashboard, tick only the new device and click **Start Monitoring**.
2. It should go *starting* → *running* → *receiving · ~100 msg/s* within about 30 s.
3. If it stays at *starting*, check on the AMS host:

   ```bash
   docker service ps edge_imu-<id> --no-trunc
   docker service logs edge_imu-<id> --since 5m
   ```

4. Click **Stop Monitoring**.

## Adding a camera node

The same Swarm steps apply (join, label `camera=<name>`, add a service block like `camera-front`, add the `CAMERA_<NAME>_*` variables to `deploy/.env`). The device key is `camera/<device_id>_<name>`.

::: info Placeholder
TODO: camera Pi host setup: what provides `/run/camera-hw`, the calibration file, and how `camera-edge:latest` gets onto the Pi.
:::

## Troubleshooting

See [Swarm troubleshooting](/docker/swarm#troubleshooting) and [Stack controller troubleshooting](/docker/stack-controller#troubleshooting).
