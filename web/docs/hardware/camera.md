# Camera nodes

Raspberry Pis with cameras take the photos for the camera sensor-fusion pipeline: ArUco marker pose detection (code: [wku-smr-lab-camera-edge-node](https://github.com/UmarKhattab09/wku-smr-lab-camera-edge-node/tree/plc_update), branch `plc_update`, `camera-swarm-fusion/`). Each frame's marker poses are published over MQTT to `camera/<device_id>_<name>`, for example `camera/114_cam1`. The markers on the robot, and their sizes, are listed in [ArUco markers](/hardware/aruco-markers). A message is sent only for frames where a marker is detected, so **no marker in view means no messages**, and the Devices box then shows *running · no data*.

## Where each step runs

| Step | Where | Code (camera edge repo) |
| --- | --- | --- |
| Open `/dev/video0` (OpenCV V4L2, MJPG), grab frames at `CAMERA_FPS`, JPEG-encode | Pi: `camera_host`, systemd unit `camera-hw`, not Docker | `camera_host/`, `camera_fusion/frame_source.py` |
| Wait for the PLC, number each run's frames | Pi: `camera_edge` (Swarm service) | `camera_edge/agent.py`, `plc_signals.py` |
| Decode, ArUco detection, PnP pose, save frames, publish rows | **`CAMERA_PROCESSING=remote`** (default): [camera-processor](/docker/camera-processor) on the AMS. `local`: `camera_edge` on the Pi | `camera_processor/` here; `camera_edge/agent.py` `_process_frame` on the Pi |

`camera_host` serves the frames on a Unix-socket API at `/run/camera-hw/camera.sock`, which is why the containers mount `/run/camera-hw`. In remote mode `camera_edge` forwards the JPEG bytes unchanged on `camera_frames/<device_id>_<name>/frame`; see [Camera processor](/docker/camera-processor).

## Nodes

| Swarm service | Device key / MQTT topic | Pi (hostname) | Placement |
| --- | --- | --- | --- |
| `camera-cam1` | `camera/114_cam1` | RPICAM1 (192.168.1.114) | `node.labels.camera == cam1` |
| `camera-cam2` | `camera/113_cam2` | RPICAM2 (192.168.1.113) | `node.labels.camera == cam2` |
| `camera-cam3` | `camera/94_cam3` | RPICAM3 (192.168.1.94) | `node.labels.camera == cam3` |
| `camera-cam4` | `camera/60_cam4` | RPICAM4 (192.168.1.60) | `node.labels.camera == cam4` |

Device ids, names and calibration files come from `deploy/.env` (`CAMERA_CAM1_DEVICE_ID`, `CAMERA_CAM1_NAME`, `CAMERA_CAM1_CALIBRATION_PATH`, …). Each `CAMERA_CAM<N>_DEVICE_ID` is the last octet of that Pi's IP (RPICAM1 at .114 → `114`); nothing derives it automatically, so change it if a Pi's IP changes. The calibration is read on the Pi and sent to camera-processor in the camera's config message. The containers (image `camera-edge:latest`) mount `/run/camera-hw` and `/opt/camera-sensor-fusion/data` from the Pi; with remote processing nothing is written to the data folder (run folders are on the AMS).

With `CAMERA_PLC_TRIGGER=true`, a camera waits for the [PLC](/hardware/plc)'s `Data_Start` pulse before sending and stops on `Db_Stop` (or after `CAMERA_PLC_MAX_RUN_S`). `fastapi-app` sets this on every deploy, the same as the IMUs': off while monitoring, on for a session unless the Run Parameters panel or `IMU_PLC_TRIGGER_ON_RECORD` says otherwise. See [PLC auto stop](/operations/plc-auto-stop#imu-plc-trigger-monitor-vs-session).

::: warning Calibration placeholders
`deploy/.env.example` points every camera at `calib/PLACEHOLDER_front_1920x1080.yml`. Check that each camera has its own real calibration file.
:::

::: info Placeholder
TODO: how `camera-edge:latest` is built on each Pi (and where the `camera-hw` unit's checkout lives, `/home/admin/camera_swarm_stuff/camera-swarm-fusion` in the repo's unit file), and what the image-analysis machine does with the stream. To view a camera's live video, see [Camera live feed](/operations/camera-ops).
:::

## Marker pose data format

| Field | Type | Description | Example Value |
|---|---|---|---|
| `id` | Integer | Unique row identifier for the record | `964148` |
| `frame_idx` | Integer | Index of the video/capture frame the detection belongs to | `67` |
| `marker_idx` | Integer | The detected marker's ArUco ID ([markers on the robot](/hardware/aruco-markers)) | `3` |
| `rvec_x` | Float | Rotation vector, X component (Rodrigues representation, radians) | `-2.5944445313622717` |
| `rvec_y` | Float | Rotation vector, Y component (Rodrigues representation, radians) | `0.07264518829616069` |
| `rvec_z` | Float | Rotation vector, Z component (Rodrigues representation, radians) | `-1.2751264283290702` |
| `tvec_x` | Float | Marker position, metres: the camera frame's **Y** (see notes) | `-0.5318441733067558` |
| `tvec_y` | Float | Marker position, metres: the camera frame's **Z** (distance from the camera) | `2.6731892890859474` |
| `tvec_z` | Float | Marker position, metres: the camera frame's **X** | `-0.5036038234276543` |
| `image_path` | String | Always empty in the database (the frame's path is only in the run folder's `detections.csv`) | *(empty)* |
| `recorded_at` | Float (epoch s) | When camera-processor produced the row (the AMS clock) | `1775679027.678343` |
| `ingested_at` | Float (epoch s) | Timestamp when the record was ingested into the system | `1775679028.212774` |
| `device_id` | Integer | Identifier of the capturing device/camera | `270` |
| `session_id` | Integer | Identifier of the recording session | `318` |
| `capture_time` | Float (epoch s) | When the Pi captured the frame (the Pi's clock); `NaN` if the frame had no capture time | `NaN` |

### Notes

- `rvec_x/y/z` is an OpenCV Rodrigues rotation vector (radians): the marker's rotation relative to the camera.
- `tvec_*` is in metres, because the marker sizes are configured in metres. It's only right if the marker's configured size matches the printed one; see [Why the size matters](/hardware/aruco-markers#why-the-size-matters).
- The translation is stored in the axis order the Pi always published, `(y, z, x)` of OpenCV's camera frame (`map_tvec_axes()` in `camera_processor/pipeline.py`): `tvec_x` is the camera's Y (down), `tvec_y` its Z (forward, so it's the distance from the camera), `tvec_z` its X (right). The rotation isn't reordered.
- On the wire, each MQTT message on `camera/<device>` is one CSV row: `frame_idx, capture_time, recorded_at, marker_id, rvec_x, rvec_y, rvec_z, tvec_x, tvec_y, tvec_z, marker_length_m, image_path, device_id`. `fast_server/parsing.py` stores the first ten fields.
