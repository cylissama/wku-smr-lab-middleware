## Camera nodes

Raspberry Pis fitted with cameras run the camera sensor-fusion pipeline (ArUco/marker pose detection) and publish frame + marker pose data to MQTT under `camera/<device_id>`. A separate image-analysis machine consumes and processes the camera stream.


# Marker Pose Data Format: Data from the Camera Nodes

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

## Notes

- `rvec_x/y/z` and `tvec_x/y/z` follow the OpenCV pose convention: `rvec` is a Rodrigues rotation vector and `tvec` is a translation vector, together forming the marker's 6-DOF pose relative to the camera.
- Units for `tvec_*` are inferred (likely meters) — worth confirming against your camera calibration setup.
- `image_path` and `capture_time` were empty/`NaN` in this sample, so their populated format couldn't be confirmed from the data alone.