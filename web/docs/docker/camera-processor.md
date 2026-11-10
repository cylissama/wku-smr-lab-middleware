# Camera processor

The `camera-processor` service does the camera image processing that used to run on each camera Pi: ArUco marker detection and per-marker pose. The Pis now only take the photos.

```
camera Pi   camera_host captures + JPEG-encodes, camera_edge forwards each JPEG
    │  MQTT  camera_frames/<device>/frame   (+ retained camera_frames/<device>/config)
    ▼
camera-processor (AMS)   detection + pose, keeps each run's files
    │  MQTT  camera/<device>               the same CSV rows as before
    ▼
fastapi-app              ingests camera/# unchanged
```

`<device>` is the camera's device key without its category, `<DEVICE_ID>_<CAMERA_NAME>`, e.g. `113_front`. Code: `camera_processor/` (built from `camera_processor/Dockerfile`). Design and test results: `plans/camera-offload-plan.md`.

## Turning it on and off

Each camera's `camera_edge` decides with `CAMERA_PROCESSING` in `deploy/.env`, applied on the next deploy:

| `CAMERA_PROCESSING` | The Pi | camera-processor |
| --- | --- | --- |
| `remote` (default in `swarm-edge-nodes.yml`) | captures, waits for the PLC, forwards each JPEG | detects and publishes the rows |
| `local` | does the detection itself and publishes the rows, as before | receives nothing for that camera |

Remote mode needs a `camera-edge:latest` built from the camera edge repo with `camera_edge/frame_forwarder.py` (the patch in `plans/camera-offload/`). A Pi still running an older image ignores the variable and keeps processing locally, so the two can be rolled out in either order.

## What the Pi sends

- **`camera_frames/<device>/config`**, retained, re-sent on every (re)connect: the camera's calibration (`camera_matrix`, `dist_coeffs`) and detection settings (`aruco_dict`, `marker_length_m`, `marker_lengths_m`, `target_ids`) from its env. Calibration stays configured on the Pi (`CAMERA_*_CALIBRATION_PATH`); the processor needs no per-camera settings. Frames that arrive before a camera's config are dropped and logged.
- **`camera_frames/<device>/frame`**, one per frame: a 4-byte header length, a JSON header (`device_id`, `camera_name`, `run_id`, `frame_idx`, `capture_time_ms`, `sent_at_ms`) and the JPEG exactly as `camera_host` encoded it. The Pi doesn't decode it.

The PLC trigger, run boundaries and frame numbering stay on the Pi: with `CAMERA_PLC_TRIGGER` on, frames are only sent between `Data_Start` and `Db_Stop`, numbered from 0 per run, and each run has its own `run_id`. The format is in `camera_processor/protocol.py`; the Pi's copy must match it.

## What the processor does

For each frame, on one worker thread per camera: decode, detect ArUco markers, estimate each marker's pose with PnP, and publish one CSV row per marker in `target_ids` to `camera/<device>`. The rows are the ones the Pi used to publish (see [Camera nodes](/hardware/camera#marker-pose-data-format)), computed by the same OpenCV calls; `recorded_at` is now the processor's clock. No marker in view still means no messages.

Each run gets a folder in the `camera_data` volume (`/data` in the container):

```
/data/<device>/<camera_name>_session_<YYYYmmdd_HHMMSS>/
    config.json          run id + the camera's config message
    detections.csv       the rows published
    frames/f000000.jpg   the JPEG as the Pi sent it
    annotated/f000000_aruco.jpg   frames with a marker, outlined, with pose axes
```

Raw frames are ~0.2-0.4 MB each at 1080p, so ~3-6 MB/s per streaming camera. Turn parts off with `CAMERA_SAVE_FRAMES`, `CAMERA_SAVE_ANNOTATED`, `CAMERA_SAVE_CSV` in the root `.env`. These are the AMS copies. The Pis' own frame saving, which only happens with local processing, is the *Save frames on Pi* / *Save annotated on Pi* [run parameters](/operations/run-parameters) (`CAMERA_EDGE_SAVE_*` in `deploy/.env`).

If processing falls behind, each camera's queue (`CAMERA_QUEUE_FRAMES`, default 60 = 4 s at 15 fps) drops its oldest frame and counts it, so a slow processor never backs up the broker or the Pis.

## Settings (root `.env`)

| Variable | Default | |
| --- | --- | --- |
| `CAMERA_FRAME_BROKER_HOST` / `_PORT` | the stack's `mqtt-broker` | where frames come from; the Pis' `CAMERA_FRAME_BROKER_IP` must point at the same broker |
| `CAMERA_FRAME_TOPIC_PREFIX` | `camera_frames` | must match the Pis'; `camera` is refused |
| `CAMERA_QUEUE_FRAMES` | `60` | per-camera queue before dropping |
| `CAMERA_SAVE_FRAMES`, `CAMERA_SAVE_ANNOTATED`, `CAMERA_SAVE_CSV` | `true` | what each run folder keeps |

Rows always go to the stack's `mqtt-broker`.

## Checking it

- **Container Health box / `docker ps`:** the container is healthy while its main loop runs. A broker that is down is printed by the health check, not failed on: restarting it wouldn't help.
- **Logs** (`docker logs AMS-camera-processor`, or the dashboard's Logs box): `config received` per camera, a `run ... -> <folder>` line per run, and every 30 s per streaming camera: frames received/processed, frames with markers, rows, dropped, and latency from the Pi's send to the published rows.
- **Health file** with per-camera counters: `docker exec AMS-camera-processor cat /tmp/camera-processor-health.json`.
- **On the Pi:** `camera_edge`'s log says `forwarding frames to ...` at start and `frame=N forwarded (forwarded X, dropped Y)` every 50 frames.
- **End to end**, from any machine with the camera edge repo: `python scripts/remote_processing_smoke.py <broker-ip> 1883` runs a fake camera and PLC against the real processor and checks the rows equal local processing.

::: warning Subscribing to `#`
Frame traffic goes through the broker. An MQTT client subscribed to `#` (e.g. MQTT Explorer) receives every JPEG; subscribe to `camera/#` or `imu/#` instead.
:::

## Running it somewhere else

The image needs only an MQTT broker. To run it on another machine (more CPU, a GPU box), start the same image there with `MQTT_HOST`/`MQTT_PORT` set to the AMS broker, and stop the AMS's `camera-processor` so rows aren't published twice.
