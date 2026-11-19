# camera-processor: the image processing for every camera Pi, run on the AMS
# (or any machine that can reach the broker) instead of on the Pis.
#
#   camera Pi (camera_host captures + JPEG-encodes, camera_edge forwards)
#       -> camera_frames/<device>/frame        (MQTT, binary, protocol.py)
#   camera-processor (this): ArUco detection + PnP pose, run folders on disk
#       -> camera/<device>                     (MQTT, the same CSV rows as before)
#   fastapi-app ingests camera/# unchanged
#
# One worker thread per camera, each with a bounded queue: if processing falls
# behind, the oldest queued frame is dropped and counted (never the broker or
# the Pi backing up). OpenCV releases the GIL, so cameras process in parallel.
# Rows are published in every capture mode (the dashboard's live view), but run
# folders are only written while fastapi-app is recording (CAMERA_SAVE_WHEN).
# Design: plans/camera-offload-plan.md; docs: web/docs/docker/camera-processor.md.

from __future__ import annotations

import json
import logging
import os
import queue
import signal
import threading
import time
from dataclasses import dataclass, asdict
from pathlib import Path

from . import protocol
from .pipeline import CameraPipeline, row_to_csv_line
from .storage import RunFolder

log = logging.getLogger("camera_processor")


def _flag(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _save_when(value: str) -> str:
    value = (value or "").strip().lower() or "record"
    if value not in {"record", "always"}:
        raise ValueError(f"CAMERA_SAVE_WHEN must be 'record' or 'always', not {value!r}")
    return value


# fastapi-app capture modes in which run folders are written (save_when=record).
# STOPPING too, so the frames still queued when a session stops are kept.
SAVING_MODES = {"record", "stopping"}


@dataclass
class ProcessorConfig:
    # Where the rows go (the broker fastapi-app subscribes to)
    mqtt_host: str = "mqtt-broker"
    mqtt_port: int = 1883
    # Where the frames come from; the same broker unless set
    frame_host: str = "mqtt-broker"
    frame_port: int = 1883
    topic_prefix: str = protocol.DEFAULT_PREFIX
    frame_qos: int = 0
    publish_qos: int = 0
    queue_frames: int = 60
    # Threads per camera sharing its queue. One 1080p frame takes ~12-25 ms to
    # decode + detect (more with a busy scene), and a camera at ~38 fps sends
    # one every 26 ms, so a single thread can't keep up with every camera.
    workers_per_camera: int = 2
    data_root: str = "/data"
    save_frames: bool = True
    save_annotated: bool = True
    save_csv: bool = True
    # When run folders are written: "record" = only while fastapi-app's capture
    # mode is record/stopping (monitoring streams at up to ~100 MB/s for four
    # cameras, which would fill the disk), "always" = every frame as before.
    save_when: str = "record"
    # fastapi-app's GET /capture, polled every capture_poll_s for the mode
    capture_url: str = "http://fastapi-app:8000/capture"
    capture_poll_s: float = 1.0
    health_path: str = "/tmp/camera-processor-health.json"
    stale_after_s: int = 30
    stats_interval_s: float = 30.0

    @classmethod
    def from_env(cls) -> "ProcessorConfig":
        mqtt_host = os.getenv("MQTT_HOST", "mqtt-broker")
        mqtt_port = int(os.getenv("MQTT_PORT", "1883"))
        prefix = os.getenv("CAMERA_FRAME_TOPIC_PREFIX", protocol.DEFAULT_PREFIX).strip().strip("/")
        if not prefix or prefix.lower() == "camera":
            raise ValueError("CAMERA_FRAME_TOPIC_PREFIX must be set and must not be 'camera' "
                             "(fastapi-app ingests camera/# as marker rows)")
        return cls(
            mqtt_host=mqtt_host,
            mqtt_port=mqtt_port,
            frame_host=os.getenv("CAMERA_FRAME_BROKER_HOST") or mqtt_host,
            frame_port=int(os.getenv("CAMERA_FRAME_BROKER_PORT") or mqtt_port),
            topic_prefix=prefix,
            frame_qos=min(1, max(0, int(os.getenv("CAMERA_FRAME_QOS", "0")))),
            publish_qos=min(1, max(0, int(os.getenv("CAMERA_PUBLISH_QOS", "0")))),
            queue_frames=max(1, int(os.getenv("CAMERA_QUEUE_FRAMES", "60"))),
            workers_per_camera=max(1, min(8, int(os.getenv("CAMERA_WORKERS_PER_CAMERA", "2")))),
            data_root=os.getenv("CAMERA_DATA_ROOT", "/data"),
            save_frames=_flag("CAMERA_SAVE_FRAMES", True),
            save_annotated=_flag("CAMERA_SAVE_ANNOTATED", True),
            save_csv=_flag("CAMERA_SAVE_CSV", True),
            save_when=_save_when(os.getenv("CAMERA_SAVE_WHEN", "record")),
            capture_url=os.getenv("CAMERA_CAPTURE_URL", "http://fastapi-app:8000/capture"),
            capture_poll_s=max(0.2, float(os.getenv("CAMERA_CAPTURE_POLL_S", "1"))),
            health_path=os.getenv("CAMERA_PROCESSOR_HEALTH_PATH", "/tmp/camera-processor-health.json"),
            stale_after_s=max(5, int(os.getenv("CAMERA_PROCESSOR_STALE_AFTER_S", "30"))),
            stats_interval_s=max(5.0, float(os.getenv("CAMERA_PROCESSOR_STATS_INTERVAL_S", "30"))),
        )


@dataclass
class DeviceStats:
    received: int = 0
    processed: int = 0
    dropped: int = 0          # queue overflow: processing fell behind
    no_config: int = 0        # frames before the camera's config message
    bad_frames: int = 0       # undecodable payload or JPEG
    frames_with_markers: int = 0
    rows: int = 0
    run_id: str | None = None
    run_folder: str | None = None
    last_frame_at: float | None = None
    last_latency_ms: float | None = None  # Pi sent_at -> rows published


class DeviceWorker:
    """Processes one camera's frames on workers_per_camera threads sharing one queue.

    With more than one thread, frames finish slightly out of order (rows and
    detections.csv lines by a frame or two); each row carries its frame index
    and capture time, so consumers order by those, not arrival.
    """

    def __init__(self, label: str, processor: "CameraProcessor"):
        self.label = label
        self.processor = processor
        self.cfg = processor.cfg
        self.stats = DeviceStats()
        self.pipeline: CameraPipeline | None = None
        self.config_message: dict | None = None
        self._queue: "queue.Queue[tuple[dict, bytes]]" = queue.Queue(maxsize=self.cfg.queue_frames)
        self._folder: RunFolder | None = None
        self._lock = threading.Lock()  # run folder + stats, shared by the threads
        self._local = threading.local()  # each thread's own pipeline copy
        self._stop = threading.Event()
        self._threads = [
            threading.Thread(target=self._run, name=f"camera-{label}-{i}", daemon=True)
            for i in range(max(1, self.cfg.workers_per_camera))
        ]

    def start(self) -> None:
        for thread in self._threads:
            thread.start()

    def stop(self, timeout: float = 10.0) -> None:
        self._stop.set()
        for thread in self._threads:
            if thread.is_alive():
                thread.join(timeout=timeout)
        with self._lock:
            self._close_folder()

    def configure(self, config: dict) -> None:
        # Swapped as one reference, so a thread sees old or new, never a mix.
        self.pipeline = CameraPipeline(config)
        self.config_message = config

    def _thread_pipeline(self) -> CameraPipeline | None:
        # A copy per thread, so no OpenCV detector object is shared between
        # threads; rebuilt when a new config message replaces self.pipeline.
        shared = self.pipeline
        if shared is None:
            return None
        local = self._local
        if getattr(local, "source", None) is not shared:
            local.source = shared
            local.pipeline = CameraPipeline(self.config_message) if len(self._threads) > 1 else shared
        return local.pipeline

    def submit(self, header: dict, jpeg: bytes) -> None:
        self.stats.received += 1
        while True:
            try:
                self._queue.put_nowait((header, jpeg))
                return
            except queue.Full:
                try:
                    self._queue.get_nowait()
                    self.stats.dropped += 1
                except queue.Empty:
                    pass

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                header, jpeg = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                self.process(header, jpeg, self._thread_pipeline())
            except Exception:
                with self._lock:
                    self.stats.bad_frames += 1
                log.exception("camera %s: failed to process frame %s", self.label, header.get("frame_idx"))

    def _close_folder(self) -> None:
        if self._folder is not None:
            self._folder.close()
            self._folder = None

    def _folder_for(self, pipeline: CameraPipeline, run_id: str) -> RunFolder | None:
        if not (self.cfg.save_frames or self.cfg.save_annotated or self.cfg.save_csv):
            return None
        if not self.processor.saving():
            self._close_folder()  # a recording ended: finish its folder
            return None
        if self._folder is None or self._folder.run_id != run_id:
            self._close_folder()
            manifest = {k: v for k, v in (self.config_message or {}).items()}
            self._folder = RunFolder(
                Path(self.cfg.data_root), self.label, pipeline.camera_name, run_id, manifest,
                self.cfg.save_frames, self.cfg.save_annotated, self.cfg.save_csv,
            )
            self.stats.run_folder = str(self._folder.path)
            log.info("camera %s: run %s -> %s", self.label, run_id, self._folder.path,
                     extra={"category": "ingest"})
        return self._folder

    def process(self, header: dict, jpeg: bytes, pipeline: CameraPipeline | None = None) -> list[str]:
        """Process one frame; returns the CSV lines published."""
        pipeline = pipeline or self.pipeline
        if pipeline is None:
            return []
        frame_idx = int(header["frame_idx"])
        run_id = str(header["run_id"])

        image = pipeline.decode(jpeg)
        if image is None:
            with self._lock:
                self.stats.bad_frames += 1
            return []

        with self._lock:
            if run_id != self.stats.run_id:
                self.stats.run_id = run_id
            folder = self._folder_for(pipeline, run_id)
        image_path = folder.write_frame(frame_idx, jpeg) if folder else None
        result = pipeline.process(image, frame_idx, header.get("capture_time_ms"), image_path)
        if result.detections and folder and folder.save_annotated:
            folder.write_annotated(frame_idx, pipeline.annotate(image, frame_idx, result))

        lines = [row_to_csv_line(row) for row in result.rows]
        for line in lines:
            self.processor.publish(pipeline.output_topic, line)

        now = time.time()
        with self._lock:
            if folder:
                folder.write_rows(result.rows)
            if result.detections:
                self.stats.frames_with_markers += 1
            self.stats.processed += 1
            self.stats.rows += len(lines)
            self.stats.last_frame_at = now
            sent_at = header.get("sent_at_ms")
            if sent_at:
                self.stats.last_latency_ms = round(now * 1000 - float(sent_at), 1)
        return lines


class CameraProcessor:
    def __init__(self, cfg: ProcessorConfig, publish_fn=None):
        self.cfg = cfg
        self.workers: dict[str, DeviceWorker] = {}
        self._workers_lock = threading.Lock()
        self._publish_fn = publish_fn
        self._no_config_warned: dict[str, float] = {}
        self.frame_connected = False
        self.output_connected = False
        self.started_at = time.time()
        # fastapi-app's capture mode from the last successful poll; None until
        # the first one. Unreachable keeps the last known mode (a recording
        # survives a fastapi-app restart); never reached means not saving.
        self.capture_mode: str | None = None

    def saving(self) -> bool:
        return self.cfg.save_when == "always" or self.capture_mode in SAVING_MODES

    def set_capture_mode(self, mode: str | None) -> None:
        if mode == self.capture_mode:
            return
        was_saving = self.saving()
        self.capture_mode = mode
        if self.saving() != was_saving:
            log.info("capture mode %s: %s run folders", mode,
                     "writing" if self.saving() else "not writing",
                     extra={"category": "ingest", "important": True})

    # --- message handling (called on the MQTT network thread) ---

    def worker(self, label: str) -> DeviceWorker:
        with self._workers_lock:
            worker = self.workers.get(label)
            if worker is None:
                worker = DeviceWorker(label, self)
                self.workers[label] = worker
                worker.start()
            return worker

    def handle_message(self, topic: str, payload: bytes) -> None:
        try:
            label, kind = protocol.parse_topic(topic, self.cfg.topic_prefix)
        except protocol.ProtocolError:
            return

        if kind == protocol.CONFIG:
            if not payload:  # retained message cleared
                return
            try:
                config = protocol.decode_config(payload)
                expected = protocol.device_label(config["device_id"], config["camera_name"])
                if expected != label:
                    raise protocol.ProtocolError(f"config for {expected} published under {label}")
                self.worker(label).configure(config)
            except (protocol.ProtocolError, ValueError, KeyError, TypeError) as error:
                log.warning("camera %s: ignoring bad config message: %s", label, error,
                            extra={"category": "ingest"})
                return
            log.info("camera %s: config received (dict %s, marker %.4f m, publishing to %s/%s)",
                     label, config.get("aruco_dict"), float(config["marker_length_m"]),
                     str(config.get("client_type") or "camera").lower(), label,
                     extra={"category": "ingest"})
            return

        worker = self.worker(label)
        try:
            header, jpeg = protocol.decode_frame(payload)
        except protocol.ProtocolError as error:
            worker.stats.bad_frames += 1
            log.debug("camera %s: bad frame: %s", label, error)
            return
        if worker.pipeline is None:
            worker.stats.no_config += 1
            last = self._no_config_warned.get(label, 0.0)
            if time.time() - last > 60:
                self._no_config_warned[label] = time.time()
                log.warning("camera %s: frames arriving but no config message on %s yet; dropping them",
                            label, protocol.config_topic(self.cfg.topic_prefix, label),
                            extra={"category": "ingest"})
            return
        worker.submit(header, jpeg)

    def publish(self, topic: str, line: str) -> None:
        if self._publish_fn is not None:
            self._publish_fn(topic, line)

    # --- health ---

    def snapshot(self) -> dict:
        now = time.time()
        devices = {}
        for label, worker in list(self.workers.items()):
            stats = asdict(worker.stats)
            stats["queued"] = worker._queue.qsize()
            stats["threads"] = len(worker._threads)
            stats["configured"] = worker.pipeline is not None
            stats["last_frame_age_s"] = (
                None if worker.stats.last_frame_at is None else round(now - worker.stats.last_frame_at, 1)
            )
            devices[label] = stats
        ok = self.frame_connected and self.output_connected
        return {
            "updated_at_ms": int(now * 1000),
            "state": "ok" if ok else "degraded",
            "frame_broker": f"{self.cfg.frame_host}:{self.cfg.frame_port}",
            "frame_broker_connected": self.frame_connected,
            "output_broker": f"{self.cfg.mqtt_host}:{self.cfg.mqtt_port}",
            "output_broker_connected": self.output_connected,
            "save_when": self.cfg.save_when,
            "capture_mode": self.capture_mode,
            "saving": self.saving(),
            "devices": devices,
        }

    def write_health(self) -> dict:
        snap = self.snapshot()
        path = Path(self.cfg.health_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(snap))
        tmp.replace(path)
        return snap

    def stop(self) -> None:
        for worker in list(self.workers.values()):
            worker.stop()


# --- MQTT wiring -------------------------------------------------------------

def _mqtt_client(client_id: str):
    import paho.mqtt.client as mqtt

    if hasattr(mqtt, "CallbackAPIVersion"):  # paho-mqtt >= 2
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)
    else:
        client = mqtt.Client(client_id=client_id)
    client.reconnect_delay_set(min_delay=1, max_delay=30)
    return client


def _rc_ok(rc) -> bool:
    # paho 2 passes a ReasonCode, paho 1 an int
    return (not rc.is_failure) if hasattr(rc, "is_failure") else rc == 0


def fetch_capture_mode(url: str, timeout: float = 2.0) -> str:
    """fastapi-app's capture mode ("idle", "monitor", "record", "stopping")."""
    import urllib.request

    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return str(json.load(resp)["mode"])


def capture_poll_loop(processor: CameraProcessor, stop: threading.Event, fetch=fetch_capture_mode) -> None:
    cfg = processor.cfg
    failures = 0
    while True:
        try:
            processor.set_capture_mode(fetch(cfg.capture_url))
            failures = 0
        except Exception as error:
            failures += 1
            # fastapi-app is often still starting when this does; warn once it's been a while
            if failures == 10:
                log.warning("can't read the capture mode from %s (%s); keeping %s, %s run folders",
                            cfg.capture_url, error, processor.capture_mode,
                            "writing" if processor.saving() else "not writing",
                            extra={"category": "health", "important": True})
        if stop.wait(cfg.capture_poll_s):
            return


def run(cfg: ProcessorConfig | None = None) -> None:
    cfg = cfg or ProcessorConfig.from_env()
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())

    same_broker = (cfg.frame_host, cfg.frame_port) == (cfg.mqtt_host, cfg.mqtt_port)
    suffix = os.getenv("HOSTNAME", str(os.getpid()))
    out_client = _mqtt_client(f"camera-processor-{suffix}")
    frame_client = out_client if same_broker else _mqtt_client(f"camera-processor-frames-{suffix}")

    processor = CameraProcessor(
        cfg, publish_fn=lambda topic, line: out_client.publish(topic, line, qos=cfg.publish_qos)
    )

    def on_frame_connect(client, _userdata, _flags, rc, _properties=None):
        if not _rc_ok(rc):
            log.warning("frame broker %s:%s refused the connection: %s", cfg.frame_host, cfg.frame_port, rc,
                        extra={"category": "health"})
            return
        processor.frame_connected = True
        if same_broker:
            processor.output_connected = True
        client.subscribe(protocol.subscription(cfg.topic_prefix), qos=cfg.frame_qos)
        log.info("connected to %s:%s, subscribed to %s", cfg.frame_host, cfg.frame_port,
                 protocol.subscription(cfg.topic_prefix), extra={"category": "health", "important": True})

    def on_frame_disconnect(_client, _userdata, *args):
        processor.frame_connected = False
        if same_broker:
            processor.output_connected = False
        log.warning("lost the frame broker %s:%s; reconnecting", cfg.frame_host, cfg.frame_port,
                    extra={"category": "health", "important": True})

    def on_message(_client, _userdata, msg):
        processor.handle_message(msg.topic, msg.payload)

    frame_client.on_connect = on_frame_connect
    frame_client.on_disconnect = on_frame_disconnect
    frame_client.on_message = on_message

    if not same_broker:
        def on_out_connect(_client, _userdata, _flags, rc, _properties=None):
            processor.output_connected = _rc_ok(rc)
            if processor.output_connected:
                log.info("connected to output broker %s:%s", cfg.mqtt_host, cfg.mqtt_port,
                         extra={"category": "health"})

        def on_out_disconnect(_client, _userdata, *args):
            processor.output_connected = False
            log.warning("lost the output broker %s:%s; reconnecting", cfg.mqtt_host, cfg.mqtt_port,
                        extra={"category": "health", "important": True})

        out_client.on_connect = on_out_connect
        out_client.on_disconnect = on_out_disconnect
        out_client.connect_async(cfg.mqtt_host, cfg.mqtt_port, keepalive=30)
        out_client.loop_start()

    if cfg.save_when == "record":
        threading.Thread(target=capture_poll_loop, args=(processor, stop),
                         name="capture-poll", daemon=True).start()
    frame_client.connect_async(cfg.frame_host, cfg.frame_port, keepalive=30)
    frame_client.loop_start()
    log.info(
        "camera-processor starting: frames from %s:%s (%s), rows to %s:%s, data in %s "
        "(frames=%s annotated=%s csv=%s, %s), queue %d frames and %d threads per camera",
        cfg.frame_host, cfg.frame_port, protocol.subscription(cfg.topic_prefix),
        cfg.mqtt_host, cfg.mqtt_port, cfg.data_root,
        cfg.save_frames, cfg.save_annotated, cfg.save_csv,
        "always" if cfg.save_when == "always" else f"only while recording, mode from {cfg.capture_url}",
        cfg.queue_frames, cfg.workers_per_camera,
        extra={"category": "system", "important": True},
    )

    last_stats = time.monotonic()
    reported: dict[str, int] = {}
    try:
        while not stop.wait(5.0):
            snap = processor.write_health()
            if time.monotonic() - last_stats >= cfg.stats_interval_s:
                last_stats = time.monotonic()
                for label, s in snap["devices"].items():
                    if s["received"] == reported.get(label):
                        continue  # nothing new from this camera
                    reported[label] = s["received"]
                    log.info(
                        "camera %s: received %d, processed %d, with markers %d, rows %d, "
                        "dropped %d (queue full), no-config %d, bad %d, latency %s ms",
                        label, s["received"], s["processed"], s["frames_with_markers"], s["rows"],
                        s["dropped"], s["no_config"], s["bad_frames"], s["last_latency_ms"],
                        extra={"category": "ingest", "context": s},
                    )
    finally:
        log.info("camera-processor stopping", extra={"category": "system"})
        frame_client.loop_stop()
        processor.stop()
        if not same_broker:
            out_client.loop_stop()
        try:
            out_client.disconnect()
        except Exception:
            pass


def healthcheck(cfg: ProcessorConfig | None = None) -> int:
    """Docker HEALTHCHECK: healthy while the main loop keeps the health file fresh.

    A broker that is down is printed, not failed on: restarting this container
    would not bring the broker back (same rule as fast_server/healthcheck.py).
    """
    cfg = cfg or ProcessorConfig.from_env()
    try:
        snap = json.loads(Path(cfg.health_path).read_text())
    except (OSError, ValueError) as error:
        print(f"no health file: {error}")
        return 1
    age_s = time.time() - snap.get("updated_at_ms", 0) / 1000
    if age_s > cfg.stale_after_s:
        print(f"health file is {age_s:.0f}s old")
        return 1
    if snap.get("state") != "ok":
        print(f"degraded: frame broker connected={snap.get('frame_broker_connected')}, "
              f"output broker connected={snap.get('output_broker_connected')}")
    return 0
