# IMU nodes

Wikipedia: [inertial measurement unit](https://en.wikipedia.org/wiki/Inertial_measurement_unit).

Each robot joint has a Raspberry Pi with a BNO08x 9-DoF IMU on I2C. Code: [wku-smr-lab-imu-edge-node](https://github.com/cylissama/wku-smr-lab-imu-edge-node), installed on each Pi at `/opt/smart-mfg-imu`.

## Nodes

| Swarm service | Device key / MQTT topic | Pi (hostname) | Address |
| --- | --- | --- | --- |
| `imu-106` | `imu/106` | RPIIMUJ1 | 192.168.1.106 |
| `imu-107` | `imu/107` | RPIIMUJ2 | 192.168.1.107 |
| `imu-108` | `imu/108` | RPIIMUJ3 | 192.168.1.108 |
| `imu-109` | `imu/109` | RPIIMUJ4 | 192.168.1.109 |
| `imu-110` | `imu/110` | RPIIMUJ5 | 192.168.1.110 |
| `imu-111` | `imu/111` | RPI-IMU-BENCH | bench node, currently on 192.168.4.x |

Device ids and hostnames come from `deploy/.env` (`IMU_106_DEVICE_ID`, `IMU_106_HOSTNAME`, …). Each service is pinned to its Pi with `node.hostname == ${IMU_<id>_HOSTNAME}`.

## Two processes per Pi

1. **`imu_host`**: a Pi-local service, not in a container, run by `systemd` as `imu-hw`. It talks to the IMU over I2C and serves a small HTTP API on the Unix socket `/run/imu-hw/imu.sock` (`/v1/readyz`, `/v1/status`, session start/stop, tare, a telemetry stream).
2. **`imu_edge`**: the container that the edge stack runs (image `smart-mfg-imu:latest`). It starts a session on `imu_host` with the requested sample rate, reads the telemetry stream, and publishes each sample over MQTT to `imu/<device_id>`. It also writes a CSV under `/opt/smart-mfg-imu/data`.

The split exists because Docker Swarm can't give a container usable access to `/dev/i2c-1`. See [Swarm](/docker/swarm#known-limitation-i2c-device-access-under-swarm-resolved). Setting up a new Pi is covered in [Bringing a node online](/expanding/swarm-nodes).

## PLC trigger mode

With `IMU_PLC_TRIGGER=true`, an IMU waits for the [PLC](/hardware/plc)'s `Data_Start` pulse before sending, tares on `IMU_Tare`, and stops sending on `Db_Stop` (or after `IMU_PLC_MAX_RUN_S`). `fastapi-app` sets this on every deploy: off while monitoring, on for a session unless the Run Parameters panel or `IMU_PLC_TRIGGER_ON_RECORD` says otherwise. See [PLC auto stop](/operations/plc-auto-stop#imu-plc-trigger-monitor-vs-session).

## Sample rate

`IMU_SAMPLE_HZ` (default 100, set per run in [Run parameters](/operations/run-parameters)) is sent to `imu_host` when the container starts its session. While monitoring or recording, the Devices box shows the rate actually arriving (`receiving · N msg/s`).

## IMU data format

| Field | Type | Description | Example Value |
|---|---|---|---|
| `id` | Integer | Unique row identifier for the record | `2211674` |
| `device_id` | Integer | Identifier of the IMU/sensor device | `275` |
| `session_id` | Integer | Identifier of the recording session | `318` |
| `accel_x` | Float | Accelerometer reading, X-axis (likely in g) | `0.01171875` |
| `accel_y` | Float | Accelerometer reading, Y-axis (likely in g) | `0.0078125` |
| `accel_z` | Float | Accelerometer reading, Z-axis (likely in g) | `0.01953125` |
| `gyro_x` | Float | Gyroscope reading, X-axis (angular velocity) | `0` |
| `gyro_y` | Float | Gyroscope reading, Y-axis (angular velocity) | `0` |
| `gyro_z` | Float | Gyroscope reading, Z-axis (angular velocity) | `0` |
| `mag_x` | Float | Magnetometer reading, X-axis (likely µT) | `33.3125` |
| `mag_y` | Float | Magnetometer reading, Y-axis (likely µT) | `11.9375` |
| `mag_z` | Float | Magnetometer reading, Z-axis (likely µT) | `-156.9375` |
| `yaw` | Float | Orientation angle, yaw (degrees) | `-0.037` |
| `pitch` | Float | Orientation angle, pitch (degrees) | `-0.678` |
| `roll` | Float | Orientation angle, roll (degrees) | `-177.314` |
| `recorded_at` | Integer (epoch ms) | Timestamp when the sample was recorded | `1775679031110` |
| `ingested_at` | Float (epoch s) | Timestamp when the record was ingested into the system | `1775679031.537057` |
| `frame_id` | Integer | Frame/sequence identifier for the sample | `87` |
| `capture_time` | Integer (epoch ms) | Timestamp when the sensor captured the sample | `1775679031099` |

### Notes

- On the wire, each MQTT message on `imu/<device_id>` is one comma-separated sample: `counter, capture_time_ms, recorded_at_time_ms, accel_x…z, gyro_x…z, mag_x…z, yaw, pitch, roll, device_id` (parsed by `fast_server/parsing.py`).
- [Database structure](/data/database-structure#_2-6-imu-measurement) lists the units as m/s², rad/s and µT, which is what the Adafruit BNO08x library reports.

::: info Placeholder
TODO: confirm the units against the `imu_host` code, and whether `accel_*` is linear acceleration (gravity removed). The sample above shows `accel_z` ≈ 0, not ≈ 9.8.
:::