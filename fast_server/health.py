# Health of fastapi-app's dependencies (DB, MQTT, stack-controller, tcp, NAS
# paths), reported by GET /health and shown on the dashboard. Each component
# flips between ok/down; transitions -- not every retry -- are logged as
# important events and broadcast on /ws/misc. See
# plans/dashboard-decouple-plan.md §B.

import asyncio
import logging
import time
from typing import Any, Awaitable, Callable

from fast_server import loggers

# Retry delays (s) for reconnect loops: 1, 2, 5, 10, then every 30
BACKOFF = (1, 2, 5, 10, 30)


def backoff_delay(attempt: int) -> float:
    return BACKOFF[min(max(attempt, 1), len(BACKOFF)) - 1]


def describe_age(seconds: float) -> str:
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m {seconds % 60}s"
    return f"{seconds // 3600}h {seconds % 3600 // 60}m"


class HealthRegistry:

    def __init__(self, components: list[str], notify: Callable[[str, str], Awaitable[None]] | None = None):
        now = time.time()
        self.components: dict[str, dict[str, Any]] = {
            name: {"status": "unknown", "error": None, "since": now, "last_ok": None,
                   "attempts": 0, "next_retry_at": None, "detail": {}}
            for name in components
        }
        # async notify(message, msg_type) -- e.g. a /ws/misc broadcast
        self.notify = notify

    async def ok(self, name: str, **detail: Any) -> None:
        c = self.components[name]
        was = c["status"]
        now = time.time()
        if was != "ok":
            down_for = now - c["since"]
            c.update(status="ok", error=None, since=now)
            if was == "down":
                await self._announce(f"{name} recovered after {describe_age(down_for)}", logging.INFO, name)
            else:
                loggers.log_event(f"{name} ok", category="health", important=False, component=name)
        c.update(last_ok=now, attempts=0, next_retry_at=None, detail=detail)

    async def down(self, name: str, error: str, attempts: int | None = None,
                   retry_in: float | None = None, **detail: Any) -> None:
        c = self.components[name]
        was = c["status"]
        now = time.time()
        if was != "down":
            c.update(status="down", since=now)
            await self._announce(f"{name} down: {error}", logging.ERROR, name)
        elif c["error"] != error:
            # Same outage, different reason -- worth a line in the logs, not a broadcast
            loggers.log_event(f"{name} still down: {error}", category="health", level=logging.WARNING,
                              important=False, component=name)
        c.update(error=error, attempts=attempts if attempts is not None else c["attempts"] + 1,
                 next_retry_at=now + retry_in if retry_in is not None else None, detail=detail)

    def is_ok(self, name: str) -> bool:
        return self.components[name]["status"] == "ok"

    def describe(self, name: str) -> str:
        c = self.components[name]
        if c["status"] == "ok":
            return f"{name} ok"
        if c["status"] == "unknown":
            return f"{name} not connected yet"
        text = f"{name} down {describe_age(time.time() - c['since'])}: {c['error']}"
        if c["next_retry_at"]:
            text += f" (retrying in {max(0, int(c['next_retry_at'] - time.time()))}s)"
        return text

    def snapshot(self) -> dict[str, Any]:
        now = time.time()
        components = {}
        for name, c in self.components.items():
            components[name] = {
                "status": c["status"],
                "error": c["error"],
                "since": c["since"],
                "for_s": round(now - c["since"], 1),
                "last_ok": c["last_ok"],
                "attempts": c["attempts"],
                "retry_in_s": max(0.0, round(c["next_retry_at"] - now, 1)) if c["next_retry_at"] else None,
                "detail": c["detail"],
            }
        statuses = {c["status"] for c in components.values()}
        overall = "ok" if statuses == {"ok"} else "degraded" if "down" in statuses else "starting"
        return {"overall": overall, "components": components, "time": now}

    async def _announce(self, message: str, level: int, name: str) -> None:
        loggers.log_event(message, category="health", level=level, component=name)
        if self.notify:
            try:
                await self.notify(message, "error" if level >= logging.WARNING else "info")
            except Exception:
                pass


# Runs a blocking filesystem check in a thread with a timeout. A hung NFS mount
# would leave the thread stuck, so a new probe isn't started while the previous
# one is still running -- that counts as a failure instead.
class PathProbe:

    def __init__(self, check: Callable[[], Any], timeout: float = 5.0):
        self.check = check
        self.timeout = timeout
        self._running: asyncio.Future | None = None

    async def run(self) -> Any:
        if self._running is not None and not self._running.done():
            raise TimeoutError(f"previous check still hasn't returned after {self.timeout:.0f}s+ (mount hung?)")
        self._running = asyncio.ensure_future(asyncio.to_thread(self.check))
        return await asyncio.wait_for(asyncio.shield(self._running), self.timeout)
