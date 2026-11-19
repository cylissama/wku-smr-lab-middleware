"""camera-processor: wire protocol, detection/pose rows, run folders, message handling.

Synthetic frames: real ArUco markers drawn on a white canvas and JPEG-encoded,
the same bytes a Pi's camera_host would send. Rows are checked with fastapi-app's
own parser, so a format drift between the processor and ingestion fails here.
"""
import csv
import json
import math
import tempfile
import time
import unittest
import unittest.mock
from pathlib import Path

import cv2
import numpy as np
import yaml

from camera_processor import protocol
from camera_processor.pipeline import CSV_HEADER, CameraPipeline, row_to_csv_line
from camera_processor.service import (CameraProcessor, DeviceWorker, ProcessorConfig,
                                      capture_poll_loop, healthcheck)
from fast_server.parsing import parse_camera_message

ROOT = Path(__file__).resolve().parent.parent

FOCAL = 1000.0
W, H = 1280, 720
MARKER_PX = 200
MARKER_M = 0.05  # 200 px at f=1000 -> 0.25 m away


def camera_config(**overrides):
    config = {
        "device_id": "113",
        "camera_name": "cam1",
        "client_type": "CAMERA",
        "aruco_dict": "4x4_50",
        "marker_length_m": MARKER_M,
        "marker_lengths_m": None,
        "target_ids": None,
        "camera_matrix": [[FOCAL, 0, W / 2], [0, FOCAL, H / 2], [0, 0, 1]],
        "dist_coeffs": [0, 0, 0, 0, 0],
        "image_size": [W, H],
    }
    config.update(overrides)
    return config


def marker_image(ids=(3,), size=MARKER_PX):
    image = np.full((H, W, 3), 255, np.uint8)
    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    for i, marker_id in enumerate(ids):
        marker = cv2.aruco.generateImageMarker(dictionary, marker_id, size)
        x = 100 + i * (size + 120)
        y = (H - size) // 2
        image[y:y + size, x:x + size] = cv2.cvtColor(marker, cv2.COLOR_GRAY2BGR)
    return image


def jpeg(image) -> bytes:
    ok, buf = cv2.imencode(".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
    assert ok
    return buf.tobytes()


def header(frame_idx=0, run_id="run-1", capture_time_ms=1_700_000_000_123):
    return {"device_id": "113", "camera_name": "cam1", "run_id": run_id,
            "frame_idx": frame_idx, "capture_time_ms": capture_time_ms,
            "sent_at_ms": int(time.time() * 1000)}


def cfg(tmp, **overrides):
    # save_when=always: these tests aren't about the capture mode (RecordGateTests are)
    values = dict(data_root=tmp, health_path=str(Path(tmp) / "health.json"), save_when="always")
    values.update(overrides)
    return ProcessorConfig(**values)


class ProtocolTests(unittest.TestCase):

    def test_frame_round_trip_keeps_jpeg_bytes(self):
        data = jpeg(marker_image())
        payload = protocol.encode_frame(header(7), data)
        got_header, got_jpeg = protocol.decode_frame(payload)
        self.assertEqual(got_jpeg, data)
        self.assertEqual(got_header["frame_idx"], 7)
        self.assertEqual(got_header["v"], protocol.VERSION)

    def test_bad_frames_are_rejected(self):
        good = protocol.encode_frame(header(), b"\xff\xd8jpeg")
        for bad in (b"", b"\x00\x00", b"\x00\x10\x00\x00{}",
                    good[:4] + b"not json" + good[4:],
                    protocol.encode_frame(header(), b"")):
            with self.assertRaises(protocol.ProtocolError):
                protocol.decode_frame(bad)
        missing = {k: v for k, v in header().items() if k != "run_id"}
        with self.assertRaises(protocol.ProtocolError):
            protocol.decode_frame(protocol.encode_frame(missing, b"x"))
        wrong_version = protocol.encode_frame(header(), b"x").replace(b'"v":1', b'"v":9')
        with self.assertRaises(protocol.ProtocolError):
            protocol.decode_frame(wrong_version)

    def test_topics(self):
        self.assertEqual(protocol.frame_topic("camera_frames", "113_cam1"), "camera_frames/113_cam1/frame")
        self.assertEqual(protocol.parse_topic("camera_frames/113_cam1/config", "camera_frames"),
                         ("113_cam1", "config"))
        for topic in ("camera/113_cam1", "camera_frames/113_cam1", "other/113_cam1/frame",
                      "camera_frames/113_cam1/frame/x", "camera_frames//frame"):
            with self.assertRaises(protocol.ProtocolError):
                protocol.parse_topic(topic, "camera_frames")

    def test_prefix_cannot_collide_with_ingested_topics(self):
        with unittest.mock.patch.dict("os.environ", {"CAMERA_FRAME_TOPIC_PREFIX": "camera"}):
            with self.assertRaises(ValueError):
                ProcessorConfig.from_env()

    def test_config_round_trip_and_validation(self):
        config = protocol.decode_config(protocol.encode_config(camera_config()))
        self.assertEqual(config["device_id"], "113")
        with self.assertRaises(protocol.ProtocolError):
            protocol.decode_config(protocol.encode_config({"device_id": "113"}))


class PipelineTests(unittest.TestCase):

    def test_detects_marker_and_pose_distance(self):
        pipeline = CameraPipeline(camera_config())
        result = pipeline.process(marker_image((3,)), 5, 1_700_000_000_123, recorded_at=1_700_000_001.5)
        self.assertEqual([d.marker_id for d in result.detections], [3])
        self.assertEqual(len(result.rows), 1)

        # The row is what fastapi-app ingests from camera/113_cam1
        self.assertEqual(pipeline.output_topic, "camera/113_cam1")
        parsed = parse_camera_message(pipeline.output_topic, row_to_csv_line(result.rows[0]).encode())
        self.assertEqual(parsed["device_label"], "113_cam1")
        self.assertEqual(parsed["frame_idx"], 5)
        self.assertEqual(parsed["marker_idx"], 3)
        self.assertAlmostEqual(parsed["capture_time"], 1_700_000_000.123, places=3)
        self.assertAlmostEqual(parsed["recorded_at"], 1_700_000_001.5, places=3)
        # tvec is published as (y, z, x): the distance from the camera is tvec_y
        self.assertAlmostEqual(parsed["tvec_y"], FOCAL * MARKER_M / MARKER_PX, delta=0.01)

    def test_row_layout_matches_the_pi(self):
        # MqttOutput (use_length=True): 10 pose fields, length_m, image_path, device_id
        pipeline = CameraPipeline(camera_config())
        row = pipeline.process(marker_image((3,)), 0, 1000, image_path="113_cam1/x/frames/f000000.jpg").rows[0]
        self.assertEqual(len(row), len(CSV_HEADER))
        self.assertEqual(row[10], MARKER_M)
        self.assertEqual(row[11], "113_cam1/x/frames/f000000.jpg")
        self.assertEqual(row[12], "113")
        self.assertEqual(row[1], "1.000000")

    def test_target_ids_and_per_marker_lengths(self):
        pipeline = CameraPipeline(camera_config(target_ids=[7], marker_lengths_m={"7": 0.1}))
        result = pipeline.process(marker_image((3, 7)), 0, 0)
        self.assertEqual(sorted(d.marker_id for d in result.detections), [3, 7])
        self.assertEqual([r[3] for r in result.rows], [7])
        self.assertEqual(result.rows[0][10], 0.1)
        # twice the marker length -> twice the distance
        self.assertAlmostEqual(float(result.rows[0][8]), FOCAL * 0.1 / MARKER_PX, delta=0.02)

    def test_no_marker_no_rows(self):
        pipeline = CameraPipeline(camera_config())
        self.assertEqual(pipeline.process(np.full((H, W, 3), 255, np.uint8), 0, 0).rows, [])

    def test_no_length_gives_nan_pose(self):
        pipeline = CameraPipeline(camera_config(marker_length_m=0))
        row = pipeline.process(marker_image((3,)), 0, 0).rows[0]
        self.assertTrue(all(math.isnan(v) for v in row[4:10]))


class WorkerTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.published = []
        self.processor = CameraProcessor(cfg(self.tmp), publish_fn=lambda t, l: self.published.append((t, l)))

    def worker(self):
        worker = DeviceWorker("113_cam1", self.processor)  # not started: process() is called directly
        worker.configure(camera_config())
        return worker

    def test_run_folders_frames_and_csv(self):
        worker = self.worker()
        data = jpeg(marker_image((3,)))
        worker.process(header(0, "run-1"), data)
        worker.process(header(1, "run-1"), data)
        first = Path(worker.stats.run_folder)
        worker.process(header(0, "run-2"), data)
        second = Path(worker.stats.run_folder)
        worker.stop(timeout=0)

        self.assertNotEqual(first, second)
        self.assertEqual(first.parent, Path(self.tmp) / "113_cam1")
        self.assertEqual((first / "frames" / "f000001.jpg").read_bytes(), data)  # stored as sent
        self.assertTrue((first / "annotated" / "f000000_aruco.jpg").exists())
        self.assertEqual(json.loads((first / "config.json").read_text())["run_id"], "run-1")
        rows = list(csv.reader((first / "detections.csv").open()))
        self.assertEqual(rows[0], CSV_HEADER)
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[1][11], "113_cam1/" + first.name + "/frames/f000000.jpg")

        self.assertEqual(len(self.published), 3)
        self.assertTrue(all(t == "camera/113_cam1" for t, _ in self.published))
        self.assertEqual(worker.stats.processed, 3)
        self.assertEqual(worker.stats.frames_with_markers, 3)

    def test_saving_off_writes_nothing(self):
        self.processor = CameraProcessor(
            cfg(self.tmp, save_frames=False, save_annotated=False, save_csv=False),
            publish_fn=lambda t, l: self.published.append((t, l)))
        worker = self.worker()
        lines = worker.process(header(), jpeg(marker_image((3,))))
        self.assertEqual(len(lines), 1)
        self.assertEqual(list(Path(self.tmp).iterdir()), [])
        self.assertEqual(lines[0].split(",")[11], "")

    def test_undecodable_jpeg_is_counted(self):
        worker = self.worker()
        self.assertEqual(worker.process(header(), b"\xff\xd8 not a jpeg"), [])
        self.assertEqual(worker.stats.bad_frames, 1)

    def test_queue_drops_oldest_when_full(self):
        self.processor.cfg.queue_frames = 2
        worker = DeviceWorker("113_cam1", self.processor)
        for i in range(5):
            worker.submit(header(i), b"x")
        self.assertEqual(worker.stats.received, 5)
        self.assertEqual(worker.stats.dropped, 3)
        self.assertEqual([worker._queue.get_nowait()[0]["frame_idx"] for _ in range(2)], [3, 4])


class RecordGateTests(unittest.TestCase):
    """save_when=record: run folders only while fastapi-app records, rows always."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.published = []
        self.processor = CameraProcessor(cfg(self.tmp, save_when="record"),
                                         publish_fn=lambda t, l: self.published.append((t, l)))
        self.worker = DeviceWorker("113_cam1", self.processor)
        self.worker.configure(camera_config())
        self.data = jpeg(marker_image((3,)))

    def folders(self):
        root = Path(self.tmp) / "113_cam1"
        return sorted(root.iterdir()) if root.exists() else []

    def test_monitoring_publishes_but_saves_nothing(self):
        for mode in (None, "idle", "monitor"):
            self.processor.set_capture_mode(mode)
            self.assertEqual(len(self.worker.process(header(0, "run-1"), self.data)), 1, mode)
        self.assertEqual(len(self.published), 3)
        self.assertEqual(self.folders(), [])
        self.assertFalse(self.processor.snapshot()["saving"])

    def test_record_writes_until_the_session_ends(self):
        self.processor.set_capture_mode("monitor")
        self.worker.process(header(0, "run-1"), self.data)
        self.processor.set_capture_mode("record")
        self.worker.process(header(1, "run-1"), self.data)
        self.processor.set_capture_mode("stopping")  # frames still queued at stop are kept
        self.worker.process(header(2, "run-1"), self.data)
        self.processor.set_capture_mode("idle")
        self.worker.process(header(3, "run-1"), self.data)

        [folder] = self.folders()
        self.assertEqual(sorted(p.name for p in (folder / "frames").iterdir()), ["f000001.jpg", "f000002.jpg"])
        rows = list(csv.reader((folder / "detections.csv").open()))
        self.assertEqual(len(rows), 3)  # header + frames 1, 2 (closed and flushed at idle)
        self.assertIsNone(self.worker._folder)
        self.assertEqual(len(self.published), 4)

    def test_poll_loop_keeps_the_last_mode_when_unreachable(self):
        replies = iter(["record", OSError("connection refused"), OSError("timeout")])
        stop = unittest.mock.Mock()
        stop.wait.side_effect = [False, False, True]

        def fetch(url):
            reply = next(replies)
            if isinstance(reply, Exception):
                raise reply
            return reply

        capture_poll_loop(self.processor, stop, fetch=fetch)
        self.assertEqual(self.processor.capture_mode, "record")
        self.assertTrue(self.processor.saving())

    def test_save_when_from_env(self):
        with unittest.mock.patch.dict("os.environ", {"CAMERA_SAVE_WHEN": ""}):
            self.assertEqual(ProcessorConfig.from_env().save_when, "record")
        with unittest.mock.patch.dict("os.environ", {"CAMERA_SAVE_WHEN": "Always"}):
            self.assertEqual(ProcessorConfig.from_env().save_when, "always")
        with unittest.mock.patch.dict("os.environ", {"CAMERA_SAVE_WHEN": "monitor"}):
            with self.assertRaises(ValueError):
                ProcessorConfig.from_env()


class ProcessorMessageTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.published = []
        self.processor = CameraProcessor(cfg(self.tmp), publish_fn=lambda t, l: self.published.append((t, l)))

    def tearDown(self):
        self.processor.stop()

    def wait_for(self, predicate, timeout=10):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if predicate():
                return True
            time.sleep(0.02)
        return False

    def test_frames_wait_for_config_then_process(self):
        frame = protocol.encode_frame(header(0), jpeg(marker_image((3,))))
        self.processor.handle_message("camera_frames/113_cam1/frame", frame)
        self.assertEqual(self.processor.workers["113_cam1"].stats.no_config, 1)

        self.processor.handle_message("camera_frames/113_cam1/config", protocol.encode_config(camera_config()))
        self.processor.handle_message("camera_frames/113_cam1/frame", frame)
        self.assertTrue(self.wait_for(lambda: self.published), "frame was not processed")
        self.assertEqual(self.published[0][0], "camera/113_cam1")

        snap = self.processor.snapshot()
        self.assertTrue(snap["devices"]["113_cam1"]["configured"])
        self.assertEqual(snap["devices"]["113_cam1"]["rows"], 1)

    def test_several_threads_per_camera_process_every_frame(self):
        self.processor.cfg.workers_per_camera = 3
        self.processor.cfg.queue_frames = 100
        self.processor.handle_message("camera_frames/113_cam1/config", protocol.encode_config(camera_config()))
        worker = self.processor.workers["113_cam1"]
        self.assertEqual(len(worker._threads), 3)
        data = jpeg(marker_image((3,)))
        for i in range(30):
            self.processor.handle_message("camera_frames/113_cam1/frame", protocol.encode_frame(header(i), data))
        self.assertTrue(self.wait_for(lambda: worker.stats.processed == 30), worker.stats)
        self.assertEqual(worker.stats.dropped, 0)
        self.assertEqual(len(self.published), 30)
        [folder] = (Path(self.tmp) / "113_cam1").iterdir()
        self.assertEqual(len(list((folder / "frames").iterdir())), 30)
        rows = list(csv.reader((folder / "detections.csv").open()))[1:]
        self.assertEqual(sorted(int(r[0]) for r in rows), list(range(30)))  # every frame once, any order

    def test_bad_and_foreign_messages_are_ignored(self):
        self.processor.handle_message("camera/113_cam1", b"1,2,3")
        self.processor.handle_message("camera_frames/113_cam1/config", b"{not json")
        # a config naming another camera than its topic
        self.processor.handle_message("camera_frames/114_cam2/config", protocol.encode_config(camera_config()))
        self.processor.handle_message("camera_frames/113_cam1/config", b"")  # retained clear
        self.assertTrue(all(w.pipeline is None for w in self.processor.workers.values()))
        self.processor.handle_message("camera_frames/113_cam1/frame", b"garbage")
        self.assertEqual(self.processor.workers["113_cam1"].stats.bad_frames, 1)

    def test_healthcheck(self):
        conf = self.processor.cfg
        self.assertEqual(healthcheck(conf), 1)  # no file yet
        self.processor.write_health()
        self.assertEqual(healthcheck(conf), 0)  # degraded (no broker) still passes
        snap = json.loads(Path(conf.health_path).read_text())
        snap["updated_at_ms"] -= (conf.stale_after_s + 5) * 1000
        Path(conf.health_path).write_text(json.dumps(snap))
        self.assertEqual(healthcheck(conf), 1)


class DeployConfigTests(unittest.TestCase):

    def test_compose_service(self):
        for name in ("docker-compose.yml", "docker-compose.local.yml"):
            svc = yaml.safe_load((ROOT / name).read_text())["services"]["camera-processor"]
            self.assertEqual(svc["build"]["dockerfile"], "camera_processor/Dockerfile", name)
            self.assertEqual(svc["labels"]["smr.monitor"], "true", name)
            self.assertEqual(svc["labels"]["smr.autoheal"], "true", name)
            self.assertIn("camera_processor", svc["healthcheck"]["test"], name)
            env = dict(e.split("=", 1) for e in svc["environment"])
            self.assertEqual(env["CAMERA_SAVE_WHEN"], "${CAMERA_SAVE_WHEN:-record}", name)
            self.assertEqual(env["CAMERA_WORKERS_PER_CAMERA"], "${CAMERA_WORKERS_PER_CAMERA:-2}", name)
            self.assertEqual(env["CAMERA_CAPTURE_URL"], "http://fastapi-app:8000/capture", name)

    def test_cameras_forward_to_the_same_prefix(self):
        services = yaml.safe_load((ROOT / "deploy" / "swarm-edge-nodes.yml").read_text())["services"]
        cameras = {n: s for n, s in services.items()
                   if s["deploy"]["labels"].get("smr.category") == "camera"}
        self.assertTrue(cameras)
        for name, svc in cameras.items():
            env = svc["environment"]
            self.assertIn("CAMERA_PROCESSING", env, name)
            self.assertIn("camera_frames", env["CAMERA_FRAME_TOPIC_PREFIX"], name)
            self.assertEqual(env["CAMERA_FPS"], "${CAMERA_FPS:-15}", name)  # else camera_edge's 15
            self.assertEqual(env["CAMERA_STOP_SESSION_ON_EXIT"], "true", name)  # new fps on redeploy


if __name__ == "__main__":
    unittest.main()
