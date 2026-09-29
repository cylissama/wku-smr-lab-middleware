import os, asyncio, aiohttp, time
from aiohttp import web
from typing import Optional, Tuple
from datetime import datetime
from fast_server import loggers
from db.database import DatabaseSingleton
from zoneinfo import ZoneInfo

# Batched info for ROBOT
queue_size = float(os.getenv("QUEUE_SIZE", 5000))
robot_queue = asyncio.Queue(maxsize=queue_size)

# Items pulled off robot_queue into the current batch but not yet inserted --
# robot_queue.empty() alone misses this window, so fastapi-app's drain check
# (via /queue/status below) needs both numbers.
robot_pending = 0

# Helper to send messages from TCP server to FASTAPI server
async def send_to_fastapi(msg: str, msg_type: str = "normal"):
    host = os.getenv("FASTAPI_HOST", os.getenv("HOST_IP", "localhost"))
    port = os.getenv("FASTAPI_PORT", "8000")

    url = f"http://{host}:{port}/send/robot"

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
            try:
                await db.insert_robot_batch(batch)
                loggers.cur_robot_logger.info(f"Inserted {len(batch)} robot rows.")
                await send_to_fastapi(f"Inserted {len(batch)} robot rows.")
                batch.clear()
                robot_pending = 0
                last_flush = now
            except Exception as e:
                loggers.cur_robot_logger.error(f"DB batch insert failed: {e}")
                await send_to_fastapi(f"Failed to store message: {e}", "error")
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


async def start_status_server(port: int) -> None:
    app = web.Application()
    app.router.add_get("/queue/status", queue_status)

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
