import atexit
import logging
import os
import queue
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from common.log_schema import JsonLineFormatter

cur_camera_logger: logging.Logger | None = None
cur_imu_logger: logging.Logger | None = None
cur_robot_logger: logging.Logger | None = None
system_logger: logging.Logger | None = None
system_logger_date = None

# NFS-mounted in compose (fastapi-app: /fast_server/logs, tcp: /tcp-server/logs)
LOG_DIR = Path(os.getenv("LOG_DIR", "/fast_server/logs"))

formatter = logging.Formatter(
    fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

# Everything that reaches stdout is one JSON LogRecord per line, so `docker logs`
# always has the story (even with the NAS down) and the dashboard can parse it
_stdout_handler = logging.StreamHandler(sys.stdout)
_stdout_handler.setFormatter(JsonLineFormatter())

# Reports the file writer's own trouble -- stdout only, it can't log to the files
_status_logger = logging.getLogger("smr_log_writer")
_status_logger.addHandler(_stdout_handler)
_status_logger.addFilter(lambda record: setattr(record, "smr_logger", "logs") or True)
_status_logger.setLevel(logging.INFO)
_status_logger.propagate = False


# Writes log files on one background thread, so a slow or hung NFS mount can
# never block the event loop. Lines are dropped (and counted) rather than
# queued without bound while the log directory is unreachable.
class _FileWriter:
    MAX_OPEN_FILES = 16

    def __init__(self, maxsize: int = 10000):
        self.queue: queue.Queue = queue.Queue(maxsize=maxsize)
        self.files: dict[Path, Any] = {}
        self.ok = True
        self.error: str | None = None
        self.since: float | None = None
        self.dropped = 0
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def submit(self, path: Path, line: str) -> None:
        self._ensure_thread()
        try:
            self.queue.put_nowait((path, line))
        except queue.Full:
            self.dropped += 1

    def status(self) -> dict[str, Any]:
        return {"ok": self.ok, "error": self.error, "since": self.since,
                "dropped": self.dropped, "dir": str(LOG_DIR)}

    def flush(self, timeout: float = 2.0) -> None:
        deadline = time.monotonic() + timeout
        while not self.queue.empty() and time.monotonic() < deadline:
            time.sleep(0.05)

    def _ensure_thread(self) -> None:
        if self._thread is None:
            with self._lock:
                if self._thread is None:
                    self._thread = threading.Thread(target=self._run, name="log-file-writer", daemon=True)
                    self._thread.start()

    def _open(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        if len(self.files) >= self.MAX_OPEN_FILES:
            self._close(next(iter(self.files)))
        f = self.files[path] = open(path, "a", encoding="utf-8")
        return f

    def _close(self, path: Path) -> None:
        f = self.files.pop(path, None)
        if f is not None:
            try:
                f.close()
            except OSError:
                pass

    def _run(self) -> None:
        while True:
            path, line = self.queue.get()
            try:
                f = self.files.get(path) or self._open(path)
                f.write(line + "\n")
                f.flush()
            except OSError as e:
                self._close(path)
                self.dropped += 1
                if self.ok:
                    self.ok, self.error, self.since = False, str(e), time.time()
                    _status_logger.error(f"Log files unavailable in {LOG_DIR}, logging to stdout only: {e}",
                                         extra={"category": "health", "important": True,
                                                "context": {"component": "logs"}})
                continue

            if not self.ok:
                down_for = time.time() - (self.since or time.time())
                _status_logger.info(f"Log files writable again in {LOG_DIR} after {down_for:.0f}s "
                                    f"({self.dropped} lines dropped so far)",
                                    extra={"category": "health", "important": True,
                                           "context": {"component": "logs", "dropped": self.dropped}})
                self.ok, self.error, self.since = True, None, None


_writer = _FileWriter()
atexit.register(_writer.flush)


class NonBlockingFileHandler(logging.Handler):

    def __init__(self, path: Path):
        super().__init__()
        self.path = path

    def emit(self, record: logging.LogRecord) -> None:
        try:
            _writer.submit(self.path, self.format(record))
        except Exception:
            self.handleError(record)


# Tags records with the short logger name ("system", "imu", ...) for the JSON output
class _NameTag(logging.Filter):

    def __init__(self, short_name: str):
        super().__init__()
        self.short_name = short_name

    def filter(self, record: logging.LogRecord) -> bool:
        record.smr_logger = self.short_name
        return True


# Creates a timestamped logger writing to its own file in LOG_DIR. Records at
# stdout_level or above also go to stdout.
def create_logger(name, stdout_level=logging.WARNING):

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    logger = logging.getLogger(f"{name}_{timestamp}_utc")

    if not logger.handlers:
        file_handler = NonBlockingFileHandler(LOG_DIR / f"{name}_{timestamp}.log")
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

        stdout_handler = logging.StreamHandler(sys.stdout)
        stdout_handler.setFormatter(JsonLineFormatter())
        stdout_handler.setLevel(stdout_level)
        logger.addHandler(stdout_handler)

        logger.addFilter(_NameTag(name.removesuffix("_logger")))
        logger.setLevel(logging.DEBUG)
        logger.propagate = False

    return logger

# Creates a system logger -- Created on system turned on or refresh if new day occurred
def create_system_logger() -> None:
    global system_logger, system_logger_date

    utc_date = datetime.now(timezone.utc).strftime("%Y%m%d")

    # Recreate logger if date changes
    if system_logger is None or system_logger_date != utc_date:
        system_logger_date = utc_date
        # Everything the system logger writes also goes to stdout
        system_logger = create_logger("system_logger", stdout_level=logging.DEBUG)

        system_logger.info(f"Created new system logger for {utc_date}")

# Helper method to access loggers and add information to them
def log_system_logger(msg: str, is_error: bool = False) -> None:
    create_system_logger()

    if is_error:
        system_logger.error(msg)
    else:
        system_logger.info(msg)

# Records an event a person should notice (dependency down/up, session
# start/stop, backups, dropped data...). Shows in the dashboard's "Important"
# log tab; extra keyword arguments land in the record's context.
def log_event(msg: str, category: str = "system", level: int = logging.INFO,
              important: bool = True, **context: Any) -> None:
    create_system_logger()
    system_logger.log(level, msg, extra={"category": category, "important": important, "context": context})

# Whether log files are currently being written, for the health report
def file_logging_status() -> dict[str, Any]:
    return _writer.status()


def create_loggers() -> None:
    global cur_camera_logger, cur_imu_logger, cur_robot_logger

    cur_camera_logger = create_logger("camera_logger")
    cur_imu_logger = create_logger("imu_logger")
    cur_robot_logger = create_logger("robot_logger")
