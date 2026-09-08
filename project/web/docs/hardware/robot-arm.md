# FANUC Robot Arm

## The robot arm

A robot arm streams joint angles and TCP (tool center point) pose as CSV lines over a raw TCP connection to the `tcp_server`, rather than over MQTT. Unlike the other devices, the robot is started manually by a human operator in the lab — it is not remotely orchestrated.

# Robot Joint & Pose Data Format

| Field | Type | Description | Example Value |
|---|---|---|---|
| `id` | Integer | Unique row identifier for the record | `398479` |
| `ts_epoch` | Integer (epoch s) | Timestamp of the robot controller clock at time of sample | `1552447821` |
| `joint_1` | Float | Joint 1 angle/position (likely degrees) | `0.001674` |
| `joint_2` | Float | Joint 2 angle/position (likely degrees) | `0.001414` |
| `joint_3` | Float | Joint 3 angle/position (likely degrees) | `-0.001159` |
| `joint_4` | Float | Joint 4 angle/position (likely degrees) | `0.000825` |
| `joint_5` | Float | Joint 5 angle/position (likely degrees) | `-90.000511` |
| `joint_6` | Float | Joint 6 angle/position (likely degrees) | `-0.000624` |
| `x` | Float | Tool center point (TCP) position, X-axis (likely mm) | `1783.12` |
| `y` | Float | Tool center point (TCP) position, Y-axis (likely mm) | `-2205.959` |
| `z` | Float | Tool center point (TCP) position, Z-axis (likely mm) | `928.974` |
| `w` | Float | TCP orientation, yaw component (likely degrees) | `179.999` |
| `p` | Float | TCP orientation, pitch component (likely degrees) | `0.001` |
| `r` | Float | TCP orientation, roll component (likely degrees) | `0.001` |
| `recorded_at` | Float (epoch s) | Timestamp when the sample was recorded | `1775679035.11709` |
| `ingested_at` | Float (epoch s) | Timestamp when the record was ingested into the system | `1775679035.298104` |
| `device_id` | Integer | Identifier of the robot/device | `2` |
| `session_id` | Integer | Identifier of the recording session | `318` |
| `frame_id` | Integer | Frame/sequence identifier for the sample | `1` |

## Notes

- `joint_1`–`joint_6` correspond to a 6-axis robot arm's joint positions; units are inferred as degrees (worth confirming against the robot's controller docs).
- `x, y, z, w, p, r` follow a common industrial-robot TCP pose convention (position in mm + orientation as yaw/pitch/roll or similar), but the exact orientation convention should be confirmed against the robot manufacturer's spec.
- `ts_epoch` vs `recorded_at` both appear to be timestamps — `ts_epoch` looks like it may update only per motion segment (repeated across rows) while `recorded_at` is per-sample.