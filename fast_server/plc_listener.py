"""
Watches tags on the robot cell's PLC (an Allen-Bradley 1769-L32E, read over
EtherNet/IP with pycomm3) so fastapi-app can react to them. Today that's one
tag: Db_Stop, which the PLC pulses briefly when the robot finishes its move,
and which stops the recording session (plc_supervisor in main.py).

Ported from PLCSignalWatcher in the IMU edge node repo
(wku-smr-lab-imu-edge-node, imu_edge/plc_signals.py, plc_update branch), with
the tag list as a parameter instead of a fixed start/tare/stop triple.

The PLC doesn't push anything, so the tags are polled. A pulse is short, so
the watcher counts each time a tag turns ON (a rising edge) instead of
looking at whether it is on right now; callers compare count() with the
count they saw last. A tag turning OFF again is ignored. pycomm3 is blocking,
so the polling runs in a background thread -- a hung PLC connection can't
stall the event loop.
"""
import threading
import time
from collections import namedtuple
from typing import Any, Callable

FakeTag = namedtuple("FakeTag", "tag value type error")


class FakePLC:
    """
    Stand-in for pycomm3's LogixDriver, for testing without the robot. Plays
    back a timeline of (seconds, tag, value) -- by default one Db_Stop pulse.
    """

    DEFAULT_TIMELINE = [
        (20.0, "Db_Stop", 1),   # robot finished: short pulse
        (21.0, "Db_Stop", 0),
    ]

    def __init__(self, timeline=None, speed: float = 1.0, **_ignored):
        self.timeline = sorted(timeline or self.DEFAULT_TIMELINE)
        self.speed = speed
        self._t0 = time.monotonic()

    def __enter__(self):
        self._t0 = time.monotonic()
        return self

    def __exit__(self, *exc):
        return False

    def read(self, *tags):
        elapsed = (time.monotonic() - self._t0) * self.speed
        state = {tag: 0 for _at, tag, _value in self.timeline}
        for at, tag, value in self.timeline:
            if elapsed >= at:
                state[tag] = value

        results = [
            FakeTag(tag, state[tag], "DINT", None)
            if tag in state
            else FakeTag(tag, None, None, "Tag doesn't exist")
            for tag in tags
        ]
        return results[0] if len(results) == 1 else results


def build_plc_factory(path: str, fake: bool = False, fake_speed: float = 1.0) -> Callable:
    """Return a function that opens a connection to the PLC (or the stand-in)."""
    if fake:
        return lambda: FakePLC(speed=fake_speed)

    def _open_real():
        # Imported here so pycomm3 is only needed when the PLC listener is on
        from pycomm3 import LogixDriver

        return LogixDriver(path, init_connection=False, large_packets=False)

    return _open_real


class PLCSignalWatcher:
    def __init__(
        self,
        plc_factory: Callable,
        tags: tuple[str, ...],
        poll_s: float = 0.05,
        retry_delay_s: float = 1.0,
    ):
        self._plc_factory = plc_factory
        self._tags = tuple(tags)
        self._poll_s = poll_s
        self._retry_delay_s = retry_delay_s

        self._lock = threading.Lock()
        # How many times each tag has turned ON since the watcher started
        self._counts = {tag: 0 for tag in self._tags}
        # The value each tag had at the last good read
        self._values = {tag: False for tag in self._tags}
        self._connected = False
        # Connection problem (PLC unreachable) vs. a tag the PLC doesn't know
        self._last_error: str | None = None
        self._tag_errors: str | None = None
        self._last_read_at: float | None = None

        self._closing = threading.Event()
        self._thread = threading.Thread(target=self._run, name="plc-signals", daemon=True)

    @property
    def tags(self) -> tuple[str, ...]:
        return self._tags

    def start(self) -> None:
        self._thread.start()

    def close(self) -> None:
        self._closing.set()
        self._thread.join(timeout=5)

    def count(self, tag: str) -> int:
        """How many times this tag has turned ON. A 1 s pulse counts once."""
        with self._lock:
            return self._counts[tag]

    @property
    def connected(self) -> bool:
        with self._lock:
            return self._connected

    @property
    def last_error(self) -> str | None:
        with self._lock:
            return self._last_error

    @property
    def tag_errors(self) -> str | None:
        with self._lock:
            return self._tag_errors

    def snapshot(self) -> dict[str, Any]:
        """Current state, for /health and log messages."""
        with self._lock:
            return {
                "connected": self._connected,
                "values": {tag: int(self._values[tag]) for tag in self._tags},
                "counts": dict(self._counts),
                "last_read_age_s": round(time.monotonic() - self._last_read_at, 1) if self._last_read_at else None,
            }

    @staticmethod
    def _as_bool(result) -> bool:
        # The lab PLC's tags are DINTs, so anything non-zero counts as ON
        return bool(result.value) if result.error is None else False

    def _run(self) -> None:
        first_read = True
        while not self._closing.is_set():
            try:
                with self._plc_factory() as plc:
                    with self._lock:
                        self._connected = True
                        self._last_error = None

                    while not self._closing.is_set():
                        results = plc.read(*self._tags)
                        # pycomm3 returns a bare Tag (itself a NamedTuple, so
                        # not a list) for a single tag
                        if not isinstance(results, list):
                            results = [results]
                        errors = [f"{r.tag}: {r.error}" for r in results if r.error]

                        with self._lock:
                            for tag, result in zip(self._tags, results):
                                value = self._as_bool(result)
                                # A tag that is already ON when the watcher
                                # starts is not counted: only a fresh OFF->ON
                                # change counts
                                if value and not self._values[tag] and not first_read:
                                    self._counts[tag] += 1
                                self._values[tag] = value
                            self._tag_errors = "; ".join(errors) or None
                            self._last_read_at = time.monotonic()
                        first_read = False

                        self._closing.wait(self._poll_s)
            except Exception as error:  # connection lost or refused: retry
                # Pulses that arrive while disconnected are missed; the last
                # known values are kept so no false edge is seen on reconnect.
                with self._lock:
                    self._connected = False
                    self._last_error = str(error) or type(error).__name__
                self._closing.wait(self._retry_delay_s)
