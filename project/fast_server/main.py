import asyncio, os

from fast_server import loggers
from fastapi import FastAPI, HTTPException, WebSocket
from fastapi_mqtt import FastMQTT, MQTTConfig
from db.database import DatabaseSingleton
from pathlib import Path
from fastapi.middleware.cors import CORSMiddleware
from fast_server.connection_manager import camera_manager, imu_manager, robot_manager, misc_manager, MANAGERS, broadcast_message
from typing import Any

from fast_server.parsing import parse_camera_message, parse_imu_message


def build_allowed_origins() -> list[str]:
    host_ip = os.getenv("HOST_IP", "localhost")
    web_port = os.getenv("WEB_PORT", "80")
    fastapi_port = os.getenv("FASTAPI_PORT", "8000")

    origins = {
        "http://localhost",
        "http://127.0.0.1",
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
        f"http://{host_ip}",
        f"http://{host_ip}:{web_port}",
        f"http://{host_ip}:3000",
        f"http://{host_ip}:5173",
        f"http://{host_ip}:{fastapi_port}",
    }

    return sorted(origins)

# MQTT Config Setup
mqtt_config = MQTTConfig(
    host=os.getenv("MQTT_HOST", "mqtt-broker"),
    port=int(os.getenv("MQTT_PORT", 1883)),
    keepalive=60,
)

# FastAPI Client
app = FastAPI()

# Cores Setup
app.add_middleware(
    CORSMiddleware,
    allow_origins=build_allowed_origins(),
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)

# Enabled FASTAPI + MQTT combo
mqtt = FastMQTT(config=mqtt_config)
mqtt.init_app(app)

# Batched Input Configurations -- Use .env
queue_size = int(os.getenv("QUEUE_SIZE", 5000))
imu_queue = asyncio.Queue(maxsize=queue_size)
camera_queue = asyncio.Queue(maxsize=queue_size)

# Attempts to create a backup of DB and returns a status code of whether it was successful or not
async def try_backup() -> dict[str, Any]:

    await broadcast_message(misc_manager, "DB Backup Started")

    try:
        db = app.state.db
        backup_path = db.create_backup()

        await broadcast_message(misc_manager, "DB Backup Completed")

        return {
            "success": True,
            "path": backup_path
        }
    except Exception as e:

        # Messages
        await broadcast_message(misc_manager, f"Failed to backup DB: {e}", "error")
        loggers.log_system_logger(f"Failed to backup DB: {e}", True)

        return {
            "success": False,
            "error": str(e)
        }

# Creates an open websocket for camera messages
@app.websocket("/ws/camera")
async def camera_ws(websocket: WebSocket) -> None:
    await camera_manager.connect(websocket)

    # Creates a connection and stays until connection is lost
    try:
        while True:
            await asyncio.sleep(3600)
    except Exception as e:
        loggers.log_system_logger(f"Camera WB Error: {e}", True)
    finally:
        camera_manager.disconnect(websocket)

# Creates an open websocket for robot messages
@app.websocket("/ws/robot")
async def robot_ws(websocket: WebSocket) -> None:
    await robot_manager.connect(websocket)

    # Creates a connection and stays until connection is lost
    try:
        while True:
            await asyncio.sleep(3600)
    except Exception as e:
        loggers.log_system_logger(f"Robot WB Error: {e}", True)
    
    finally:
        robot_manager.disconnect(websocket)

# Creates an open websocket for imu messages
@app.websocket("/ws/imu")
async def imu_ws(websocket: WebSocket) -> None:
    await imu_manager.connect(websocket)

    # Creates a connection and stays until connection is lost
    try:
        while True:
            await asyncio.sleep(3600)
    except Exception as e:
        loggers.log_system_logger(f"IMU WB Error: {e}", True)
    finally:
        imu_manager.disconnect(websocket)

# Creates an open websocket for misc messages
@app.websocket("/ws/misc")
async def misc_ws(websocket: WebSocket) -> None:
    await misc_manager.connect(websocket)

    # Creates a connection and stays until connection is lost
    try:
        while True:
            await asyncio.sleep(3600)
    except Exception as e:
        loggers.log_system_logger(f"Misc WB Error: {e}", True)
    finally:
        misc_manager.disconnect(websocket)

# API that sends messages to a manager for broadcasting into the web interface
@app.post("/send/{channel}")
async def send_channel(channel: str, payload: dict) -> dict[str, bool]:

    mgr = MANAGERS.get(channel)

    # Unable to find manager
    if not mgr:
        raise HTTPException(404, "unknown channel")

    # Expected Messages: {"type":"normal|info|error", "text":"..."}
    if "text" not in payload:
        raise HTTPException(400, "missing 'text'")

    if "type" not in payload:
        payload["type"] = "normal"

    await mgr.broadcast_json(payload)
    return {"success": True}

# API that returns a JSON of available backup files
@app.get("/backup/list")
def list_backups() -> dict[str, list[str]]:

    # Folder is attached in docker -- Must Match or else pathing errors
    folder = Path("/db_backups")
    files = []

    # List all files
    for file in folder.iterdir():
        if file.is_file():
          files.append(file.name)

    return {"files": files}

# API that starts a backup
@app.get("/backup")
async def backup() -> dict[str, Any]:
  return await try_backup()

# API to attempt to restore a backup
@app.post("/backup/restore/{filename}")
async def restore_backup(filename: str) -> dict[str, Any]:

    try:
        db = app.state.db

        # Must Match the mounted folder shown in compose
        path = f"/db_backups/{filename}"

        # Restore the DB
        await db.restore_backup(path)

        await broadcast_message(misc_manager, "DB Restore Completed")

        return {"success": True}

    except Exception as e:

        # Messages
        await broadcast_message(misc_manager, f"Restore failed: {e}", "error")
        loggers.log_system_logger(f"Failed to restore backup: {e}", True)

        return {"success": False, "error": str(e)}

# API to get a JSON of all sessions
@app.get("/sessions")
async def get_sessions() -> dict[str, Any]:
  try:
    db = app.state.db
    data = await db.retrieve_sessions()

    return {"data": data, "success": True}
  except Exception as e:
    loggers.log_system_logger(f"Failed to pull sessions: {e}", True)
    await broadcast_message(misc_manager, f"Failed to pull sessions: {e}", "error")

    return {"error": str(e), "success": False}

# API to get the current active session if available
@app.get("/session")
async def get_running_session() -> dict[str, Any]:
    
    try:
        db = app.state.db
        sess_id = db.current_session_id

        return {"id": sess_id if sess_id != None else -404, "data": sess_id != None, "success": True}

    except Exception as e:
        loggers.log_system_logger(f"Failed to get current session: {e}", True)
        await broadcast_message(misc_manager, f"Failed to get current session: {e}", "error")

        return {"error": str(e), "success": False}

# API to get a JSON of historical IMU data from a session label
@app.get("/imu/{label}")
async def get_imu(label: str) -> dict[str, Any]:

  try:
    db = app.state.db
    data = await db.retrieve_imu(label)

    return {"data": data, "success": True}
  except Exception as e:
    loggers.log_system_logger(f"Failed to pull IMU data from session '{label}': {e}", True)
    await broadcast_message(misc_manager, f"Failed to pull IMU data from session {label}: {e}", "error")

    return {"error": str(e), "success": False}

# API to get a JSON of historical CAMERA data from a session label
@app.get("/camera/{label}")
async def get_camera(label: str) -> dict[str, Any]:

  try:
    db = app.state.db
    data = await db.retrieve_camera(label)

    return {"data": data, "success": True}
  except Exception as e:
    loggers.log_system_logger(f"Failed to pull CAMERA data from session '{label}': {e}", True)
    await broadcast_message(misc_manager, f"Failed to pull CAMERA data from session {label}: {e}", "error")

    return {"error": str(e), "success": False}

# API to get a JSON of historical ROBOT data from a session label
@app.get("/robot/{label}")
async def get_robot(label: str) -> dict[str, Any]:

  try:
    db = app.state.db
    data = await db.retrieve_robot(label)

    return {"data": data, "success": True}
  except Exception as e:
    loggers.log_system_logger(f"Failed to pull ROBOT data from session '{label}': {e}", True)
    await broadcast_message(misc_manager, f"Failed to pull ROBOT data from session {label}: {e}", "error")

    return {"error": str(e), "success": False}

# API to start a session
@app.get("/session/start/{label}")
async def start_session(label: str, is_test_session: bool = True) -> dict[str, Any]:

    # Create new logs for this new session only
    loggers.create_loggers()

    # Prep logs and prepare session id
    try:
        db = app.state.db
        session_id = await db.create_session(label=label, is_test_session=is_test_session)

        loggers.log_system_logger(f"System session created with label: {label}")
        loggers.cur_camera_logger.info(f"Camera session ready with label: {label}")
        loggers.cur_imu_logger.info(f"IMU session ready with label: {label}")
        loggers.cur_robot_logger.info(f"Robot session ready with label: {label}")

        await broadcast_message(misc_manager, "Session started with logs successfully")

        return {
            "message": f"Session started with label: {label}",
            "id": session_id,
            "success": True,
        }
    except Exception as e:

        loggers.log_system_logger(f"Failed to start session '{label}': {e}", True)
        loggers.cur_camera_logger.error(f"Camera session failed to start with label: {label}. Error: {e}")
        loggers.cur_imu_logger.error(f"IMU session failed to start with label: {label}. Error: {e}")
        loggers.cur_robot_logger.error(f"Robot session failed to start with label: {label}. Error: {e}")

        await broadcast_message(misc_manager, f"Failed to start a session with label '{label}': {e}", "error")

        return {"error": str(e), "success": False}

# API to stop a session
@app.get("/session/stop")
async def stop_session() -> dict[str, Any]:

  try:

    db = app.state.db
    await db.end_session()

    loggers.log_system_logger("System session stopped successfully")
    loggers.cur_camera_logger.info(f"Camera session ended.")
    loggers.cur_imu_logger.info(f"IMU session ended.")
    loggers.cur_robot_logger.info(f"Robot session ended.")

    await broadcast_message(misc_manager, "Session ended with logs successfully")

    msg = await try_backup()

    return {"message": f"Current Session Ended", "backup": msg, "success": True}
  except Exception as e:

    loggers.log_system_logger(f"Failed to stop the current session: {e}", True)
    loggers.cur_camera_logger.error(f"Camera session failed to stop. Error: {e}")
    loggers.cur_imu_logger.error(f"IMU session failed to stop. Error: {e}")
    loggers.cur_robot_logger.error(f"Robot session failed to stop. Error: {e}")

    await broadcast_message(misc_manager, f"Failed to stop the current session: {e}", "error")

    return {"error": str(e), "success": False}

# FastAPI Startup
@app.on_event("startup")
async def startup():

    # Creates a DB singleton to be used in API calls
    app.state.db = await DatabaseSingleton.get_instance()

    # Creates the loggers instances to be ready
    loggers.create_loggers()

    # Creates workers for IMU and CAMERA
    asyncio.create_task(camera_worker(batch_size=int(os.getenv("BATCHES", 50)), flush_interval=float(os.getenv("B_TIMEOUT"))))
    asyncio.create_task(imu_worker(batch_size=int(os.getenv("BATCHES", 50)), flush_interval=float(os.getenv("B_TIMEOUT"))))

# FastAPI Shutdown
@app.on_event("shutdown")
async def shutdown_event():
    await DatabaseSingleton.close()

# Camera Worker
async def camera_worker(batch_size=50, flush_interval=2.0) -> None:
    db = app.state.db
    batch = []
    last_flush = asyncio.get_event_loop().time()

    # Continues to work unless worker process ends
    while True:

        # Attempt to grab messages in QUEUE
        try:
            item = await asyncio.wait_for(camera_queue.get(), timeout=0.5)
            batch.append(item)
        except asyncio.TimeoutError:
            pass

        # If the last flush was a X seconds ago OR the number of messages exceed the batch size, insert them to DB
        now = asyncio.get_event_loop().time()
        if len(batch) >= batch_size or (batch and (now - last_flush) >= flush_interval):

            try:
                await db.insert_camera_batch(batch)

                loggers.cur_camera_logger.info(f"Inserted {len(batch)} CAMERA rows")
                await broadcast_message(camera_manager, f"Inserted {len(batch)} CAMERA rows")

                batch.clear()
                last_flush = now
            except Exception as e:
                loggers.cur_camera_logger.error(f"CAMERA batch insert failed: {e} {batch[0]}")
                await broadcast_message(camera_manager, f"CAMERA batch insert failed: {e}", "error")

                await asyncio.sleep(1)

# IMU Worker
async def imu_worker(batch_size=50, flush_interval=2.0) -> None:
    db = app.state.db
    batch = []
    last_flush = asyncio.get_event_loop().time()

    # Continues to work unless worker process ends
    while True:

        # Attempt to grab messages in QUEUE
        try:
            item = await asyncio.wait_for(imu_queue.get(), timeout=0.5)
            batch.append(item)
        except asyncio.TimeoutError:
            pass

        # If the last flush was an X seconds ago OR the number of messages exceed the batch size, insert them to DB
        now = asyncio.get_event_loop().time()
        if len(batch) >= batch_size or (batch and (now - last_flush) >= flush_interval):

            try:
                await db.insert_imu_batch(batch)

                loggers.cur_imu_logger.info(f"Inserted {len(batch)} IMU rows")
                await broadcast_message(imu_manager, f"Inserted {len(batch)} IMU rows")

                batch.clear()
                last_flush = now
            except Exception as e:
                loggers.cur_imu_logger.error(f"IMU batch insert failed: {e}")
                await broadcast_message(imu_manager, f"IMU batch insert failed: {e}", "error")

                await asyncio.sleep(1)

# MQTT Subscription for IMU device topics
@mqtt.subscribe("imu/#")
async def handle_sensors(client, topic, payload, qos, prop) -> None:

    try:
        data = parse_imu_message(topic, payload)
        await imu_queue.put(data)
    except Exception as e:
        loggers.cur_imu_logger.error(f"IMU parse error: {e}")
        await broadcast_message(imu_manager, f"IMU parse error: {e}", "error")

# MQTT Subscription for CAMERA device topics
@mqtt.subscribe("camera/#")
async def handle_camera(client, topic, payload, qos, prop) -> None:

    try:
        data = parse_camera_message(topic, payload)
        await camera_queue.put(data)

    except Exception as e:
        loggers.cur_camera_logger.error(f"Camera parse error: {e}")
        await broadcast_message(camera_manager, f"Camera parse error: {e}", "error")
