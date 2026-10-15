# Turns raw `docker logs --timestamps` lines from any AMS container into
# LogRecords (common/log_schema.py). Our own services already write JSON
# records; third-party containers (nginx, mosquitto, pgadmin, ntp, uvicorn's
# own lines) get a level from one per-format pattern each. Python tracebacks
# are folded into the record they belong to, and credentials are masked
# before anything leaves this process.

import hashlib
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Iterable

from common.log_schema import make_record

# "2026-10-09T14:38:39.123456789Z rest of line"
DOCKER_TS = re.compile(r"^(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(?:\.(\d+))?Z\s?(.*)$", re.S)

NAMES = {
    "debug": logging.DEBUG, "info": logging.INFO, "notice": logging.INFO,
    "warn": logging.WARNING, "warning": logging.WARNING,
    "error": logging.ERROR, "err": logging.ERROR, "crit": logging.CRITICAL, "critical": logging.CRITICAL,
    "alert": logging.CRITICAL, "emerg": logging.CRITICAL, "fatal": logging.CRITICAL,
}

# (name, pattern, level group, message group) -- first match wins. To support
# a new container's format, add a row.
PATTERNS = [
    # fast_server/loggers.py text format: "2026-10-09 14:38:39 [ERROR] name: msg"
    ("smr-text", re.compile(r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d \[(\w+)\] [^:]+: (.*)$", re.S), 1, 2),
    # uvicorn / python logging defaults: "ERROR:    Application startup failed."
    ("uvicorn", re.compile(r"^(DEBUG|INFO|WARNING|ERROR|CRITICAL):\s+(.*)$", re.S), 1, 2),
    # nginx error log: "2026/10/09 13:45:28 [emerg] 1#1: host not found ..."
    ("nginx-error", re.compile(r"^\d{4}/\d\d/\d\d \d\d:\d\d:\d\d \[(\w+)\] \d+#\d+: (.*)$", re.S), 1, 2),
    # gunicorn (pgadmin): "[2026-10-09 14:38:39 +0000] [1] [INFO] Booting worker"
    ("gunicorn", re.compile(r"^\[[^\]]+\] \[\d+\] \[(\w+)\] (.*)$", re.S), 1, 2),
    # nginx entrypoint: "/docker-entrypoint.sh: Configuration complete"
    ("entrypoint", re.compile(r"^(/docker-entrypoint[^:]*): (.*)$", re.S), None, 2),
    # mosquitto: "1791556719: mosquitto version 2.0.18 running"
    ("mosquitto", re.compile(r"^\d{9,}: (.*)$", re.S), None, 1),
]

# nginx access log: '1.2.3.4 - - [09/Oct/2026:14:38:39 +0000] "GET / HTTP/1.1" 200 ...'
NGINX_ACCESS = re.compile(r'^\S+ - \S+ \[[^\]]+\] "[^"]*" (\d{3}) ')

KEYWORD_LEVELS = [
    (re.compile(r"\b(fatal|panic|critical)\b", re.I), logging.CRITICAL),
    (re.compile(r"\b(error|exception|traceback|failed|failure|refused)\b", re.I), logging.ERROR),
    (re.compile(r"\bwarn(ing)?\b", re.I), logging.WARNING),
]

REDACTIONS = [
    (re.compile(r"(?i)(password|passwd|pgpassword|secret|token)(\s*[=:]\s*|\"\s*:\s*\")([^\s\"',;&]+)"), r"\1\2***"),
    (re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+"), r"\1***"),
    (re.compile(r"(?i)(postgres(?:ql)?://[^:/\s]+:)[^@\s]+@"), r"\1***@"),
]


def redact(text: str) -> str:
    for pattern, replacement in REDACTIONS:
        text = pattern.sub(replacement, text)
    return text


def guess_level(text: str) -> int:
    for pattern, level in KEYWORD_LEVELS:
        if pattern.search(text):
            return level
    return logging.INFO


def parse_docker_ts(line: str) -> tuple[datetime | None, str, str]:
    """Returns (time, raw timestamp string, text) for one docker logs line."""
    m = DOCKER_TS.match(line)
    if not m:
        return None, "", line
    whole, frac, text = m.groups()
    micros = int((frac or "0")[:6].ljust(6, "0"))
    ts = datetime.strptime(whole, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc, microsecond=micros)
    return ts, f"{whole}.{frac or '0'}Z", text


def _from_json(text: str, source: str) -> dict[str, Any] | None:
    if not text.startswith("{"):
        return None
    try:
        data = json.loads(text)
    except ValueError:
        return None
    if not isinstance(data, dict) or "message" not in data or "level" not in data:
        return None
    # Always the compose service name, so it matches the dashboard's source
    # filter even if the producer didn't know its own name (SERVICE_NAME unset)
    data["source"] = source
    data.setdefault("priority", None)
    data.setdefault("context", {})
    data.setdefault("important", False)
    data["message"] = redact(str(data["message"]))
    return data


def normalize_line(source: str, ts: datetime | None, raw_ts: str, text: str) -> dict[str, Any]:
    """One docker log line -> LogRecord. JSON records from our services pass through."""
    text = text.rstrip("\n")
    record = _from_json(text, source)
    if record is not None:
        return record

    level = None
    message = text
    for _name, pattern, level_group, message_group in PATTERNS:
        m = pattern.match(text)
        if m:
            if level_group:
                level = NAMES.get(m.group(level_group).lower())
            message = m.group(message_group)
            break
    else:
        access = NGINX_ACCESS.match(text)
        if access:
            status = int(access.group(1))
            level = logging.ERROR if status >= 500 else logging.WARNING if status >= 400 else logging.INFO

    if level is None:
        level = guess_level(message)

    digest = hashlib.sha1(text.encode("utf-8", "replace")).hexdigest()[:8]
    record = make_record(redact(message), level=level, logger=source, category="other",
                         important=False, ts=ts, source=source)
    record["id"] = f"{source}:{raw_ts or record['ts']}:{digest}"
    return record


def _continues_traceback(text: str, in_traceback: bool) -> bool:
    if text.startswith("Traceback (most recent call last)"):
        return True
    if not in_traceback:
        return False
    # Indented frames/source lines, blank separators, and the final
    # "SomeError: message" line all belong to the traceback
    return text.startswith((" ", "\t")) or text == "" or bool(re.match(r"^[\w.]+(Error|Exception|Exit|Interrupt|Warning)\b", text)) \
        or text.startswith(("During handling", "The above exception"))


def normalize_lines(source: str, lines: Iterable[str]) -> list[dict[str, Any]]:
    """docker logs --timestamps output for one container -> LogRecords, oldest first."""
    records: list[dict[str, Any]] = []
    in_traceback = False
    last_ts: datetime | None = None

    for line in lines:
        ts, raw_ts, text = parse_docker_ts(line.rstrip("\n"))
        # Only fold into a record written moments earlier, never one from minutes ago
        recent = last_ts is None or ts is None or (ts - last_ts).total_seconds() <= 2
        if records and recent and _continues_traceback(text, in_traceback) and not text.startswith("{"):
            prev = records[-1]
            prev["message"] = f"{prev['message']}\n{redact(text)}"
            prev["level"] = max(prev["level"], logging.ERROR)
            prev["level_name"] = logging.getLevelName(prev["level"])
            in_traceback = True
            continue
        if not text.strip():
            in_traceback = False
            continue
        records.append(normalize_line(source, ts, raw_ts, text))
        last_ts = ts
        # A traceback that starts its own record still collects the lines after it
        in_traceback = text.startswith("Traceback (most recent call last)")

    return records
