# Per-run files the camera Pi used to keep under /opt/camera-sensor-fusion/data:
# one session folder per run (per PLC run when recording, per deploy when
# monitoring) with the raw frames, annotated frames and detections.csv.
#
#   <CAMERA_DATA_ROOT>/<device>/<camera_name>_session_<YYYYmmdd_HHMMSS>[_n]/
#       config.json        run id + the camera config the Pi sent
#       detections.csv     the rows published to camera/<device>
#       frames/f000000.jpg the JPEG exactly as the Pi sent it
#       annotated/f000000_aruco.jpg   only frames with a marker

from __future__ import annotations

import csv
import json
import logging
import time
from pathlib import Path

import cv2

from .pipeline import CSV_HEADER

log = logging.getLogger("camera_processor.storage")


class RunFolder:
    def __init__(self, root: Path, label: str, camera_name: str, run_id: str, manifest: dict,
                 save_frames: bool, save_annotated: bool, save_csv: bool):
        self.root = root
        self.run_id = run_id
        self.save_frames = save_frames
        self.save_annotated = save_annotated
        self._csv_fh = None
        self._csv = None
        self.errors = 0

        base = root / label
        stamp = time.strftime("%Y%m%d_%H%M%S")
        path = base / f"{camera_name}_session_{stamp}"
        n = 2
        while path.exists():  # back-to-back runs within one second
            path = base / f"{camera_name}_session_{stamp}_{n}"
            n += 1
        self.path = path
        self.frames_dir = path / "frames"
        self.annotated_dir = path / "annotated"

        try:
            for d in (self.frames_dir, self.annotated_dir):
                d.mkdir(parents=True, exist_ok=True)
            (path / "config.json").write_text(json.dumps({"run_id": run_id, **manifest}, indent=2, default=str))
            if save_csv:
                self._csv_fh = open(path / "detections.csv", "w", newline="")
                self._csv = csv.writer(self._csv_fh)
                self._csv.writerow(CSV_HEADER)
        except OSError as error:
            self._error("could not create run folder", error)
            self.save_frames = self.save_annotated = False

    def _error(self, what: str, error: Exception) -> None:
        self.errors += 1
        # One warning per run folder, not one per frame.
        if self.errors == 1:
            log.warning("%s in %s: %s (further errors for this run are counted, not logged)",
                        what, self.path, error)

    def relative(self, path: Path) -> str:
        try:
            return str(path.relative_to(self.root))
        except ValueError:
            return str(path)

    def frame_path(self, frame_idx: int) -> Path:
        return self.frames_dir / f"f{frame_idx:06d}.jpg"

    def write_frame(self, frame_idx: int, jpeg: bytes) -> str | None:
        if not self.save_frames:
            return None
        path = self.frame_path(frame_idx)
        try:
            path.write_bytes(jpeg)
        except OSError as error:
            self._error("could not save frame", error)
            return None
        return self.relative(path)

    def write_annotated(self, frame_idx: int, image) -> None:
        if not self.save_annotated:
            return
        try:
            if not cv2.imwrite(str(self.annotated_dir / f"f{frame_idx:06d}_aruco.jpg"), image):
                raise OSError("cv2.imwrite returned False")
        except (OSError, cv2.error) as error:
            self._error("could not save annotated frame", error)

    def write_rows(self, rows) -> None:
        if self._csv is None or not rows:
            return
        try:
            self._csv.writerows(rows)
            self._csv_fh.flush()
        except OSError as error:
            self._error("could not write detections.csv", error)

    def close(self) -> None:
        if self._csv_fh is not None:
            try:
                self._csv_fh.close()
            except OSError:
                pass
            self._csv_fh = self._csv = None
