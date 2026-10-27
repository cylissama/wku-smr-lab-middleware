# Running a test session

The procedure for recording one robot run. Since October 2026 everything except the robot itself is driven from the [dashboard](/overview/dashboard): it starts the selected IMUs and cameras, records, and takes them back down. You no longer deploy anything over SSH.

## Overview

1. Check the dashboard and the AMS are healthy.
2. Check the edge Pis are up.
3. Choose devices and check the run parameters.
4. (Optional) Monitor to check the devices are sending.
5. Start the session.
6. Start the robot.
7. Stop: automatically when the robot finishes, or with Stop Session.
8. Review the data.

## 1. Check the dashboard and the AMS

Open the [Dashboard](http://192.168.2.100/). The **System Health** strip should be all green, and the **Container Health** box at the bottom should show every container as healthy. If something is red, see [Troubleshooting](/operations/troubleshooting).

The AMS stack is always on. If the dashboard doesn't load at all, SSH to the [AMS host](/hardware/data-broker-mini-pc) and start it:

```bash
ssh data-team@192.168.2.100
cd /home/ubuntu/wku-smr-lab-middleware
docker compose up -d
```

## 2. Check the edge Pis

The IMU and camera Pis must be powered on and in the Swarm. On the AMS host, `docker node ls` should show each one as `Ready` (see the node list in [Swarm](/docker/swarm#the-cluster)). On the dashboard, a device whose Pi is down sits at *starting* and never becomes *running* after you start monitoring.

Each IMU Pi also runs the `imu-hw` host service. If an IMU starts but never sends, check it on that Pi:

```bash
ssh admin@192.168.1.106          # RPIIMUJ1; .107–.110 for J2–J5
sudo systemctl status imu-hw --no-pager
curl --unix-socket /run/imu-hw/imu.sock http://localhost/v1/readyz   # "ready": true
```

::: info Placeholder
TODO: the SSH user for the IMU and camera Pis, and anything the camera Pis need before a run.
:::

If image analysis is also needed, start it on the image analysis machine:

::: info Placeholder
TODO: confirm the image analysis machine and its start command. The old SOP used `ssh username@192.168.1.113`, then `cd camera_sensor_fusion/pi-stream/ && docker compose up -d`, but 192.168.1.113 is now a camera Pi.
:::

## 3. Choose devices and check the run parameters

### Devices

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

### Run parameters

The **Run Parameters** card (right margin on wide screens, under Devices otherwise) shows the IMU sample rate, whether the IMUs wait for the PLC, and the IMU max run time. Values stay set from the previous run, so check them. See [Run parameters](/operations/run-parameters).

Pick the **session type** in the dropdown, and tick **Fake Data** if this is a test rather than real data.

## 4. (Optional) Monitor first

To check that devices are publishing without recording anything, click **Start Monitoring**. This brings the selected devices up and shows one cyan `[live]` line per device per second in the Camera / IMU / Robot boxes (message rate plus latest values). Nothing is written to the database. While monitoring, the IMUs stream right away; they don't wait for the robot's PLC.

From here, click **Start Session** to record, or **Stop Monitoring** to take the devices back down.

## 5. Start the session

Click **Start Session**, then **Confirm & Start**. The confirmation lists any run parameters changed from their defaults.

In a session, the IMUs run in **PLC trigger mode**: they only send after the robot's PLC pulses `Data_Start`, tare on `IMU_Tare`, and stop sending on `Db_Stop`. Starting a session therefore (re)starts the IMU services (the cameras keep running if you were monitoring), and the Misc box says so. An IMU only notices a `Data_Start` that comes *after* it is running, so **wait until the IMUs show as running before starting the robot**. Until the robot starts, the IMUs show as not receiving; that's expected.

To record without the PLC (for example, no robot run), turn off **Wait for PLC start** in Run Parameters first.

## 6. Start the robot

The robot is started manually by the operator in the downstairs lab. Coordinate with them before starting the session.

## 7. Stop

With PLC auto stop on (the lab default), you don't have to do anything. When the robot finishes, the PLC pulses `Db_Stop` and the session stops itself. The dashboard switches to **Idle** within about 5 s. See [PLC auto stop](/operations/plc-auto-stop).

Otherwise, click **Stop Session**. Either way, the AMS:

1. stops accepting new data
2. removes the edge devices
3. waits up to 10 s for the IMU, camera and robot buffers to be written (a warning names any that didn't drain in time)
4. ends the session
5. takes a database backup

## 8. Review the data

- [pgAdmin](http://192.168.2.100:5050/browser/); new users see [Getting database access](/data/new-student-access)
- Each session row records its devices and run parameters; see [Sessions & capture modes](/overview/capture-modes#sessions)

## Quick reference (AMS host)

```bash
docker compose ps                         # AMS containers
docker node ls                            # edge Pis in the Swarm
docker stack services edge                # edge devices running now
docker service logs edge_imu-106 --since 5m
curl -s localhost:8000/capture            # idle / monitor / record / stopping
```

::: warning
An older version of this procedure had a literal SSH password for `data-team` written inline. It's in this repo's git history; if that password is still in use, rotate it.
:::
