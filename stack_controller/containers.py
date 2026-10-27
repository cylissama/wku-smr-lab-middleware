# Container health for the dashboard's Container Health and Logs boxes, plus
# the watchdog that restarts unhealthy containers (plain compose only reports
# "unhealthy", it never acts on it). Only containers labelled smr.monitor=true
# are visible here, and only smr.autoheal=true ones are ever restarted.
# See plans/completed/dashboard-decouple-plan.md §D and §G.

import asyncio
import logging
import os
import re
import sys
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Any

import docker
from docker.errors import DockerException

from common.log_schema import JsonLineFormatter
from stack_controller.log_normalize import normalize_lines

MONITOR_LABEL = "smr.monitor"
AUTOHEAL_LABEL = "smr.autoheal"

WATCHDOG_INTERVAL = float(os.getenv("WATCHDOG_INTERVAL", 30))
# At most this many watchdog restarts per container per window, then it gives up
WATCHDOG_MAX_RESTARTS = int(os.getenv("WATCHDOG_MAX_RESTARTS", 3))
WATCHDOG_WINDOW = float(os.getenv("WATCHDOG_WINDOW", 15 * 60))

CRASH_LOG_LINES = 20

# stack-controller's own events (watchdog restarts) as JSON LogRecords on stdout
_logger = logging.getLogger("stack_controller.events")
if not _logger.handlers:
    _handler = logging.StreamHandler(sys.stdout)
    _handler.setFormatter(JsonLineFormatter())
    _logger.addHandler(_handler)
    _logger.addFilter(lambda record: setattr(record, "smr_logger", "watchdog") or True)
    _logger.setLevel(logging.INFO)
    _logger.propagate = False


def log_event(msg: str, category: str = "watchdog", level: int = logging.INFO,
              important: bool = True, **context: Any) -> None:
    _logger.log(level, msg, extra={"category": category, "important": important, "context": context})


def _client() -> docker.DockerClient:
    return docker.from_env()


_DOCKER_TIME = re.compile(r"^(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(?:\.(\d+))?(Z|[+-]\d\d:\d\d)?$")


def _parse_time(value: str | None) -> float | None:
    # Docker times have nanoseconds and either "Z" or the host's offset, e.g.
    # "2026-10-09T08:57:36.391292706-05:00" (health checks); "0001-01-01..." = never
    if not value or value.startswith("0001-"):
        return None
    m = _DOCKER_TIME.match(value)
    if not m:
        return None
    whole, frac, tz = m.groups()
    micros = int((frac or "0")[:6].ljust(6, "0"))
    dt = datetime.strptime(whole, "%Y-%m-%dT%H:%M:%S").replace(microsecond=micros)
    if tz and tz != "Z":
        sign = 1 if tz[0] == "+" else -1
        offset = timedelta(hours=int(tz[1:3]), minutes=int(tz[4:6]))
        return (dt.replace(tzinfo=timezone(sign * offset))).timestamp()
    return dt.replace(tzinfo=timezone.utc).timestamp()


def monitored_containers(client: docker.DockerClient) -> list:
    return client.containers.list(all=True, filters={"label": f"{MONITOR_LABEL}=true"})


def service_name(container) -> str:
    return container.labels.get("com.docker.compose.service") or container.name


def is_crashed(state: dict[str, Any]) -> bool:
    return state.get("Status") in ("exited", "dead", "restarting", "created")


class Watchdog:

    def __init__(self):
        self.history: deque[dict[str, Any]] = deque(maxlen=50)
        self._restarts: dict[str, deque[float]] = {}
        self._gave_up: set[str] = set()

    def recent_restarts(self, name: str, now: float | None = None) -> int:
        now = now or time.time()
        stamps = self._restarts.get(name, deque())
        while stamps and now - stamps[0] > WATCHDOG_WINDOW:
            stamps.popleft()
        return len(stamps)

    def status_for(self, name: str) -> dict[str, Any]:
        return {
            "restarts": self.recent_restarts(name),
            "max_restarts": WATCHDOG_MAX_RESTARTS,
            "gave_up": name in self._gave_up,
            "events": [e for e in self.history if e["container"] == name][-5:],
        }

    def check_once(self, client: docker.DockerClient) -> None:
        now = time.time()
        for container in client.containers.list(filters={"label": f"{AUTOHEAL_LABEL}=true"}):
            name = container.name
            health = (container.attrs.get("State") or {}).get("Health") or {}

            if health.get("Status") != "unhealthy":
                # Healthy again (or not checked): it may be restarted again later
                self._gave_up.discard(name)
                continue

            last_probe = (health.get("Log") or [{}])[-1]
            reason = (last_probe.get("Output") or "").strip()[:300] or f"exit code {last_probe.get('ExitCode')}"

            if self.recent_restarts(name, now) >= WATCHDOG_MAX_RESTARTS:
                if name not in self._gave_up:
                    self._gave_up.add(name)
                    msg = (f"Giving up on {name}: still unhealthy after {WATCHDOG_MAX_RESTARTS} restarts in "
                           f"{WATCHDOG_WINDOW / 60:.0f} min -- needs a person. Last check: {reason}")
                    self._record(name, "gave_up", msg, now)
                    log_event(msg, level=logging.CRITICAL, container=name)
                continue

            try:
                container.restart(timeout=10)
            except DockerException as e:
                msg = f"Couldn't restart unhealthy {name}: {e}"
                self._record(name, "restart_failed", msg, now)
                log_event(msg, level=logging.ERROR, container=name)
                continue

            self._restarts.setdefault(name, deque()).append(now)
            msg = (f"Restarted {name} (unhealthy, {health.get('FailingStreak', '?')} failed checks; "
                   f"restart {self.recent_restarts(name, now)}/{WATCHDOG_MAX_RESTARTS}). Last check: {reason}")
            self._record(name, "restarted", msg, now)
            log_event(msg, level=logging.WARNING, container=name)

    async def run(self) -> None:
        log_event("Watchdog started", important=False, interval=WATCHDOG_INTERVAL,
                  max_restarts=WATCHDOG_MAX_RESTARTS, window=WATCHDOG_WINDOW)
        while True:
            try:
                await asyncio.to_thread(self._check_with_client)
            except Exception as e:
                log_event(f"Watchdog check failed: {type(e).__name__}: {e}", level=logging.ERROR, important=False)
            await asyncio.sleep(WATCHDOG_INTERVAL)

    def _check_with_client(self) -> None:
        client = _client()
        try:
            self.check_once(client)
        finally:
            client.close()

    def _record(self, name: str, action: str, message: str, now: float) -> None:
        self.history.append({"container": name, "action": action, "message": message, "time": now})


watchdog = Watchdog()


def describe_container(container, now: float | None = None) -> dict[str, Any]:
    now = now or time.time()
    attrs = container.attrs
    state = attrs.get("State") or {}
    health = state.get("Health")
    started = _parse_time(state.get("StartedAt"))
    finished = _parse_time(state.get("FinishedAt"))

    info: dict[str, Any] = {
        "name": container.name,
        "service": service_name(container),
        "image": (attrs.get("Config") or {}).get("Image"),
        "state": state.get("Status"),
        "running": bool(state.get("Running")),
        "exit_code": state.get("ExitCode"),
        "error": state.get("Error") or None,
        "oom_killed": bool(state.get("OOMKilled")),
        "started_at": started,
        "finished_at": finished,
        "uptime_s": round(now - started, 1) if started and state.get("Running") else None,
        "restart_count": attrs.get("RestartCount", 0),
        "autoheal": container.labels.get(AUTOHEAL_LABEL) == "true",
        "health": None,
        "watchdog": watchdog.status_for(container.name),
        "crashed": is_crashed(state),
        "logs": None,
    }

    if health:
        probes = health.get("Log") or []
        info["health"] = {
            "status": health.get("Status"),
            "failing_streak": health.get("FailingStreak", 0),
            "probes": [
                {
                    "start": _parse_time(p.get("Start")),
                    "exit_code": p.get("ExitCode"),
                    "output": (p.get("Output") or "").strip()[:500],
                }
                for p in probes[-5:]
            ],
        }

    # A crashed container's health check never runs -- its last log lines are
    # the only explanation
    if info["crashed"]:
        info["logs"] = read_records(container, tail=CRASH_LOG_LINES)

    return info


def list_containers() -> dict[str, Any]:
    client = _client()
    try:
        now = time.time()
        containers = sorted(monitored_containers(client), key=service_name)
        return {"containers": [describe_container(c, now) for c in containers], "time": now}
    finally:
        client.close()


def read_records(container, tail: int = 200, since: float | None = None) -> list[dict[str, Any]]:
    kwargs: dict[str, Any] = {"stdout": True, "stderr": True, "timestamps": True, "tail": tail}
    if since is not None:
        kwargs["since"] = since
    raw = container.logs(**kwargs).decode("utf-8", errors="replace")
    return normalize_lines(service_name(container), raw.splitlines())


def _ts_key(record: dict[str, Any]) -> str:
    return record.get("ts") or ""


def read_logs(
    tail: int = 200,
    since: float | None = None,
    sources: list[str] | None = None,
    min_level: int = 0,
    important_only: bool = False,
    min_priority: int | None = None,
) -> dict[str, Any]:
    client = _client()
    try:
        containers = monitored_containers(client)
        all_sources = sorted({service_name(c) for c in containers})
        if sources:
            containers = [c for c in containers if service_name(c) in sources or c.name in sources]

        # When filtering (e.g. the Important tab), look further back so rare
        # important lines aren't crowded out by routine ones
        filtering = important_only or min_level > 0 or min_priority is not None
        scan = max(tail * 10, 2000) if filtering else tail

        records: list[dict[str, Any]] = []
        errors: dict[str, str] = {}
        for container in containers:
            try:
                records.extend(read_records(container, tail=scan, since=since))
            except DockerException as e:
                errors[service_name(container)] = str(e)
    finally:
        client.close()

    records = [
        r for r in records
        if r.get("level", 0) >= min_level
        and (not important_only or r.get("important") or r.get("level", 0) >= logging.WARNING)
        # priority isn't assigned yet (always None), so this only filters once a
        # policy exists in common/log_schema.classify()
        and (min_priority is None or r.get("priority") is None or r["priority"] <= min_priority)
    ]
    records.sort(key=_ts_key)
    records = records[-tail:]
    cursor = _ts_key(records[-1]) if records else None

    return {"records": records, "cursor": cursor, "sources": all_sources, "errors": errors}
