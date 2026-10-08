import time
from dataclasses import dataclass
from enum import Enum
from typing import Any


# What happens to incoming device data. fastapi-app owns the real state and
# pushes a copy to tcp_server (PUT /capture), which also re-syncs from
# GET /capture -- see plans/listener-switch-plan.md.
class CaptureMode(str, Enum):
    IDLE = "idle"          # nothing listened to or stored
    MONITOR = "monitor"    # live view only, nothing stored
    RECORD = "record"      # session open, data stored
    STOPPING = "stopping"  # gate closed, last batches draining


# Device keys mirror the MQTT topic: "imu/<id>", "camera/<id>", "robot/main"
def device_key(category: str, device_label: str) -> str:
    return f"{category}/{device_label}"


@dataclass
class CaptureState:
    mode: CaptureMode = CaptureMode.IDLE
    session_id: int | None = None
    # None = every device; otherwise only these device keys are accepted
    devices: set[str] | None = None
    # Bumped on every change so a stale copy (e.g. a slow re-sync in
    # tcp_server) never overwrites a newer one. Seeded from wall-clock ms so
    # it keeps increasing across fastapi-app restarts.
    version: int = 0

    def is_listening(self) -> bool:
        return self.mode in (CaptureMode.MONITOR, CaptureMode.RECORD)

    def accepts(self, category: str, device_label: str) -> bool:
        if not self.is_listening():
            return False
        return self.devices is None or device_key(category, device_label) in self.devices

    def should_store(self) -> bool:
        return self.mode == CaptureMode.RECORD

    # True if a queued item was captured for the session still being stored/drained.
    # Items from an ended session are dropped instead of landing in the next one.
    def is_current(self, item: dict[str, Any]) -> bool:
        return (
            self.mode in (CaptureMode.RECORD, CaptureMode.STOPPING)
            and item.get("session_id") is not None
            and item.get("session_id") == self.session_id
        )

    def set(self, mode: CaptureMode, session_id: int | None = None, devices: set[str] | None = None) -> None:
        self.mode = mode
        self.session_id = session_id
        self.devices = devices
        self.version = max(self.version + 1, time.time_ns() // 1_000_000)

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode.value,
            "session_id": self.session_id,
            "devices": sorted(self.devices) if self.devices is not None else None,
            "version": self.version,
        }

    # Applies a copy received from fastapi-app; returns False if it was stale
    # or one we already have
    def apply(self, data: dict[str, Any]) -> bool:
        version = int(data.get("version", 0))
        if version <= self.version:
            return False

        devices = data.get("devices")
        self.mode = CaptureMode(data["mode"])
        self.session_id = data.get("session_id")
        self.devices = set(devices) if devices is not None else None
        self.version = version
        return True


# Throttles live dashboard samples to one per device per interval, so a 100 Hz
# IMU doesn't flood the WebSockets. Counts what arrived in between so each
# sample can report the device's message rate.
class LiveSampler:

    def __init__(self, interval_s: float = 1.0):
        self.interval_s = interval_s
        self._last: dict[str, float] = {}
        self._count: dict[str, int] = {}

    # Records one message for key; returns its rate (msg/s) if a sample is due
    # now, else None. The first message from a device is always sampled.
    def tick(self, key: str, now: float | None = None) -> float | None:
        now = time.monotonic() if now is None else now
        self._count[key] = self._count.get(key, 0) + 1

        last = self._last.get(key)
        if last is not None and now - last < self.interval_s:
            return None

        elapsed = now - last if last is not None else 0.0
        count = self._count[key]
        self._last[key] = now
        self._count[key] = 0
        return count / elapsed if elapsed > 0 else 0.0

    # "12 msg/s", or "first sample" when there's no previous sample to measure from
    @staticmethod
    def describe_rate(rate: float) -> str:
        return f"{rate:.0f} msg/s" if rate > 0 else "first sample"

    def reset(self) -> None:
        self._last.clear()
        self._count.clear()


# Splits a worker's batch into items still belonging to the current capture
# session and the stale ones to drop.
def split_current(state: CaptureState, batch: list[dict[str, Any]]) -> tuple[list, list]:
    current, stale = [], []
    for item in batch:
        (current if state.is_current(item) else stale).append(item)
    return current, stale
