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

The middleware runs on the MiniPC at `192.168.1.76` and is normally already up — check the [Dashboard](http://192.168.1.76/data/dashboard) first. If it's reachable and showing healthy listeners, skip to step 2. Otherwise, SSH into the middleware host (credentials via the lab's password manager, not written here) and start it:

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

Green listening indicators mean the middleware is waiting for incoming data. Red messages about no active session yet (e.g. `CAMERA batch insert failed: No current active session. Run a GET to start a new session.`) are expected before a session starts and are not a blocker.

## 7. Start a session from the dashboard

Once the dashboard is healthy, the robot operator is ready, and the IMU services are already running in Swarm, click **Start Session**. Because the IMU services are already running, they begin associating data with the session as soon as it starts.

## 8. Start the robot

Started manually by the human operator in the downstairs lab — coordinate with them before starting the session and IMU services.

## 9. Stop the IMU services and end the session

When the robot run is complete, remove the IMU stack:

```bash
docker stack rm imu
```

Give the system roughly 15–20 seconds to flush any remaining messages, then click **Stop Session**.

## 10. Review data

- [Database Browser](http://192.168.1.111:8080/browser/)
- [Dashboard](http://192.168.1.76/data/dashboard)

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
