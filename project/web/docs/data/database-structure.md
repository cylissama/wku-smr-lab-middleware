# Database structure

There is no committed schema file — the tables below are derived from the actual `INSERT`/`SELECT` statements in `db/database.py` (the source of truth) plus the change history in `db/migrations.md`. If you change the schema, update this page as part of the workflow in [Database uses](/data/database-uses).

## Entity relationships

```text
session ──< session_device >── device
   │                               │
   ├──< imu_measurement ──────────┤ (device_id)
   ├──< robot                     │
   └──< image_detection ──────────┘
```

- A **session** groups everything captured during one test run.
- A **device** is any IMU, camera, or the robot ("main"), identified by a `label` that's cached in memory after first use.
- `session_device` is a join table recording which devices reported into which session.
- `imu_measurement`, `robot`, and `image_detection` each hold one row per reading/frame, tagged with both `session_id` and `device_id`.

## `session`

| Column | Notes |
| --- | --- |
| `id` | Primary key |
| `label` | Unique, human-chosen session name |
| `started_at` | UTC epoch |
| `ended_at` | UTC epoch, `NULL` while active |
| `is_test_session` | Boolean, defaults to test session |

## `device`

| Column | Notes |
| --- | --- |
| `id` | Primary key |
| `label` | Unique device identifier, e.g. `83`, `main` |
| `category` | `imu`, `camera`, or `robot` |
| `ip_address` | Best-effort, defaults to `0.0.0.0` |
| `registered_at` | UTC epoch of first sighting |

## `session_device`

| Column | Notes |
| --- | --- |
| `device_id` | FK → `device.id` |
| `session_id` | FK → `session.id` |

Unique on `(device_id, session_id)`; insert is `ON CONFLICT DO NOTHING`.

## `imu_measurement`

| Column | Notes |
| --- | --- |
| `frame_id` | `bigint`, added in a later migration (backfilled to `0`) |
| `capture_time` | `double precision`, device-reported capture time |
| `recorded_at` | Device timestamp at capture |
| `ingested_at` | Broker-side UTC epoch at insert |
| `device_id` | FK → `device.id` |
| `session_id` | FK → `session.id` |
| `accel_x`, `accel_y`, `accel_z` | Accelerometer |
| `gyro_x`, `gyro_y`, `gyro_z` | Gyroscope |
| `mag_x`, `mag_y`, `mag_z` | Magnetometer |
| `yaw`, `pitch`, `roll` | Fused orientation |

## `robot`

| Column | Notes |
| --- | --- |
| `frame_id` | Frame counter from the robot |
| `ts_epoch` | Robot-reported timestamp |
| `joint_1` … `joint_6` | Joint angles |
| `x`, `y`, `z` | TCP position |
| `w`, `p`, `r` | TCP orientation |
| `recorded_at` | Broker-side capture time |
| `ingested_at` | Broker-side UTC epoch at insert |
| `device_id` | FK → `device.id` (always the `"main"` robot device) |
| `session_id` | FK → `session.id` |

## `image_detection`

| Column | Notes |
| --- | --- |
| `frame_idx` | Frame counter |
| `capture_time` | Device-reported capture time |
| `recorded_at` | Broker-side capture time |
| `marker_idx` | ArUco/marker index detected in-frame |
| `rvec_x`, `rvec_y`, `rvec_z` | Rotation vector |
| `tvec_x`, `tvec_y`, `tvec_z` | Translation vector |
| `image_path` | Currently unused/empty — reserved for future image storage |
| `device_id` | FK → `device.id` |
| `session_id` | FK → `session.id` |
| `ingested_at` | Broker-side UTC epoch at insert |

::: tip
`imu_measurement.capture_time` was added after the table's initial creation (see `db/migrations.md`), which is also why the safe-migration workflow in [Database uses](/data/database-uses) insists on adding new columns without `NOT NULL` first.
:::
