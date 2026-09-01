# Inertial Measurement Unit: IMU Nodes
 

Wiki for what an [IMU](https://en.wikipedia.org/wiki/Inertial_measurement_unit) is.

## IMU nodes

Each IMU joint is a Raspberry Pi running a BNO08x 9-DoF IMU over I2C, split into two cooperating processes:

1. **`imu_host`** — a Pi-local (non-containerized) hardware service that talks to the IMU directly over I2C and exposes a Unix socket at `/run/imu-hw/imu.sock`. It's installed as a `systemd` service so it survives reboots.
2. **`imu_edge`** — a containerized service, deployed via Docker Swarm, that connects to `imu_host` through that socket and publishes readings over MQTT (`imu/<device_id>`).

This host-service-plus-container split exists specifically because Docker Swarm on these nodes cannot grant a task sandbox usable device-cgroup access to `i2c-1` — see [Docker \> Swarm](/docker/swarm) for the full story. The `imu_host` process, running directly on the Pi, is what actually has permission to open the I2C bus.

Each IMU Pi is joined to the Swarm as a worker and labeled with its own device ID (`device_id=<node-ip>`) so the matching `imu_edge` Swarm service is always scheduled onto the correct physical node.


# IMU Data Format

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

## Notes

- Units for `accel_*` and `mag_*` are inferred (g and µT respectively) — worth confirming against your device spec since they weren't explicit in the data.
- `gyro_x/y/z` are all `0` in this sample, so units couldn't be confirmed from the data alone (likely deg/s or rad/s).