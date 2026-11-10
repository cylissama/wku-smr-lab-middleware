# Camera image processing off the Pi

Goal: `CAM_PI (takes photo) -> processing container -> AMS` instead of
`CAM_PI (takes photo + processes) -> AMS`.

Status: implemented and tested locally (below). Not yet rolled out in the lab.

## Where the processing happened (camera edge repo, `plc_update`)

Repo: [UmarKhattab09/wku-smr-lab-camera-edge-node](https://github.com/UmarKhattab09/wku-smr-lab-camera-edge-node/tree/plc_update),
everything under `camera-swarm-fusion/`. Each camera Pi runs two pieces:

| Piece | Runs as | Does |
| --- | --- | --- |
| `camera_host/` | systemd unit `camera-hw` on the Pi (`deploy/systemd/camera-hw.service`), not Docker | Owns `/dev/video0` (`camera_fusion/frame_source.py` `DeviceCameraSource`: OpenCV V4L2, MJPG). Idle until a session starts, then grabs frames at `CAMERA_FPS`, JPEG-encodes them (`manager.py` `_emit_frame`, quality 85) and serves them on a Unix-socket HTTP API at `/run/camera-hw/camera.sock` (`/v1/frame/stream` NDJSON + base64, `/v1/frame/latest`). |
| `camera_edge/` | Swarm service `edge_camera-<name>`, image `camera-edge:latest` built on each Pi | Reads frames from the socket (`service_client.py`), waits for the PLC's `Data_Start`/`Db_Stop` (`plc_signals.py`), and per frame in `agent.py` `_process_frame`: decodes the JPEG, `camera_fusion/detect.py` ArUco detection, `iiot_pipeline/strategies/localize_pnp.py` PnP pose per marker, saves the raw and annotated frames and `detections.csv` under `/opt/camera-sensor-fusion/data`, and publishes one CSV row per marker through `camera_fusion/output.py` `MqttOutput` (facade-sdk) to `camera/<DEVICE_ID>_<CAMERA_NAME>`. |

So all image processing (decode, detection, pose, annotation, file writes) ran
in `camera_edge` on the Pi.

## Design

```
camera_host (Pi, systemd)          captures + JPEG-encodes (unchanged)
   | Unix socket
camera_edge (Pi, Swarm)            CAMERA_PROCESSING=remote: PLC gating, run ids,
   |                               forwards the JPEG bytes unchanged (no decode)
   | MQTT camera_frames/<device>/frame   (+ retained camera_frames/<device>/config)
camera-processor (AMS, compose)    ArUco + PnP, run folders, publishes rows
   | MQTT camera/<device>          the same CSV rows as before
fastapi-app (AMS)                  ingests camera/# unchanged
```

- **Transport: MQTT through the existing broker.** The Pis already reach it,
  paho reconnects on its own, and the processor never needs the Pis' addresses.
  Frames go under a separate prefix (`camera_frames/`) that fastapi-app's
  `camera/#` subscription doesn't match. `CAMERA_FRAME_BROKER_*` can point both
  ends at a separate broker if frame traffic ever needs isolating.
- **Wire format** (`camera_processor/protocol.py`, Pi copy in
  `camera_edge/frame_forwarder.py`): 4-byte header length, JSON header
  (`device_id, camera_name, run_id, frame_idx, capture_time_ms, sent_at_ms`),
  then the JPEG exactly as `camera_host` encoded it. Calibration and detection
  settings travel in a retained config message re-sent on every connect, so the
  processor needs no per-camera config and calibration stays with the camera.
- **What stays on the Pi:** capture, PLC trigger, run boundaries and frame
  numbering (so timing doesn't depend on the network), health for Swarm/"edge ready".
- **Processor:** one worker thread per camera with a bounded queue (drop oldest,
  counted) so a slow processor never backs up the broker or the Pi. Detection
  code is a faithful port (same OpenCV calls, same row layout); OpenCV is pinned
  to 4.x so `estimatePoseSingleMarkers` gives the Pis' numbers.
- **Row fidelity:** the processor's rows equal local processing for the same
  JPEG (checked by the camera repo's `scripts/remote_processing_smoke.py`). Two
  intentional differences: `recorded_at` is the processor's clock (the AMS is
  the NTP server), and the CSV header line the Pi published first on each
  connection (which fastapi-app could only log as a parse error) is written to
  `detections.csv` only.
- **Failure behaviour:** broker down -> the Pi drops and counts frames (no RAM
  buildup), both containers stay healthy and reconnect. Processor down -> frames
  are lost while it is down; Docker restarts it (`smr.autoheal`). Frames before
  a camera's config message are dropped and logged.

## Changes

This repo:

- `camera_processor/` (service, pipeline, storage, protocol, Dockerfile) and the
  `camera-processor` service in `docker-compose.yml` / `docker-compose.local.yml`
  (local `camera_data` volume for run folders)
- `deploy/swarm-edge-nodes.yml`: `CAMERA_PROCESSING` (default `remote`),
  `CAMERA_FRAME_BROKER_IP`, `CAMERA_FRAME_TOPIC_PREFIX` on every camera service
- `.env.example`, `deploy/.env.example`, docs (`web/docs/docker/camera-processor.md`,
  `web/docs/hardware/camera.md`), architecture model
- `tests/camera_processor_test.py`

Camera edge repo: [`camera-offload/0001-camera_edge-remote-processing.patch`](camera-offload/0001-camera_edge-remote-processing.patch),
one commit on top of `plc_update` (2bfe412). `CAMERA_PROCESSING` defaults to
`local` there, so the change is inert until the deploy sets it.

## Verified (in a dev container, not the lab)

- `tests/camera_processor_test.py` passes with OpenCV 4.11 (the pinned version)
  and 5.0 (solvePnP fallback).
- Built both images and ran them with a real Mosquitto: the Pi image in remote
  mode against a fake `camera_host` (1920x1080 @ 15 fps, three markers):
  220 frames -> 660 rows, 0 dropped, ~40 ms from the Pi's send to the rows;
  rows parse with `fast_server.parsing.parse_camera_message`.
- Camera repo `scripts/remote_processing_smoke.py`: two fake-PLC runs, frames
  forwarded only between `Data_Start` and `Db_Stop`, numbered from 0 per run,
  target markers only, and remote rows == local rows for all 44 frames.
- Camera repo `scripts/plc_trigger_smoke.py` (local mode) still passes; its
  pytest suite has the same 13 pre-existing failures with and without the patch.
- Broker restart: both sides stay healthy, drop while it's down, reconnect and resume.

## Rollout

1. Merge this branch; on the AMS: `docker compose up -d --build camera-processor`.
   Check it in the dashboard's Container Health box.
2. Add `CAMERA_PROCESSING=remote` and `CAMERA_FRAME_BROKER_IP=` to `deploy/.env`
   (see `deploy/.env.example`).
3. Apply the patch to the camera edge repo (`git am`), then on each camera Pi pull
   it and rebuild `camera-edge:latest` (until a Pi is rebuilt it ignores the new
   variables and keeps processing locally; nothing breaks in between).
4. Start monitoring with the cameras selected; `docker logs AMS-camera-processor`
   should show `config received` per camera and the stats lines; the Devices box
   should show the cameras receiving as before.
5. Run the smoke test against the lab broker from any machine with the camera
   repo: `python scripts/remote_processing_smoke.py 192.168.2.100 1883`.

Rollback: `CAMERA_PROCESSING=local` in `deploy/.env`, next deploy.

## Open questions

- Bandwidth: ~3-6 MB/s per camera at 1080p/15 fps. Fine on wired gigabit Pis;
  check RPICAM3's link. `CAMERA_JPEG_QUALITY` on `camera_host` trades size for quality.
- Disk: raw frames now land on the AMS (`camera_data` volume) instead of the Pis'
  SD cards, at the same rate. Decide on retention, or set `CAMERA_SAVE_FRAMES=false`.
- Where the processor runs: the AMS by default. To use a separate machine
  (GPU, the image-analysis box), run the same image there with `MQTT_HOST` set
  to the AMS broker and remove it from the AMS compose.
