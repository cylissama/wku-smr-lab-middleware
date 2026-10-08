import asyncio, os

import aiohttp

from fast_server import loggers
from fastapi import FastAPI, HTTPException, Query, WebSocket
from fastapi_mqtt import FastMQTT, MQTTConfig
from db.database import DatabaseSingleton, SessionNotStarted
from pathlib import Path
from fastapi.middleware.cors import CORSMiddleware
from fast_server.connection_manager import camera_manager, imu_manager, robot_manager, misc_manager, MANAGERS, broadcast_message
from typing import Annotated, Any
from pydantic import BaseModel

from fast_server.parsing import parse_camera_message, parse_imu_message
from fast_server.capture import CaptureMode, CaptureState, LiveSampler, device_key, split_current


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
        f"http://localhost:{web_port}",
        f"http://localhost:{fastapi_port}",
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

# Items pulled off each queue into the current batch but not yet inserted --
# Queue.empty() alone misses this window between a worker grabbing a batch
# and it landing in Postgres. Updated by camera_worker/imu_worker below.
imu_pending = 0
camera_pending = 0

# Gate for incoming device data: only stored while a session is recording.
# Pushed to tcp_server on every change so robot data follows the same rules.
capture = CaptureState()

# At most one live sample per device per LIVE_SAMPLE_INTERVAL seconds goes to
# the dashboard while monitoring or recording
live_sampler = LiveSampler(float(os.getenv("LIVE_SAMPLE_INTERVAL", 1.0)))

# A device counts as "receiving" if a message from it arrived this recently (s)
RECEIVING_TIMEOUT = float(os.getenv("RECEIVING_TIMEOUT", 3))

# Swarm stacks brought up/down together with each session, via stack-controller
MANAGED_STACKS = [s.strip() for s in os.getenv("MANAGED_STACKS", "edge").split(",") if s.strip()]

# Attempts to create a backup of DB and returns a status code of whether it was successful or not
async def try_backup() -> dict[str, Any]:

    await broadcast_message(misc_manager, "DB Backup Started")

    try:
        db = app.state.db
        # backup_path = db.create_backup()
        backup_path = await db.create_backup()
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

# API to get the registered session label categories, for the start-session dropdown
@app.get("/session/labels")
async def get_session_labels() -> dict[str, Any]:
    try:
        db = app.state.db
        data = await db.get_session_labels()

        return {"data": data, "success": True}
    except Exception as e:
        loggers.log_system_logger(f"Failed to pull session labels: {e}", True)
        await broadcast_message(misc_manager, f"Failed to pull session labels: {e}", "error")

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

# Calls the stack-controller agent. Mirrors tcp_server.py's send_to_fastapi()
# -- same internal-call pattern. Never raises: failures come back as
# {"success": False, "error": ...}; successful bodies get "success": True.
async def stack_controller_request(method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    host = os.getenv("STACK_CONTROLLER_HOST", "stack-controller")
    port = os.getenv("STACK_CONTROLLER_PORT", "8080")
    token = os.getenv("STACK_CONTROLLER_TOKEN")
    url = f"http://{host}:{port}{path}"

    try:
        async with aiohttp.ClientSession() as session:
            async with session.request(method, url, json=body, headers={"Authorization": f"Bearer {token}"}) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    loggers.log_system_logger(f"stack-controller {method} {path} failed ({resp.status}): {text}", True)
                    return {"success": False, "error": text}
                data = await resp.json()
                data.setdefault("success", True)
                return data
    except Exception as e:
        loggers.log_system_logger(f"Could not reach stack-controller for {method} {path}: {e}", True)
        return {"success": False, "error": str(e)}

# Deploys/removes one Swarm stack; services limits a deploy to those services
async def call_stack_controller(action: str, stack: str, services: list[str] | None = None) -> dict[str, Any]:
    body = {"services": services} if services is not None else None
    return await stack_controller_request("POST", f"/stacks/{stack}/{action}", body)

# Deploys every stack in MANAGED_STACKS, returns {stack_name: result}. With a
# plan ({stack: [services]}, from resolve_selection), only those services run;
# a stack with none selected is removed instead, so it doesn't keep publishing.
async def deploy_managed_stacks(plan: dict[str, list[str]] | None = None) -> dict[str, dict[str, Any]]:

    async def deploy_one(stack: str) -> dict[str, Any]:
        services = plan.get(stack) if plan is not None else None
        if services == []:
            result = await call_stack_controller("remove", stack)
            if not result.get("success"):
                loggers.log_system_logger(f"Could not remove unselected stack '{stack}': {result.get('error')}", True)
            return {"success": True, "skipped": True}
        return await call_stack_controller("deploy", stack, services)

    results = await asyncio.gather(*(deploy_one(s) for s in MANAGED_STACKS))
    return dict(zip(MANAGED_STACKS, results))

# The robot isn't a Swarm service -- it streams to tcp_server on its own
ROBOT_DEVICE = {"key": device_key("robot", "main"), "category": "robot", "device_label": "main",
                "stack": None, "service": None}

# Every selectable device: each managed stack's services that carry
# smr.category/smr.device labels (see deploy/swarm-edge-nodes.yml), plus the robot
async def load_device_catalog() -> list[dict[str, Any]]:
    listings = await asyncio.gather(*(stack_controller_request("GET", f"/stacks/{s}/services") for s in MANAGED_STACKS))
    devices = []

    for stack, listing in zip(MANAGED_STACKS, listings):
        if not listing.get("success"):
            raise RuntimeError(f"Could not list devices in stack '{stack}': {listing.get('error')}")

        for svc in listing.get("services", []):
            if svc.get("category") and svc.get("device_label"):
                devices.append({
                    "key": device_key(svc["category"], svc["device_label"]),
                    "category": svc["category"],
                    "device_label": svc["device_label"],
                    "stack": stack,
                    "service": svc["service"],
                })

    devices.append(dict(ROBOT_DEVICE))
    return devices

# Turns selected device keys into (capture filter, {stack: [services to deploy]}).
# None means every device / whole stacks. Raises ValueError on a bad selection.
async def resolve_selection(devices: list[str] | None) -> tuple[set[str] | None, dict[str, list[str]] | None]:
    if devices is None:
        return None, None
    if not devices:
        raise ValueError("No devices selected")

    catalog = {d["key"]: d for d in await load_device_catalog()}
    unknown = sorted(set(devices) - catalog.keys())
    if unknown:
        raise ValueError(f"Unknown device(s): {', '.join(unknown)}")

    plan: dict[str, list[str]] = {stack: [] for stack in MANAGED_STACKS}
    for key in sorted(set(devices)):
        device = catalog[key]
        if device["stack"]:
            plan[device["stack"]].append(device["service"])

    return set(devices), plan

class DeviceSelection(BaseModel):
    # Device keys like "imu/106"; omit (null) for every device
    devices: list[str] | None = None

# API to list selectable devices with their current state, for the dashboard
@app.get("/devices")
async def get_devices() -> dict[str, Any]:
    try:
        catalog = await load_device_catalog()
    except Exception as e:
        return {"error": str(e), "success": False}

    *stack_statuses, robot_status = await asyncio.gather(
        *(stack_controller_request("GET", f"/stacks/{s}/status") for s in MANAGED_STACKS),
        get_robot_queue_status(),
    )
    statuses = dict(zip(MANAGED_STACKS, stack_statuses))

    for device in catalog:
        # Is its data actually arriving? Only tracked while monitoring/recording.
        if device["stack"]:
            device.update(live_sampler.activity(device["key"], RECEIVING_TIMEOUT))
        else:
            device.update(robot_status.get("activity") or {"receiving": False, "rate": None, "last_seen_s": None})

        if device["stack"]:
            status = statuses[device["stack"]]
            if not status.get("success") or (status.get("state") == "error" and not status.get("services")):
                device["state"] = "unknown"
            else:
                # Swarm names services <stack name>_<service>
                states = [s["state"] for s in status.get("services", []) if s["name"].endswith("_" + device["service"])]
                device["state"] = states[0] if states else "not_deployed"
        elif "error" in robot_status:
            device["state"] = "unknown"
        else:
            device["state"] = "connected" if robot_status.get("connections", 0) > 0 else "not_connected"

    return {"data": catalog, "selected": capture.to_dict()["devices"], "success": True}

# Removes every stack in MANAGED_STACKS, returns {stack_name: result}
async def remove_managed_stacks() -> dict[str, dict[str, Any]]:
    results = await asyncio.gather(*(call_stack_controller("remove", s) for s in MANAGED_STACKS))
    return dict(zip(MANAGED_STACKS, results))

# Pushes the capture state to tcp_server (separate process), which gates robot
# data with it. Best effort: tcp_server also re-syncs from GET /capture on
# its own, so a failed push is logged rather than fatal.
async def push_capture_to_tcp() -> bool:
    host = os.getenv("TCP_HOST", "tcp")
    port = os.getenv("ROBOT_STATUS_PORT", "8090")
    url = f"http://{host}:{port}/capture"

    try:
        async with aiohttp.ClientSession() as session:
            async with session.put(url, json=capture.to_dict(), timeout=aiohttp.ClientTimeout(total=2)) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    loggers.log_system_logger(f"tcp_server rejected capture update ({resp.status}): {text}", True)
                    return False
                return True
    except Exception as e:
        loggers.log_system_logger(f"Could not push capture state to tcp_server: {e}", True)
        return False

# Changes the capture state and propagates it to tcp_server
async def set_capture(mode: CaptureMode, session_id: int | None = None, devices: set[str] | None = None) -> None:
    capture.set(mode, session_id=session_id, devices=devices)
    loggers.log_system_logger(f"Capture mode -> {mode.value} (session {session_id})")
    await push_capture_to_tcp()

# API to get the current capture state -- tcp_server re-syncs from this
@app.get("/capture")
async def get_capture() -> dict[str, Any]:
    return capture.to_dict()

# API to start monitor (listen-only) mode: brings the edge stacks up and shows
# live samples on the dashboard, but nothing is stored
@app.post("/listen/start")
async def start_listening(body: DeviceSelection | None = None) -> dict[str, Any]:
    if capture.mode != CaptureMode.IDLE:
        return {"error": f"Can't start monitoring while {capture.mode.value}", "success": False}

    try:
        selected, plan = await resolve_selection(body.devices if body else None)
    except Exception as e:
        return {"error": str(e), "success": False}

    await set_capture(CaptureMode.MONITOR, devices=selected)
    await broadcast_message(misc_manager, "Monitoring started -- live data only, nothing is stored", "info")

    deploy_results = await deploy_managed_stacks(plan)
    failed_stacks = [name for name, result in deploy_results.items() if not result.get("success")]

    if failed_stacks:
        for name in failed_stacks:
            err = deploy_results[name].get("error")
            loggers.log_system_logger(f"Failed to deploy '{name}' stack for monitoring: {err}", True)
            await broadcast_message(misc_manager, f"Failed to deploy '{name}' stack: {err}", "error")

        await set_capture(CaptureMode.IDLE)
        return {"error": f"Failed to deploy stack(s): {', '.join(failed_stacks)}", "success": False}

    return {"success": True, **capture.to_dict()}

# API to stop monitor mode and take the edge stacks back down
@app.post("/listen/stop")
async def stop_listening() -> dict[str, Any]:
    if capture.mode != CaptureMode.MONITOR:
        return {"error": f"Not monitoring (currently {capture.mode.value})", "success": False}

    await set_capture(CaptureMode.IDLE)

    remove_results = await remove_managed_stacks()
    failed_stacks = [name for name, result in remove_results.items() if not result.get("success")]

    for name in failed_stacks:
        err = remove_results[name].get("error")
        loggers.log_system_logger(f"Failed to remove '{name}' stack: {err}", True)
        await broadcast_message(misc_manager, f"Failed to remove '{name}' stack: {err}", "error")

    await broadcast_message(misc_manager, "Monitoring stopped", "info")
    return {"success": True, "stack_removal_failed": failed_stacks or None, **capture.to_dict()}

# Polls tcp_server's robot queue status over HTTP (it's a separate process/
# container with its own robot_queue -- fastapi-app has no in-process handle
# on it). Treated as "not empty" on any failure to reach it, so a drain
# timeout surfaces as a visible warning instead of a silent false-positive.
async def get_robot_queue_status() -> dict[str, Any]:
    host = os.getenv("TCP_HOST", "tcp")
    port = os.getenv("ROBOT_STATUS_PORT", "8090")
    url = f"http://{host}:{port}/queue/status"

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=2)) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    return {"empty": False, "error": f"status {resp.status}: {text}"}
                return await resp.json()
    except Exception as e:
        return {"empty": False, "error": str(e)}

# Waits for the IMU/camera in-process batch queues and the robot queue (in the
# separate tcp_server process) to fully drain after their stacks stop
# producing, so nothing is left unflushed when the session ends. Checks both
# queue depth and each worker's in-flight batch ("pending"), since an empty
# queue doesn't mean the last batch has actually landed in Postgres yet.
# Returns (drained, names of queues still not empty when it gave up).
async def drain_queues(timeout: float = 10.0, poll_interval: float = 0.5) -> tuple[bool, list[str]]:
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout

    while True:
        robot_status = await get_robot_queue_status()

        remaining = []
        if not (imu_queue.empty() and imu_pending == 0):
            remaining.append("imu")
        if not (camera_queue.empty() and camera_pending == 0):
            remaining.append("camera")
        if not robot_status.get("empty", False):
            remaining.append("robot")

        if not remaining:
            return True, []

        if loop.time() >= deadline:
            return False, remaining

        await asyncio.sleep(poll_interval)

# API to start a session
@app.get("/session/start/{label}")
# devices: repeated ?devices=imu/106&devices=robot/main to record only those;
# omitted = every device
async def start_session(
    label: str,
    session_label: str,
    is_test_session: bool = True,
    devices: Annotated[list[str] | None, Query()] = None,
) -> dict[str, Any]:

    # Create new logs for this new session only
    loggers.create_loggers()

    # Set once this call opens the gate, so a failure only closes a gate it opened
    # (not one belonging to a session that was already recording)
    opened_gate = False

    # Monitoring already has the edge stacks up, so recording just flips the gate
    # (unless the selection changed)
    was_monitoring = capture.mode == CaptureMode.MONITOR
    monitored_devices = capture.devices

    # Prep logs and prepare session id
    try:
        # Validated before the session row exists, so a bad selection creates nothing
        selected, plan = await resolve_selection(devices)

        db = app.state.db
        session_id = await db.create_session(
            label=label, session_label_name=session_label, is_test_session=is_test_session, devices=selected,
        )

        loggers.log_system_logger(f"System session created with label: {label} (type: {session_label})")
        loggers.cur_camera_logger.info(f"Camera session ready with label: {label}")
        loggers.cur_imu_logger.info(f"IMU session ready with label: {label}")
        loggers.cur_robot_logger.info(f"Robot session ready with label: {label}")

        await broadcast_message(misc_manager, "Session started with logs successfully")

        # Session row exists now, so open the gate before bringing the edge-node
        # stacks online -- their first published messages will be stored.
        await set_capture(CaptureMode.RECORD, session_id=session_id, devices=selected)
        opened_gate = True

        if was_monitoring and selected == monitored_devices:
            deploy_results = {}
        else:
            deploy_results = await deploy_managed_stacks(plan)
        failed_stacks = [name for name, result in deploy_results.items() if not result.get("success")]

        if failed_stacks:
            for name in failed_stacks:
                err = deploy_results[name].get("error")
                loggers.log_system_logger(f"Failed to deploy '{name}' stack: {err}", True)
                await broadcast_message(misc_manager, f"Failed to deploy '{name}' stack: {err}", "error")

            # Block: a session with no running stacks won't receive any data, so roll it back.
            await set_capture(CaptureMode.IDLE)
            try:
                await db.end_session()
            except Exception as rollback_err:
                loggers.log_system_logger(f"Failed to roll back session after stack deploy failure: {rollback_err}", True)

            return {
                "error": f"Failed to deploy stack(s): {', '.join(failed_stacks)}",
                "success": False,
            }

        return {
            "message": f"Session started with label: {label}",
            "id": session_id,
            "success": True,
        }
    except Exception as e:

        # Never leave the gate open without a session behind it; if we came from
        # monitoring, the stacks are still up, so go back to that
        if opened_gate:
            if was_monitoring:
                await set_capture(CaptureMode.MONITOR, devices=monitored_devices)
            else:
                await set_capture(CaptureMode.IDLE)

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

    # Close the gate first so nothing new is queued, then stop the edge-node
    # stacks and drain whatever's still queued before ending the session --
    # ensures nothing is left in the buffer when the session (and backup) closes.
    # session_id is kept while STOPPING so the workers still flush its batches.
    await set_capture(CaptureMode.STOPPING, session_id=capture.session_id, devices=capture.devices)

    remove_results = await remove_managed_stacks()
    failed_stacks = [name for name, result in remove_results.items() if not result.get("success")]

    for name in failed_stacks:
        err = remove_results[name].get("error")
        loggers.log_system_logger(f"Failed to remove '{name}' stack: {err}", True)
        await broadcast_message(misc_manager, f"Failed to remove '{name}' stack: {err}", "error")
        # Session/backup still proceed below either way -- surfaced as an error, not fatal.

    drained, still_buffered = await drain_queues()
    if not drained:
        loggers.log_system_logger(f"Timed out waiting for queue(s) to drain before stopping session: {', '.join(still_buffered)}", True)
        await broadcast_message(misc_manager, f"Warning: stopping session with data still buffered in: {', '.join(still_buffered)}", "error")

    await db.end_session()
    await set_capture(CaptureMode.IDLE)

    loggers.log_system_logger("System session stopped successfully")
    loggers.cur_camera_logger.info(f"Camera session ended.")
    loggers.cur_imu_logger.info(f"IMU session ended.")
    loggers.cur_robot_logger.info(f"Robot session ended.")

    await broadcast_message(misc_manager, "Session ended with logs successfully")

    msg = await try_backup()

    return {
        "message": f"Current Session Ended",
        "backup": msg,
        "success": True,
        "stack_removal_failed": failed_stacks or None,
    }
  except Exception as e:

    # Stop was requested, so stop storing even if ending the session failed
    if capture.mode != CaptureMode.IDLE:
        await set_capture(CaptureMode.IDLE)

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

    # Resume recording if a session was left open (e.g. fastapi-app restarted
    # mid-session); otherwise start idle. Always set() so the version is fresh.
    await restore_capture()

    # Creates workers for IMU and CAMERA
    asyncio.create_task(camera_worker(batch_size=int(os.getenv("BATCHES", 50)), flush_interval=float(os.getenv("B_TIMEOUT"))))
    asyncio.create_task(imu_worker(batch_size=int(os.getenv("BATCHES", 50)), flush_interval=float(os.getenv("B_TIMEOUT"))))

# Sets the capture state from the DB: RECORD if a session is open, else IDLE
async def restore_capture() -> None:
    try:
        session_id = await app.state.db.get_latest_session()
    except Exception as e:
        loggers.log_system_logger(f"Could not check for an open session at startup: {e}", True)
        session_id = None

    if session_id:
        try:
            devices = await app.state.db.get_session_devices(session_id)
        except Exception as e:
            # Fail open to every device rather than dropping a live session's data
            loggers.log_system_logger(f"Could not read device selection for session {session_id}: {e}", True)
            devices = None
        await set_capture(CaptureMode.RECORD, session_id=session_id, devices=devices)
    else:
        await set_capture(CaptureMode.IDLE)

# FastAPI Shutdown
@app.on_event("shutdown")
async def shutdown_event():
    await DatabaseSingleton.close()

def format_imu_sample(d: dict[str, Any]) -> str:
    return (f"accel ({d['accel_x']:.2f}, {d['accel_y']:.2f}, {d['accel_z']:.2f}) "
            f"gyro ({d['gyro_x']:.2f}, {d['gyro_y']:.2f}, {d['gyro_z']:.2f}) "
            f"ypr ({d['yaw']:.1f}, {d['pitch']:.1f}, {d['roll']:.1f})")

def format_camera_sample(d: dict[str, Any]) -> str:
    return (f"frame {d['frame_idx']} marker {d['marker_idx']} "
            f"tvec ({d['tvec_x']:.3f}, {d['tvec_y']:.3f}, {d['tvec_z']:.3f})")

# Sends a throttled "[live]" sample of a device's data to its dashboard channel
async def send_live_sample(manager, category: str, data: dict[str, Any], fmt) -> None:
    key = device_key(category, data["device_label"])
    rate = live_sampler.tick(key)
    if rate is None:
        return
    await broadcast_message(manager, f"[live] {key} · {LiveSampler.describe_rate(rate)} · {fmt(data)}", "live")

# Inserts one worker batch. Returns True when the batch is done with (stored or
# deliberately dropped) and should be cleared, False to keep it and retry.
# Items from an already-ended session, or a batch with no session to land in,
# are dropped -- retrying them would write them into the NEXT session.
async def flush_batch(batch, insert_batch, name, logger, manager) -> bool:
    current, stale = split_current(capture, batch)

    if stale:
        logger.warning(f"Dropped {len(stale)} {name} rows captured outside the current session")

    if not current:
        return True

    try:
        await insert_batch(current)
    except SessionNotStarted as e:
        logger.error(f"{name} batch dropped, no active session: {e}")
        await broadcast_message(manager, f"{name} batch of {len(current)} dropped: no active session", "error")
        return True
    except Exception as e:
        logger.error(f"{name} batch insert failed: {e}")
        await broadcast_message(manager, f"{name} batch insert failed: {e}", "error")
        return False

    logger.info(f"Inserted {len(current)} {name} rows")
    await broadcast_message(manager, f"Inserted {len(current)} {name} rows")
    return True

# Camera Worker
async def camera_worker(batch_size=50, flush_interval=2.0) -> None:
    global camera_pending

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

        camera_pending = len(batch)

        # If the last flush was a X seconds ago OR the number of messages exceed the batch size, insert them to DB
        now = asyncio.get_event_loop().time()
        if len(batch) >= batch_size or (batch and (now - last_flush) >= flush_interval):

            if await flush_batch(batch, db.insert_camera_batch, "CAMERA", loggers.cur_camera_logger, camera_manager):
                batch.clear()
                camera_pending = 0
                last_flush = now
            else:
                await asyncio.sleep(1)

# IMU Worker
async def imu_worker(batch_size=50, flush_interval=2.0) -> None:
    global imu_pending

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

        imu_pending = len(batch)

        # If the last flush was an X seconds ago OR the number of messages exceed the batch size, insert them to DB
        now = asyncio.get_event_loop().time()
        if len(batch) >= batch_size or (batch and (now - last_flush) >= flush_interval):

            if await flush_batch(batch, db.insert_imu_batch, "IMU", loggers.cur_imu_logger, imu_manager):
                batch.clear()
                imu_pending = 0
                last_flush = now
            else:
                await asyncio.sleep(1)

# MQTT Subscription for IMU device topics
@mqtt.subscribe("imu/#")
async def handle_sensors(client, topic, payload, qos, prop) -> None:

    # Not monitoring or recording -- drop before spending time parsing
    if not capture.is_listening():
        return

    try:
        data = parse_imu_message(topic, payload)
    except Exception as e:
        loggers.cur_imu_logger.error(f"IMU parse error: {e}")
        await broadcast_message(imu_manager, f"IMU parse error: {e}", "error")
        return

    if not capture.accepts("imu", data["device_label"]):
        return

    await send_live_sample(imu_manager, "imu", data, format_imu_sample)

    if capture.should_store():
        data["session_id"] = capture.session_id
        await imu_queue.put(data)

# MQTT Subscription for CAMERA device topics
@mqtt.subscribe("camera/#")
async def handle_camera(client, topic, payload, qos, prop) -> None:

    # Not monitoring or recording -- drop before spending time parsing
    if not capture.is_listening():
        return

    try:
        data = parse_camera_message(topic, payload)
    except Exception as e:
        loggers.cur_camera_logger.error(f"Camera parse error: {e}")
        await broadcast_message(camera_manager, f"Camera parse error: {e}", "error")
        return

    if not capture.accepts("camera", data["device_label"]):
        return

    await send_live_sample(camera_manager, "camera", data, format_camera_sample)

    if capture.should_store():
        data["session_id"] = capture.session_id
        await camera_queue.put(data)
