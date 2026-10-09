import os, asyncio, aiohttp, logging, time
from aiohttp import web
from typing import Optional, Tuple
from datetime import datetime, timezone
from fast_server import loggers
from db.database import DatabaseSingleton, SessionNotStarted
from fast_server.capture import CaptureState, LiveSampler, split_current
from fast_server.health import backoff_delay, describe_age
from zoneinfo import ZoneInfo

# Batched info for ROBOT
queue_size = float(os.getenv("QUEUE_SIZE", 5000))
robot_queue = asyncio.Queue(maxsize=queue_size)

# Items pulled off robot_queue into the current batch but not yet inserted --
# robot_queue.empty() alone misses this window, so fastapi-app's drain check
# (via /queue/status below) needs both numbers.
robot_pending = 0

# Copy of fastapi-app's capture state -- robot lines are only queued while it
# says RECORD. Starts idle (drop everything) until the first sync arrives,
# either pushed via PUT /capture or pulled by capture_sync_loop().
capture = CaptureState()

# Open robot TCP connections, reported by /queue/status so the dashboard's
# device list can show whether the robot is connected
robot_connections = 0

# At most one live robot sample per LIVE_SAMPLE_INTERVAL seconds goes to the
# dashboard while monitoring or recording
live_sampler = LiveSampler(float(os.getenv("LIVE_SAMPLE_INTERVAL", 1.0)))

# Keeps fire-and-forget dashboard sends alive until they finish
_background_tasks: set[asyncio.Task] = set()

# The DB pool, set by db_monitor() once it connects; robot_worker waits for it
db: DatabaseSingleton | None = None
db_ready = asyncio.Event()

# Reported by /queue/status so fastapi-app (and the dashboard) see robot-side
# DB trouble: status ok/down/unknown, error, since (epoch s)
db_status: dict = {"status": "unknown", "error": None, "since": time.time()}

HEALTH_INTERVAL = float(os.getenv("HEALTH_INTERVAL", 10))

# Most robot rows held while inserts fail; older rows are dropped beyond this.
# Failures are reported at most every BACKLOG_REPORT_INTERVAL s.
MAX_BACKLOG_ROWS = int(os.getenv("MAX_BACKLOG_ROWS", os.getenv("QUEUE_SIZE", 5000)))
BACKLOG_REPORT_INTERVAL = float(os.getenv("BACKLOG_REPORT_INTERVAL", 10))

# Set while robot inserts are failing: since, last_report, dropped
insert_failure: dict | None = None


def describe_exc(e: BaseException) -> str:
    text = str(e).strip()
    return f"{type(e).__name__}: {text}" if text else type(e).__name__


# A DB error with where we were connecting to (same wording as fastapi-app)
def describe_db_error(e: BaseException) -> str:
    target = f"{os.getenv('DB_HOST')}:{os.getenv('DB_PORT')}"
    if isinstance(e, (asyncio.TimeoutError, TimeoutError)):
        reason = f"no answer within {os.getenv('DB_CONNECT_TIMEOUT', '5')}s (host down or unreachable?)"
    else:
        reason = describe_exc(e)
    return f"can't reach {target}: {reason}"


def set_db_status(ok: bool, error: str | None = None) -> None:
    status = "ok" if ok else "down"
    if db_status["status"] != status:
        if ok:
            if db_status["status"] == "down":
                loggers.log_event(f"tcp database connection recovered after {describe_age(time.time() - db_status['since'])}",
                                  category="health", component="db")
        else:
            loggers.log_event(f"tcp database down: {error}", category="health", level=logging.ERROR, component="db")
        db_status.update(status=status, since=time.time())
    db_status["error"] = error


# Connects to the DB with backoff (the TCP listener is already up), then keeps
# checking it every HEALTH_INTERVAL s. asyncpg's pool reconnects by itself.
async def db_monitor() -> None:
    global db

    attempt = 0
    while db is None:
        attempt += 1
        try:
            db = await DatabaseSingleton.get_instance()
        except Exception as e:
            delay = backoff_delay(attempt)
            loggers.log_event(f"DB connect attempt {attempt} failed: {describe_db_error(e)} -- retrying in {delay}s",
                              category="health", level=logging.WARNING, important=False, component="db")
            set_db_status(False, describe_db_error(e))
            await asyncio.sleep(delay)

    set_db_status(True)
    db_ready.set()

    while True:
        await asyncio.sleep(HEALTH_INTERVAL)
        try:
            await asyncio.wait_for(db.pool.fetchval("SELECT 1"), timeout=3)
            set_db_status(True)
        except Exception as e:
            set_db_status(False, describe_db_error(e))


# Runs a long-lived loop and restarts it (with backoff) if it ever raises
async def run_forever(name: str, loop_fn) -> None:
    failures = 0
    while True:
        try:
            await loop_fn()
            return
        except asyncio.CancelledError:
            raise
        except Exception as e:
            failures += 1
            delay = backoff_delay(failures)
            loggers.log_event(f"{name} crashed ({describe_exc(e)}), restarting in {delay}s",
                              category="system", level=logging.ERROR, task=name, failures=failures)
            await asyncio.sleep(delay)

def fastapi_base_url() -> str:
    host = os.getenv("FASTAPI_HOST", os.getenv("HOST_IP", "localhost"))
    port = os.getenv("FASTAPI_PORT", "8000")
    return f"http://{host}:{port}"

# Helper to send messages from TCP server to FASTAPI server
async def send_to_fastapi(msg: str, msg_type: str = "normal"):
    url = f"{fastapi_base_url()}/send/robot"

    payload = {
        "type": msg_type,
        "text": msg,
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    print(f"FastAPI broadcast failed ({resp.status}): {text}")
    except Exception as e:
        print(f"Could not reach FastAPI API: {e}")


# Sends to the dashboard without waiting, so a slow fastapi-app never stalls
# reading from the robot socket
def send_to_fastapi_nowait(msg: str, msg_type: str = "normal") -> None:
    task = asyncio.create_task(send_to_fastapi(msg, msg_type))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


def format_robot_sample(d: dict) -> str:
    joints = ", ".join(f"{d[f'joint{i}']:.1f}" for i in range(1, 7))
    return f"joints ({joints}) xyz ({d['x']:.1f}, {d['y']:.1f}, {d['z']:.1f})"


# Inserts one robot batch. Returns True when the batch is done with (stored or
# deliberately dropped), False to keep it and retry. Same rules as
# flush_batch() in fast_server/main.py: rows from an ended session, or with no
# session to land in, are dropped rather than written into the next session.
async def flush_robot_batch(db, batch) -> bool:
    current, stale = split_current(capture, batch)

    if stale:
        loggers.cur_robot_logger.warning(f"Dropped {len(stale)} robot rows captured outside the current session")

    if not current:
        return True

    global insert_failure

    try:
        await db.insert_robot_batch(current)
    except SessionNotStarted as e:
        loggers.cur_robot_logger.error(f"Robot batch dropped, no active session: {e}")
        await send_to_fastapi(f"Robot batch of {len(current)} dropped: no active session", "error")
        return True
    except Exception as e:
        now = time.time()
        if insert_failure is None:
            insert_failure = {"since": now, "last_report": 0.0, "dropped": 0}
        # One report per BACKLOG_REPORT_INTERVAL, not one per retry
        if now - insert_failure["last_report"] >= BACKLOG_REPORT_INTERVAL:
            insert_failure["last_report"] = now
            msg = (f"ROBOT inserts failing for {describe_age(now - insert_failure['since'])} ({describe_exc(e)}) -- "
                   f"holding {len(batch)} rows"
                   + (f", dropped {insert_failure['dropped']}" if insert_failure["dropped"] else ""))
            loggers.cur_robot_logger.error(msg)
            loggers.log_event(msg, category="ingest", level=logging.ERROR, worker="ROBOT",
                              rows_held=len(batch), dropped=insert_failure["dropped"])
            await send_to_fastapi(msg, "error")
        return False

    if insert_failure is not None:
        msg = (f"ROBOT inserts recovered after {describe_age(time.time() - insert_failure['since'])}"
               + (f" ({insert_failure['dropped']} rows dropped while failing)" if insert_failure["dropped"] else ""))
        insert_failure = None
        loggers.log_event(msg, category="ingest", worker="ROBOT")
        await send_to_fastapi(msg, "info")

    loggers.cur_robot_logger.info(f"Inserted {len(current)} robot rows.")
    await send_to_fastapi(f"Inserted {len(current)} robot rows.")
    return True

# Continuously comsumes the queue and performs batched DB insertions
async def robot_worker(batch_size=50, flush_interval=2.0):
    global robot_pending, insert_failure

    # Lines aren't queued while idle, and db_monitor() keeps retrying -- so
    # waiting here costs nothing and the worker can't die on a down DB
    await db_ready.wait()
    batch = []
    last_flush = time.monotonic()

    while True:
        try:
            item = await asyncio.wait_for(robot_queue.get(), timeout=0.5)
            batch.append(item)
        except asyncio.TimeoutError:
            pass

        robot_pending = len(batch)

        now = time.monotonic()
        if (len(batch) >= batch_size) or (batch and (now - last_flush) >= flush_interval):
            if await flush_robot_batch(db, batch):
                batch.clear()
                robot_pending = 0
                last_flush = now
            else:
                overflow = len(batch) - MAX_BACKLOG_ROWS
                if overflow > 0:
                    del batch[:overflow]
                    if insert_failure is not None:
                        insert_failure["dropped"] += overflow
                    loggers.cur_robot_logger.warning(f"ROBOT backlog over {MAX_BACKLOG_ROWS} rows, dropped the oldest {overflow}")
                robot_pending = len(batch)
                await asyncio.sleep(1)

        await asyncio.sleep(0)

# Handles TCP Connection
async def handle_robot(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    global robot_connections

    buf = b""
    robot_connections += 1

    try:
        while True:
            chunk = await reader.read(4096)
            if not chunk:
                break

            buf += chunk.replace(b"\r\n", b"\n").replace(b"\r", b"\n")

            while b"\n" in buf:
                line, _, buf = buf.partition(b"\n")
                text = line.decode("utf-8", errors="replace").strip()
                if not text:
                    continue

                # Keep reading so the robot's connection stays up, but drop
                # lines while not monitoring or recording
                if not capture.is_listening():
                    continue

                try:
                    parts = [p.strip() for p in text.split(",")]

                    ts_str = parts[0]

                    try:
                        dt = datetime.strptime(ts_str, "%m/%d/%Y %H:%M")
                        local_dt = dt.replace(tzinfo=ZoneInfo("US/Eastern"))
                        utc_dt = local_dt.astimezone(ZoneInfo("UTC"))
                        ts_epoch = int(utc_dt.timestamp())

                    except Exception as e:
                        ts_epoch = int(-1)


                    data = {
                        "frame_id": int(parts[0]), # count
                        "ts_epoch": float(parts[1]),
                        "ts_string": parts[2],

                        "joint1": float(parts[3]),
                        "joint2": float(parts[4]),
                        "joint3": float(parts[5]),
                        "joint4": float(parts[6]),
                        "joint5": float(parts[7]),
                        "joint6": float(parts[8]),
                        
                        "x": float(parts[9]),
                        "y": float(parts[10]),
                        "z": float(parts[11]),
                        "w": float(parts[12]),
                        "p": float(parts[13]),
                        "r": float(parts[14]),
                        "recorded_at": datetime.now(timezone.utc).timestamp(),
                    }

                    if not capture.accepts("robot", "main"):
                        continue

                    rate = live_sampler.tick("robot/main")
                    if rate is not None:
                        send_to_fastapi_nowait(f"[live] robot/main · {live_sampler.describe_rate(rate)} · {format_robot_sample(data)}", "live")

                    if capture.should_store():
                        data["session_id"] = capture.session_id
                        await robot_queue.put(data)
                        loggers.cur_robot_logger.info(f"Queued message: {text}")
                except Exception as e:
                    print(f"ROBOT PARSE ERROR: {e} line={text!r}")  # 👈 new
                    loggers.cur_robot_logger.error(f"Parse error: {e}")

    except asyncio.CancelledError:
        loggers.cur_robot_logger.info("Robot handler cancelled")
    finally:
        robot_connections -= 1
        writer.close()
        await writer.wait_closed()
        loggers.cur_robot_logger.info("Writer Closed")

# GET /queue/status -- lets fastapi-app's drain_queues() confirm robot data is
# fully flushed before stop_session ends the session. depth is items still
# queued; pending is items pulled into the in-flight batch but not yet
# inserted (see robot_worker) -- both must be zero for "empty" to be true.
async def queue_status(request: "web.Request") -> "web.Response":
    depth = robot_queue.qsize()
    return web.json_response({
        "depth": depth,
        "pending": robot_pending,
        "empty": depth == 0 and robot_pending == 0,
        "connections": robot_connections,
        # Is robot data actually arriving (only tracked while monitoring/recording)
        "activity": live_sampler.activity("robot/main", float(os.getenv("RECEIVING_TIMEOUT", 3))),
        # Robot-side DB connection, so fastapi-app's health check can report it
        "db": {**db_status, "for_s": round(time.time() - db_status["since"], 1)},
        "backlog": {"since": insert_failure["since"], "dropped": insert_failure["dropped"]} if insert_failure else None,
    })


# PUT /capture -- fastapi-app pushes its capture state here on every change.
# Stale copies (older version) are ignored.
async def put_capture(request: "web.Request") -> "web.Response":
    try:
        data = await request.json()
        applied = capture.apply(data)
    except Exception as e:
        return web.json_response({"error": f"bad capture state: {e}"}, status=400)

    if applied:
        loggers.cur_robot_logger.info(f"Capture mode -> {capture.mode.value} (session {capture.session_id})")
    return web.json_response({"applied": applied, **capture.to_dict()})


# Pulls fastapi-app's capture state on boot and every CAPTURE_SYNC_INTERVAL
# seconds, as a safety net for pushes that didn't arrive (e.g. this process
# restarted mid-session, or fastapi-app couldn't reach it).
async def capture_sync_loop(interval: float) -> None:
    url = f"{fastapi_base_url()}/capture"
    failures = 0

    while True:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=2)) as resp:
                    if resp.status == 200 and capture.apply(await resp.json()):
                        loggers.cur_robot_logger.info(f"Capture synced -> {capture.mode.value} (session {capture.session_id})")
            failures = 0
        except Exception as e:
            # fastapi-app is often still starting when tcp does (e.g. right after
            # a deploy), so only warn once it's been unreachable for a while
            failures += 1
            level = logging.WARNING if failures >= 3 else logging.INFO
            loggers.cur_robot_logger.log(level, f"Capture sync with fastapi-app failed ({failures}x): {describe_exc(e)}")

        await asyncio.sleep(interval)


async def start_status_server(port: int) -> None:
    app = web.Application()
    app.router.add_get("/queue/status", queue_status)
    app.router.add_put("/capture", put_capture)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    loggers.cur_robot_logger.info(f"[TCP] Queue status endpoint listening on :{port}")


# Starts the TCP server
async def start_tcp_server(host: Optional[str] = None, port: int = 5001):
    host = host or os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("ROBOT_TCP_PORT", port))
    batch_size = int(os.getenv("BATCHES", 50))
    batch_timeout = float(os.getenv("B_TIMEOUT", 1.0))
    status_port = int(os.getenv("ROBOT_STATUS_PORT", 8090))

    server = await asyncio.start_server(handle_robot, host=host, port=port)
    sockets = ", ".join(str(s.getsockname()) for s in (server.sockets or []))
    loggers.cur_robot_logger.info(f"[TCP] Listening on {sockets}")

    for task in (
        db_monitor(),
        run_forever("robot_worker", lambda: robot_worker(batch_size=batch_size, flush_interval=batch_timeout)),
        start_status_server(status_port),
        run_forever("capture_sync_loop", lambda: capture_sync_loop(float(os.getenv("CAPTURE_SYNC_INTERVAL", 5)))),
    ):
        t = asyncio.create_task(task)
        _background_tasks.add(t)
        t.add_done_callback(_background_tasks.discard)

    async with server:
        await server.serve_forever()


def main():
    loggers.create_loggers()
    loggers.log_event("tcp starting", category="system")

    try:
        asyncio.run(start_tcp_server())
    except KeyboardInterrupt:
        loggers.log_event("tcp stopped by user", category="system")
    except Exception as e:
        # Exit non-zero so the restart policy brings the container back
        loggers.cur_robot_logger.exception(f"TCP fast_server crashed: {e}")
        raise SystemExit(1)
    finally:
        try:
            asyncio.run(DatabaseSingleton.close())
        except Exception:
            pass


if __name__ == "__main__":
    main()
