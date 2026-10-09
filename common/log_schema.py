# The one log record shape shared by every AMS service (see
# plans/dashboard-decouple-plan.md §G). Services write these to stdout as one
# JSON object per line, so `docker logs` is both human-readable and parseable by
# stack-controller's /logs reader.
#
# level    -- severity, Python's numbers (10 DEBUG ... 50 CRITICAL), set when written
# priority -- how urgently a person must act; reserved, always None until a
#             policy is added in classify()

import json
import logging
import os
import socket
import threading
from datetime import datetime, timezone
from typing import Any

CATEGORIES = ("health", "session", "ingest", "backup", "deploy", "watchdog", "system", "other")

# Which service wrote the record -- compose sets SERVICE_NAME per container
SOURCE = os.getenv("SERVICE_NAME") or socket.gethostname()

_seq = 0
_seq_lock = threading.Lock()


def _next_seq() -> int:
    global _seq
    with _seq_lock:
        _seq += 1
        return _seq


def make_record(
    message: str,
    level: int = logging.INFO,
    logger: str = "system",
    category: str = "system",
    important: bool = False,
    context: dict[str, Any] | None = None,
    ts: datetime | None = None,
    source: str | None = None,
    priority: int | None = None,
) -> dict[str, Any]:
    ts = ts or datetime.now(timezone.utc)
    source = source or SOURCE
    record = {
        "id": f"{source}:{ts.isoformat()}:{_next_seq()}",
        "ts": ts.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "source": source,
        "logger": logger,
        "level": level,
        "level_name": logging.getLevelName(level),
        "priority": priority,
        "category": category if category in CATEGORIES else "other",
        "important": important,
        "message": message,
        "context": context or {},
    }
    return classify(record)


# Hook for a future priority policy: rank a record by how urgently a person
# must act on it (e.g. "db down while a session is recording"). No-op today.
def classify(record: dict[str, Any]) -> dict[str, Any]:
    return record


# Formats stdlib logging records as one JSON LogRecord per line. Callers can
# pass extra={"category": ..., "important": ..., "context": {...}}; the logger
# name comes from the record's smr_logger attribute (see fast_server/loggers.py)
class JsonLineFormatter(logging.Formatter):

    def format(self, record: logging.LogRecord) -> str:
        message = record.getMessage()
        if record.exc_info:
            message = f"{message}\n{self.formatException(record.exc_info)}"

        data = make_record(
            message,
            level=record.levelno,
            logger=getattr(record, "smr_logger", record.name),
            category=getattr(record, "category", "system"),
            important=bool(getattr(record, "important", False)),
            context=getattr(record, "context", None),
            ts=datetime.fromtimestamp(record.created, tz=timezone.utc),
        )
        return json.dumps(data, default=str)
