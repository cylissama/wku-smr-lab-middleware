# Running a test session

Current as of Apr 20, 2026. This replaces the older per-device `docker compose --env-file ... up -d` workflow for IMU nodes — IMUs are now launched from the Swarm manager instead of individually. All operations listed here are assumed to run on the Alienware PC or the Swarm manager unless stated otherwise.

## Overview

1. Initialize the middleware.
2. Confirm the IMU RPIs are powered on and their host services are healthy.
3. Start the camera nodes.
4. Deploy the IMU Swarm stack from the manager.
5. Confirm the dashboard is listening.
6. Start a session from the dashboard.
7. Confirm the IMU services are actively publishing.
8. Start the robot.
9. Stop the IMU services and session when the robot run ends.
10. Review the collected data.

## 1. Initialize the middleware

The middleware runs on the MiniPC at `192.168.1.76` and is normally already up — check the [Dashboard](http://192.168.2.100/) first. If it's reachable and showing healthy listeners, skip to step 2. Otherwise, SSH into the middleware host (credentials via the lab's password manager, not written here) and start it:

```bash
ssh data-team@192.168.1.76
cd smart_manufacturing_research/project
docker compose up -d
```

`up` creates and starts the services defined in `docker-compose.yml`; `-d` runs them detached so the terminal returns immediately instead of streaming logs.

If image analysis is also required, start it on the image analysis machine:

```bash
ssh username@192.168.1.113
cd camera_sensor_fusion/pi-stream/
docker compose up -d
```

## 2. Confirm the IMU RPIs are ready

Before deploying the Swarm stack, make sure each IMU Pi is powered on and its host-side hardware service is healthy. The active IMU RPIs are `192.168.1.83`, `.84`, and `.85`. Each should already have the `imu-hw` systemd service installed per [Bringing a node online](/expanding/swarm-nodes).

```bash
ssh admin@192.168.1.83
sudo systemctl status imu-hw --no-pager
ls -l /run/imu-hw/imu.sock
curl --unix-socket /run/imu-hw/imu.sock http://localhost/v1/readyz
```

Repeat for `.84` and `.85`. Healthy signs: `imu-hw` is `active (running)`, the socket exists, and `readyz` returns `"ready": true`.

## 3. Start the camera nodes

Cameras still follow their normal startup flow:

```bash
ssh admin@192.168.1.80
cd camera_sensor_fusion/
docker compose up -d
```

```bash
ssh admin@192.168.1.92
cd camera_sensor_fusion/middleware/
docker compose up -d
```

## 4. Deploy the IMU Swarm stack

This is the biggest difference from the older per-device workflow: don't SSH into each IMU Pi and run `docker compose --env-file ... up -d`. Deploy the IMU services once from the Swarm manager instead.

```bash
ssh <manager-user>@192.168.1.76
cd /home/user/CS560-Smart-Manufacturing-Data/project

# Load .env into the current shell
set -a
source ./.env
set +a

docker stack deploy --resolve-image never -c swarm.yml imu
```

`--resolve-image never` skips registry lookups for image digests, useful when the needed image is already present locally. `imu` is the stack name, which is why services appear as `imu_imu_83_joint1` etc. Each service is pinned to its matching Pi via the `node.labels.device_id` placement constraint and gets its device-specific env values from `.env`.

## 5. Verify the Swarm deployment

```bash
docker service ps imu_imu_83_joint1
docker service ps imu_imu_84_joint2
docker service ps imu_imu_85_joint3
```

Inspect a service's resolved environment if needed:

```bash
docker service inspect imu_imu_85_joint3 --format '{{range .Spec.TaskTemplate.ContainerSpec.Env}}{{println .}}{{end}}'
```

Watch logs:

```bash
docker service logs -f imu_imu_83_joint1
```

Healthy signs: a running task on the correct node, no socket connection failures in the logs, and the service begins sampling and publishing. If a service won't start, check that the target Pi is online and in the Swarm, its node label matches the placement constraint, `imu-hw` is healthy on that Pi, and the image tag in `.env` is reachable.

## 6. Ensure the dashboard shows listening status

Green listening indicators mean the dashboard's WebSocket feeds are connected. With no session running, the middleware ignores any device data that arrives — nothing is queued or stored, and nothing from before the session is carried into it. Data is only captured between **Start Session** and **Stop Session**. The badge next to the session indicator shows the current capture mode: **Idle**, **Monitoring — not saved**, **Recording**, or **Stopping**.

### Choose which devices to run

The **Devices** panel lists every IMU, camera, and the robot with its current state. Everything is ticked by default. Untick devices to test only part of the system — a whole category with its group box, or single devices. Only the ticked devices are started, shown in the live feeds, and recorded; the session remembers which devices it used. The selection is locked while monitoring or recording.

Each device's status moves through **not deployed → starting → running → receiving**:

- **starting / running** come from Docker Swarm. A device shows *starting* until its container's first health check passes (about 10 s for IMUs, longer for cameras while they warm up).
- **receiving · N msg/s** means its data is actually reaching the AMS right now (a message within the last 3 s). This is the one to trust.
- **running · no data** (red) while monitoring or recording means the device is up but nothing is arriving — e.g. a camera with no marker in view, or a wrong MQTT topic.
- The robot shows **connected** when it has a TCP connection open, and **receiving** once lines arrive.

The status dots, and the **Field Devices** graphics in the left margin on wide screens (about 1840 px and up), share one color code:

| Color | Meaning |
|---|---|
| Grey | Offline: not deployed, or the robot isn't connected. Normal while idle. |
| Blue | Standby: starting, running or connected, but not sending (or not being listened to). |
| Green | Sending: data is arriving now. The graphic shows the message rate (`TX · N/s`). |
| Red | Fault: a Swarm error, no status from stack-controller, or up but no data while monitoring/recording. |

Devices left out of the current selection are dimmed in the graphics.

### Optional: check the devices with monitor mode first

To see that devices are publishing without recording anything, click **Start Monitoring**. This brings the edge devices up and shows one cyan `[live]` line per device per second in the Camera / IMU / Robot panels (message rate plus latest values). Nothing is written to the database. While monitoring, the IMUs stream right away; they don't wait for the robot's PLC. From here you can either click **Start Session** or **Stop Monitoring** to take the devices back down. Starting a session from monitoring restarts the IMU services (only those; the cameras keep running) so they switch to waiting for the PLC. See step 7.

## 7. Start a session from the dashboard

Once the dashboard is healthy, the robot operator is ready, and the IMU services are already running in Swarm, click **Start Session**. Because the IMU services are already running, they begin associating data with the session as soon as it starts.

In a session, the IMUs run in **PLC trigger mode**: they only send data after the robot's PLC pulses `Data_Start`, tare on `IMU_Tare`, and stop sending on `Db_Stop`. Starting a session therefore (re)starts the IMU services, and the Messages box says so. An IMU only notices a `Data_Start` that comes *after* it is running, so wait until the IMUs show as running before starting the robot. Until the robot starts, the IMUs show as not receiving; that's expected.

## 8. Start the robot

Started manually by the human operator in the downstairs lab — coordinate with them before starting the session and IMU services.

## 9. Stop the IMU services and end the session

When the robot run is complete, remove the IMU stack:

```bash
docker stack rm imu
```

Then click **Stop Session**. It stops accepting new data first, then waits (up to 10 s) for the IMU, camera, and robot buffers to finish writing before ending the session; a warning names any buffer that didn't drain in time.

If PLC auto stop is on (the default in the lab), you don't have to click it: when the robot finishes, the PLC pulses `Db_Stop` and the session stops itself the same way. The dashboard switches to **Idle** within about 5 s. See [PLC auto stop](./plc-auto-stop).

## 10. Review data

- [Database Browser](http://192.168.2.100:5050/browser/)
- [Dashboard](http://192.168.2.100/)

## Quick reference

```bash
# Start middleware
docker compose up -d

# Deploy IMU Swarm services
cd /home/user/CS560-Smart-Manufacturing-Data/project
set -a; source ./.env; set +a
docker stack deploy --resolve-image never -c swarm.yml imu

# Check / tail IMU services
docker service ps imu_imu_83_joint1
docker service logs -f imu_imu_83_joint1

# Stop IMU Swarm services
docker stack rm imu
```

::: warning
This procedure came from an SOP that had a literal SSH password written inline. It's already in this repo's git history — if that password is still in use for `data-team@192.168.1.76`, rotate it.
:::
