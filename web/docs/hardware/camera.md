# Camera nodes

Raspberry Pis with cameras run the camera sensor-fusion pipeline: ArUco marker pose detection (code: [camera_sensor_fusion](https://github.com/UmarKhattab09/camera_sensor_fusion)). They publish each frame's marker poses over MQTT to `camera/<device_id>_<name>`, for example `camera/113_front`. A message is sent only for frames where a marker is detected, so **no marker in view means no messages**, and the Devices box then shows *running · no data*.

## Nodes

| Swarm service | Device key / MQTT topic | Pi (hostname) | Placement |
| --- | --- | --- | --- |
| `camera-front` | `camera/113_front` | RPiCamFront | `node.labels.camera == front` |
| `camera-side` | `camera/114_side` | CameraPi2 | `node.labels.camera == side` |

Device ids, names and calibration files come from `deploy/.env` (`CAMERA_FRONT_DEVICE_ID`, `CAMERA_FRONT_NAME`, `CAMERA_FRONT_CALIBRATION_PATH`, …). The containers (image `camera-edge:latest`) mount `/run/camera-hw` and `/opt/camera-sensor-fusion/data` from the Pi.

::: warning Calibration placeholders
`deploy/.env.example` points both cameras at `calib/PLACEHOLDER_front_1920x1080.yml`. Check that each camera has its own real calibration file.
:::

::: info Placeholder
TODO: the camera Pi's host-side setup (what provides `/run/camera-hw`, how `camera-edge:latest` is built), and what the image-analysis machine does with the stream. To view a camera's live video, see [Camera live feed](/operations/camera-ops).
:::

## Marker pose data format

| Field | Type | Description | Example Value |
|---|---|---|---|
| `id` | Integer | Unique row identifier for the record | `964148` |
| `frame_idx` | Integer | Index of the video/capture frame the detection belongs to | `67` |
| `marker_idx` | Integer | Identifier of the detected marker (e.g. ArUco marker ID) | `3` |
| `rvec_x` | Float | Rotation vector, X component (Rodrigues representation, radians) | `-2.5944445313622717` |
| `rvec_y` | Float | Rotation vector, Y component (Rodrigues representation, radians) | `0.07264518829616069` |
| `rvec_z` | Float | Rotation vector, Z component (Rodrigues representation, radians) | `-1.2751264283290702` |
| `tvec_x` | Float | Translation vector, X component (marker position, likely meters) | `-0.5318441733067558` |
| `tvec_y` | Float | Translation vector, Y component (marker position, likely meters) | `2.6731892890859474` |
| `tvec_z` | Float | Translation vector, Z component (marker position, likely meters) | `-0.5036038234276543` |
| `image_path` | String | File path to the associated captured image (blank if not saved) | *(empty)* |
| `recorded_at` | Float (epoch s) | Timestamp when the detection was recorded | `1775679027.678343` |
| `ingested_at` | Float (epoch s) | Timestamp when the record was ingested into the system | `1775679028.212774` |
| `device_id` | Integer | Identifier of the capturing device/camera | `270` |
| `session_id` | Integer | Identifier of the recording session | `318` |
| `capture_time` | String/Float | Timestamp when the frame was captured (`NaN` if unavailable) | `NaN` |

### Notes

- `rvec_x/y/z` and `tvec_x/y/z` follow the OpenCV pose convention: `rvec` is a Rodrigues rotation vector and `tvec` is a translation vector, together forming the marker's 6-DOF pose relative to the camera.
- Units for `tvec_*` are inferred (likely meters) — worth confirming against your camera calibration setup.
- `image_path` and `capture_time` were empty/`NaN` in this sample, so their populated format couldn't be confirmed from the data alone.