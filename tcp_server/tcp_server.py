import os, asyncio, aiohttp, time
from aiohttp import web
from typing import Optional, Tuple
from datetime import datetime
from fast_server import loggers
from db.database import DatabaseSingleton, SessionNotStarted
from fast_server.capture import CaptureState, split_current
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
            async with session.post(url, json=payload) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    print(f"FastAPI broadcast failed ({resp.status}): {text}")
    except Exception as e:
        print(f"Could not reach FastAPI API: {e}")


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

    try:
        await db.insert_robot_batch(current)
    except SessionNotStarted as e:
        loggers.cur_robot_logger.error(f"Robot batch dropped, no active session: {e}")
        await send_to_fastapi(f"Robot batch of {len(current)} dropped: no active session", "error")
        return True
    except Exception as e:
        loggers.cur_robot_logger.error(f"DB batch insert failed: {e}")
        await send_to_fastapi(f"Failed to store message: {e}", "error")
        return False

    loggers.cur_robot_logger.info(f"Inserted {len(current)} robot rows.")
    await send_to_fastapi(f"Inserted {len(current)} robot rows.")
    return True

# Continuously comsumes the queue and performs batched DB insertions
async def robot_worker(batch_size=50, flush_interval=2.0):
    global robot_pending

    db = await DatabaseSingleton.get_instance()
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
                await asyncio.sleep(1)

        await asyncio.sleep(0)

# Handles TCP Connection
async def handle_robot(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    db = await DatabaseSingleton.get_instance()
    buf = b""

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
                # lines while not listening (no session)
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
                        "recorded_at": db.get_time(),
                    }

                    if not capture.accepts("robot", "main"):
                        continue

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

    while True:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=2)) as resp:
                    if resp.status == 200 and capture.apply(await resp.json()):
                        loggers.cur_robot_logger.info(f"Capture synced -> {capture.mode.value} (session {capture.session_id})")
        except Exception as e:
            loggers.cur_robot_logger.warning(f"Capture sync with fastapi-app failed: {e}")

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

    asyncio.create_task(robot_worker(batch_size=batch_size, flush_interval=batch_timeout))
    asyncio.create_task(start_status_server(status_port))
    asyncio.create_task(capture_sync_loop(float(os.getenv("CAPTURE_SYNC_INTERVAL", 5))))

    async with server:
        await server.serve_forever()


def main():
    loggers.create_loggers()
    loggers.cur_robot_logger.info("Starting TCP fast_server...")

    try:
        asyncio.run(start_tcp_server())
    except KeyboardInterrupt:
        loggers.cur_robot_logger.info("TCP fast_server stopped by user.")
    except Exception as e:
        loggers.cur_robot_logger.error(f"TCP fast_server crashed: {e}")
    finally:
        asyncio.run(DatabaseSingleton.close())


if __name__ == "__main__":
    main()
