# The image processing that used to run on each camera Pi: ArUco marker
# detection and per-marker PnP pose, turned into the CSV rows fastapi-app
# ingests from camera/<device>.
#
# Ported from the camera edge repo (UmarKhattab09/wku-smr-lab-camera-edge-node,
# branch plc_update, camera-swarm-fusion/), keeping its numbers identical:
#   camera_fusion/detect.py                     build_detector, detect_markers
#   iiot_pipeline/strategies/detect_aruco.py    get_dict, _make_params
#   iiot_pipeline/strategies/localize_pnp.py    PnPLocalize
#   camera_fusion/output.py MqttOutput          the row layout (_build_row)
#   camera_edge/agent.py _process_frame         target_ids filter, annotated image
# If the Pi-side code changes how it detects or what it sends, change it here.

from __future__ import annotations

import csv
import io
import time
from dataclasses import dataclass, field
from typing import Any

import cv2
import numpy as np

from .protocol import device_label

# MqttOutput's header (CsvWriter.HEADER_WITH_LENGTH + device_id). The Pi sent
# it as the first message of a connection; fastapi-app can't parse it, so the
# processor only writes it to the run's detections.csv.
CSV_HEADER = [
    "frame_idx", "capture_time", "recorded_at", "marker_id",
    "rvec_x", "rvec_y", "rvec_z",
    "tvec_x", "tvec_y", "tvec_z",
    "length_m", "image_path", "device_id",
]

_DICTS = {
    "4x4_50": "DICT_4X4_50", "4x4_100": "DICT_4X4_100",
    "5x5_50": "DICT_5X5_50", "5x5_100": "DICT_5X5_100",
    "6x6_50": "DICT_6X6_50", "6x6_100": "DICT_6X6_100",
    "7x7_50": "DICT_7X7_50", "7x7_100": "DICT_7X7_100",
}


@dataclass
class Detection:
    marker_id: int
    corners: Any  # (1, 4, 2) float32, as cv2.aruco returns it


@dataclass
class Pose:
    rvec: Any
    tvec: Any


@dataclass
class FrameResult:
    detections: list[Detection]
    poses: dict[int, Pose]
    rows: list[list] = field(default_factory=list)


def get_dict(name: str):
    """ArUco dictionary by name ("4x4_50", "DICT_4X4_50"); unknown names fall back to 4x4_50."""
    key = (name or "").strip()
    if key.upper().startswith("DICT_"):
        key = key[5:]
    code = getattr(cv2.aruco, _DICTS.get(key.lower(), "DICT_4X4_50"))
    if hasattr(cv2.aruco, "getPredefinedDictionary"):
        return cv2.aruco.getPredefinedDictionary(code)
    return cv2.aruco.Dictionary_get(code)


def make_params():
    if hasattr(cv2.aruco, "DetectorParameters_create"):
        return cv2.aruco.DetectorParameters_create()
    return cv2.aruco.DetectorParameters()


def vec3(vec) -> list[float]:
    if vec is None:
        return [float("nan")] * 3
    a = np.array(vec).reshape(-1).tolist()
    if len(a) < 3:
        a += [float("nan")] * (3 - len(a))
    return a[:3]


def map_tvec_axes(tvec_xyz):
    # The Pi publishes the camera-frame translation as (y, z, x); kept as is.
    x, y, z = tvec_xyz
    return [y, z, x]


def build_row(device_id, frame_idx, capture_time, recorded_at, marker_id, rvec, tvec, length_m, image_path) -> list:
    capture_value = float("nan") if capture_time is None else float(capture_time)
    return [
        frame_idx,
        f"{capture_value:.6f}",
        f"{recorded_at:.6f}", marker_id,
        *vec3(rvec), *map_tvec_axes(vec3(tvec)),
        length_m,
        image_path if image_path is not None else "",
        device_id,
    ]


def row_to_csv_line(row) -> str:
    buf = io.StringIO()
    csv.writer(buf).writerow(row)
    return buf.getvalue().strip()


class CameraPipeline:
    """Detection + pose for one camera, configured from its retained config message."""

    def __init__(self, config: dict):
        self.device_id = str(config["device_id"])
        self.camera_name = str(config["camera_name"])
        self.label = device_label(self.device_id, self.camera_name)
        self.client_type = str(config.get("client_type") or "camera").lower()
        self.output_topic = f"{self.client_type}/{self.label}"

        self.K = np.asarray(config["camera_matrix"], dtype=np.float64).reshape(3, 3)
        self.dist = np.asarray(config["dist_coeffs"], dtype=np.float64).reshape(1, -1)
        self.marker_length_m = float(config["marker_length_m"])
        lengths = config.get("marker_lengths_m") or {}
        self.marker_lengths_m = {int(k): float(v) for k, v in lengths.items()} or None
        targets = config.get("target_ids")
        self.target_ids = {int(t) for t in targets} if targets else None
        self.aruco_dict = str(config.get("aruco_dict") or "4x4_50")

        dictionary = get_dict(self.aruco_dict)
        params = make_params()
        detector = cv2.aruco.ArucoDetector(dictionary, params) if hasattr(cv2.aruco, "ArucoDetector") else None
        self._detector_state = (dictionary, params, detector)

    # --- detection + pose (camera_fusion.detect, PnPLocalize) ---

    def detect(self, image) -> list[Detection]:
        dictionary, params, detector = self._detector_state
        if detector is not None:
            corners, ids, _rej = detector.detectMarkers(image)
        else:
            corners, ids, _rej = cv2.aruco.detectMarkers(image, dictionary, parameters=params)
        if ids is None or len(ids) == 0:
            return []
        return [Detection(int(mid), corners[i]) for i, mid in enumerate(ids.flatten())]

    def _single_marker_pose(self, corners, marker_length: float):
        estimate_fn = getattr(cv2.aruco, "estimatePoseSingleMarkers", None)
        if estimate_fn is not None:
            rvec, tvec, _ = estimate_fn([corners], marker_length, self.K, self.dist)
            return rvec[0], tvec[0]

        half = marker_length / 2.0
        object_points = np.array(
            [[-half, half, 0.0], [half, half, 0.0], [half, -half, 0.0], [-half, -half, 0.0]],
            dtype=np.float32,
        )
        image_points = np.asarray(corners, dtype=np.float32).reshape(4, 2)
        flag = getattr(cv2, "SOLVEPNP_IPPE_SQUARE", cv2.SOLVEPNP_ITERATIVE)
        ok, rvec, tvec = cv2.solvePnP(object_points, image_points, self.K, self.dist, flags=flag)
        if not ok:
            return None, None
        return rvec.reshape(1, 3), tvec.reshape(1, 3)

    def _length_for(self, marker_id: int) -> float:
        if self.marker_lengths_m and marker_id in self.marker_lengths_m:
            return self.marker_lengths_m[marker_id]
        return self.marker_length_m

    def estimate_poses(self, dets: list[Detection]) -> dict[int, Pose]:
        # PnPLocalize.estimate / estimate_with_lengths: markers with no usable
        # length (or a failed solve) get no pose, and their row has NaNs.
        if not dets:
            return {}
        if not self.marker_lengths_m and self.marker_length_m <= 0:
            return {}
        poses: dict[int, Pose] = {}
        for det in dets:
            length = self._length_for(det.marker_id)
            if length <= 0:
                continue
            rvec, tvec = self._single_marker_pose(det.corners, length)
            if rvec is not None and tvec is not None:
                poses[det.marker_id] = Pose(rvec, tvec)
        return poses

    # --- one frame ---

    @staticmethod
    def decode(jpeg: bytes):
        return cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)

    def process(self, image, frame_idx: int, capture_time_ms: int | None,
                image_path: str | None = None, recorded_at: float | None = None) -> FrameResult:
        dets = self.detect(image)
        poses = self.estimate_poses(dets)
        capture_time = None if capture_time_ms is None else capture_time_ms / 1000.0
        recorded_at = time.time() if recorded_at is None else recorded_at

        result = FrameResult(dets, poses)
        for det in dets:
            if self.target_ids is not None and det.marker_id not in self.target_ids:
                continue
            pose = poses.get(det.marker_id)
            result.rows.append(build_row(
                self.device_id, frame_idx, capture_time, recorded_at, det.marker_id,
                pose.rvec if pose else None, pose.tvec if pose else None,
                self._length_for(det.marker_id), image_path,
            ))
        return result

    def annotate(self, image, frame_idx: int, result: FrameResult):
        """The Pi's annotated copy: frame label, marker outlines and ids, pose axes."""
        draw = image.copy()
        h, w = draw.shape[:2]
        txt = f"#{frame_idx} {time.strftime('%Y-%m-%dT%H:%M:%S')} {w}x{h}"
        cv2.putText(draw, txt, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2, cv2.LINE_AA)
        color = (0, 255, 0)
        for det in result.detections:
            corners_int = det.corners.astype(np.int32)
            cv2.polylines(draw, [corners_int], True, color, 2)
            center = corners_int.reshape(-1, 2).mean(axis=0)
            cv2.putText(draw, str(det.marker_id), (int(center[0]), int(center[1])),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2, cv2.LINE_AA)
        for det in result.detections:
            pose = result.poses.get(det.marker_id)
            if pose is None:
                continue
            try:
                cv2.drawFrameAxes(draw, self.K, self.dist, pose.rvec, pose.tvec,
                                  max(0.01, self.marker_length_m * 0.5))
            except cv2.error:
                pass
        return draw
