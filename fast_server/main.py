import asyncio, logging, os, time

import aiohttp
import asyncpg

from fast_server import loggers
from fastapi import FastAPI, HTTPException, Query, Request, WebSocket
from fastapi.responses import JSONResponse
from fastapi_mqtt import FastMQTT, MQTTConfig
from db.database import DatabaseSingleton, SessionNotStarted
from pathlib import Path
from fastapi.middleware.cors import CORSMiddleware
from fast_server.connection_manager import camera_manager, imu_manager, robot_manager, misc_manager, MANAGERS, broadcast_message
from typing import Annotated, Any
from pydantic import BaseModel

from fast_server.parsing import parse_camera_message, parse_imu_message
from fast_server.capture import CaptureMode, CaptureState, LiveSampler, device_key, split_current
from fast_server.health import HealthRegistry, PathProbe, backoff_delay, describe_age
from fast_server.plc_listener import PLCSignalWatcher, build_plc_factory


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
# reconnect_retries=-1: keep reconnecting after a lost connection forever
# (fastapi-mqtt's default of 1 gives up after a single ~6 s retry)
mqtt_config = MQTTConfig(
    host=os.getenv("MQTT_HOST", "mqtt-broker"),
    port=int(os.getenv("MQTT_PORT", 1883)),
    keepalive=60,
    reconnect_retries=-1,
    reconnect_delay=5,
)

# Successful GETs of endpoints that the dashboard and Docker health checks poll
# every few seconds would otherwise bury everything else in `docker logs`
# (and the dashboard's Logs box). Failures are still logged.
QUIET_POLL_PATHS = {"/health", "/capture", "/devices", "/session"}

class QuietPollFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if not isinstance(args, tuple) or len(args) < 5:
            return True
        _client, method, path, _version, status = args[:5]
        return not (method == "GET" and str(path).split("?")[0] in QUIET_POLL_PATHS and int(status) < 400)

logging.getLogger("uvicorn.access").addFilter(QuietPollFilter())

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

# Enabled FASTAPI + MQTT combo. Not mqtt.init_app(app): its startup hook awaits
# the first connect, so a broker that's down at boot would stop the whole API.
# mqtt_supervisor() connects in the background instead.
mqtt = FastMQTT(config=mqtt_config)

# Set by db_supervisor() once the first connection succeeds; None until then
app.state.db = None

async def notify_misc(message: str, msg_type: str) -> None:
    await broadcast_message(misc_manager, message, msg_type)

def env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}

# Robot-done auto stop: the cell PLC pulses PLC_TAG_STOP when the robot
# finishes, and plc_supervisor() stops the recording session -- see
# fast_server/plc_listener.py. Off = button-only, no "plc" health entry.
PLC_AUTO_STOP = env_flag("PLC_AUTO_STOP")
PLC_PATH = os.getenv("PLC_PATH", "192.168.1.103")
PLC_TAG_STOP = os.getenv("PLC_TAG_STOP", "Db_Stop")
PLC_POLL_S = max(0.01, float(os.getenv("PLC_POLL_S", 0.05)))
PLC_RETRY_S = float(os.getenv("PLC_RETRY_S", 1.0))
PLC_FAKE = env_flag("PLC_FAKE")
PLC_FAKE_SPEED = float(os.getenv("PLC_FAKE_SPEED", 1.0))

# Dependency health, served by GET /health -- see fast_server/health.py
health = HealthRegistry(
    ["db", "mqtt", "stack_controller", "tcp", "logs", "backups"] + (["plc"] if PLC_AUTO_STOP else []),
    notify=notify_misc,
)

# How often the health monitor re-checks every dependency (s)
HEALTH_INTERVAL = float(os.getenv("HEALTH_INTERVAL", 10))

# Folder is attached in docker -- Must Match or else pathing errors
BACKUP_DIR = Path(os.getenv("BACKUP_DIR", "/db_backups"))

# Raised by require_db() -- answered as a 503 with the reason
class DatabaseUnavailable(Exception):
    pass

@app.exception_handler(DatabaseUnavailable)
async def database_unavailable_handler(request: Request, exc: DatabaseUnavailable) -> JSONResponse:
    return JSONResponse(status_code=503, content={
        "success": False,
        "error": str(exc),
        "health": health.snapshot()["components"]["db"],
    })

# The DB handle for an endpoint that can't work without it. Raises
# DatabaseUnavailable (-> 503) while the DB hasn't connected yet or the health
# monitor last saw it down.
def require_db() -> DatabaseSingleton:
    db = app.state.db
    if db is None or health.components["db"]["status"] == "down":
        raise DatabaseUnavailable(f"Database unavailable: {health.describe('db')}")
    return db

def describe_exc(e: BaseException) -> str:
    text = str(e).strip()
    return f"{type(e).__name__}: {text}" if text else type(e).__name__

# A DB error with where we were connecting to, e.g. "can't reach 192.168.1.104:5433:
# no answer within 5s (host down or unreachable?)"
def describe_db_error(e: BaseException) -> str:
    target = f"{os.getenv('DB_HOST')}:{os.getenv('DB_PORT')}"
    if isinstance(e, (asyncio.TimeoutError, TimeoutError)):
        reason = f"no answer within {os.getenv('DB_CONNECT_TIMEOUT', '5')}s (host down or unreachable?)"
    else:
        reason = describe_exc(e)
    return f"can't reach {target}: {reason}"

# Errors that mean "the DB is unreachable", as opposed to a bad request
def is_db_connection_error(e: BaseException) -> bool:
    return isinstance(e, (DatabaseUnavailable, OSError, asyncio.TimeoutError, TimeoutError,
                          asyncpg.PostgresConnectionError, asyncpg.InterfaceError,
                          asyncpg.CannotConnectNowError))

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

# Most rows a worker holds while inserts fail (DB down); older rows are dropped
# beyond this. Failures are reported at most every BACKLOG_REPORT_INTERVAL s.
MAX_BACKLOG_ROWS = int(os.getenv("MAX_BACKLOG_ROWS", queue_size))
BACKLOG_REPORT_INTERVAL = float(os.getenv("BACKLOG_REPORT_INTERVAL", 10))

# Per-worker state while its inserts are failing: since, last_report, dropped
insert_failures: dict[str, dict[str, float]] = {}

# A session stopped while the DB was unreachable: (session_id, stopped_at),
# ended in the DB by apply_pending_session_end() once it's back
pending_session_end: tuple[int, float] | None = None

# Held for the whole of a session start or stop, so the Stop button, the PLC
# and a start can't interleave (e.g. two stops ending a session and taking two
# backups)
session_lock = asyncio.Lock()

# (session_id, time.monotonic(), reason) of the last successful stop. A Stop
# click within ALREADY_STOPPED_WINDOW s of it, with nothing recording since, is
# answered "already stopped" instead of failing on "no open session".
last_stop: tuple[int | None, float, str | None] | None = None
ALREADY_STOPPED_WINDOW = 30.0

# Started by startup() when PLC_AUTO_STOP is on
plc_watcher: PLCSignalWatcher | None = None

# Swarm stacks brought up/down together with each session, via stack-controller
MANAGED_STACKS = [s.strip() for s in os.getenv("MANAGED_STACKS", "edge").split(",") if s.strip()]

# Edge-stack settings per capture mode, sent with each deploy (stack-controller
# only accepts the variables a stack lists under env_overrides in stacks.yml).
# Monitoring streams right away; in a recording session the IMU nodes wait for
# the PLC's Data_Start pulse before sending (IMU_PLC_TRIGGER on the edge node).
# IMU_PLC_TRIGGER_ON_RECORD=false records without waiting, e.g. with no robot.
MONITOR_STACK_ENV = {"IMU_PLC_TRIGGER": "false"}
RECORD_STACK_ENV = {"IMU_PLC_TRIGGER": "true" if env_flag("IMU_PLC_TRIGGER_ON_RECORD", True) else "false"}

# Attempts to create a backup of DB and returns a status code of whether it was successful or not
async def try_backup() -> dict[str, Any]:

    await broadcast_message(misc_manager, "DB Backup Started")

    try:
        db = require_db()
        # backup_path = db.create_backup()
        backup_path = await db.create_backup()
        await broadcast_message(misc_manager, "DB Backup Completed")
        loggers.log_event(f"DB backup written to {backup_path}", category="backup")

        return {
            "success": True,
            "path": backup_path
        }
    except Exception as e:

        # Messages
        await broadcast_message(misc_manager, f"Failed to backup DB: {e}", "error")
        loggers.log_event(f"Failed to backup DB: {e}", category="backup", level=logging.ERROR)

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

    files = []

    # List all files
    try:
        for file in BACKUP_DIR.iterdir():
            if file.is_file():
              files.append(file.name)
    except OSError as e:
        return JSONResponse(status_code=503, content={
            "files": [], "success": False, "error": f"Backup folder {BACKUP_DIR} unavailable: {e}"})

    return {"files": files}

# API that starts a backup
@app.get("/backup")
async def backup() -> dict[str, Any]:
  require_db()
  return await try_backup()

# API to attempt to restore a backup
@app.post("/backup/restore/{filename}")
async def restore_backup(filename: str) -> dict[str, Any]:

    db = require_db()

    try:

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
  db = require_db()
  try:
    data = await db.retrieve_sessions()

    return {"data": data, "success": True}
  except Exception as e:
    loggers.log_system_logger(f"Failed to pull sessions: {e}", True)
    await broadcast_message(misc_manager, f"Failed to pull sessions: {e}", "error")

    return {"error": str(e), "success": False}

# API to get the registered session label categories, for the start-session dropdown
@app.get("/session/labels")
async def get_session_labels() -> dict[str, Any]:
    db = require_db()
    try:
        data = await db.get_session_labels()

        return {"data": data, "success": True}
    except Exception as e:
        loggers.log_system_logger(f"Failed to pull session labels: {e}", True)
        await broadcast_message(misc_manager, f"Failed to pull session labels: {e}", "error")

        return {"error": str(e), "success": False}

# API to get the current active session if available
@app.get("/session")
async def get_running_session() -> dict[str, Any]:

    # DB unreachable: answer from the capture state (what's actually recording)
    # rather than failing the dashboard's status poll
    if app.state.db is None or health.components["db"]["status"] == "down":
        sess_id = capture.session_id if capture.mode in (CaptureMode.RECORD, CaptureMode.STOPPING) else None
        return {"id": sess_id if sess_id is not None else -404, "data": sess_id is not None,
                "success": True, "degraded": True, "error": health.describe("db")}

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

  db = require_db()
  try:
    data = await db.retrieve_imu(label)

    return {"data": data, "success": True}
  except Exception as e:
    loggers.log_system_logger(f"Failed to pull IMU data from session '{label}': {e}", True)
    await broadcast_message(misc_manager, f"Failed to pull IMU data from session {label}: {e}", "error")

    return {"error": str(e), "success": False}

# API to get a JSON of historical CAMERA data from a session label
@app.get("/camera/{label}")
async def get_camera(label: str) -> dict[str, Any]:

  db = require_db()
  try:
    data = await db.retrieve_camera(label)

    return {"data": data, "success": True}
  except Exception as e:
    loggers.log_system_logger(f"Failed to pull CAMERA data from session '{label}': {e}", True)
    await broadcast_message(misc_manager, f"Failed to pull CAMERA data from session {label}: {e}", "error")

    return {"error": str(e), "success": False}

# API to get a JSON of historical ROBOT data from a session label
@app.get("/robot/{label}")
async def get_robot(label: str) -> dict[str, Any]:

  db = require_db()
  try:
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

# Deploys/removes one Swarm stack; services limits a deploy to those services,
# env sets stack variables for this deploy (MONITOR_STACK_ENV/RECORD_STACK_ENV)
async def call_stack_controller(action: str, stack: str, services: list[str] | None = None,
                                env: dict[str, str] | None = None) -> dict[str, Any]:
    body = {}
    if services is not None:
        body["services"] = services
    if env:
        body["env"] = env
    return await stack_controller_request("POST", f"/stacks/{stack}/{action}", body or None)

# Deploys every stack in MANAGED_STACKS, returns {stack_name: result}. With a
# plan ({stack: [services]}, from resolve_selection), only those services run;
# a stack with none selected is removed instead, so it doesn't keep publishing.
# env is passed through to every deploy (see MONITOR_STACK_ENV).
async def deploy_managed_stacks(plan: dict[str, list[str]] | None = None,
                                env: dict[str, str] | None = None) -> dict[str, dict[str, Any]]:

    async def deploy_one(stack: str) -> dict[str, Any]:
        services = plan.get(stack) if plan is not None else None
        if services == []:
            result = await call_stack_controller("remove", stack)
            if not result.get("success"):
                loggers.log_system_logger(f"Could not remove unselected stack '{stack}': {result.get('error')}", True)
            return {"success": True, "skipped": True}
        return await call_stack_controller("deploy", stack, services, env)

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

    deploy_results = await deploy_managed_stacks(plan, MONITOR_STACK_ENV)
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
    async with session_lock:
        return await _start_session(label, session_label, is_test_session, devices)

async def _start_session(
    label: str,
    session_label: str,
    is_test_session: bool,
    devices: list[str] | None,
) -> dict[str, Any]:

    # A session is a DB row -- refuse (503) before touching stacks or the gate
    require_db()

    # Create new logs for this new session only
    loggers.create_loggers()

    # Set once this call opens the gate, so a failure only closes a gate it opened
    # (not one belonging to a session that was already recording)
    opened_gate = False

    # Monitoring already has the edge stacks up, so recording just flips the gate
    # -- unless the selection changed, or the stacks need different settings
    # (IMU_PLC_TRIGGER), which redeploys and restarts just the affected services
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

        loggers.log_event(f"Session {session_id} started: {label} (type: {session_label}, "
                          f"devices: {', '.join(sorted(selected)) if selected else 'all'})",
                          category="session", session_id=session_id)
        loggers.cur_camera_logger.info(f"Camera session ready with label: {label}")
        loggers.cur_imu_logger.info(f"IMU session ready with label: {label}")
        loggers.cur_robot_logger.info(f"Robot session ready with label: {label}")

        await broadcast_message(misc_manager, "Session started with logs successfully")

        # Session row exists now, so open the gate before bringing the edge-node
        # stacks online -- their first published messages will be stored.
        await set_capture(CaptureMode.RECORD, session_id=session_id, devices=selected)
        opened_gate = True

        if was_monitoring and selected == monitored_devices and RECORD_STACK_ENV == MONITOR_STACK_ENV:
            deploy_results = {}
        else:
            deploy_results = await deploy_managed_stacks(plan, RECORD_STACK_ENV)
        failed_stacks = [name for name, result in deploy_results.items() if not result.get("success")]

        if failed_stacks:
            for name in failed_stacks:
                err = deploy_results[name].get("error")
                loggers.log_system_logger(f"Failed to deploy '{name}' stack: {err}", True)
                await broadcast_message(misc_manager, f"Failed to deploy '{name}' stack: {err}", "error")

            # Block: a session with no running stacks won't receive any data, so roll it back.
            # Coming from monitoring, its stacks are still up, so go back to that.
            if was_monitoring:
                await set_capture(CaptureMode.MONITOR, devices=monitored_devices)
            else:
                await set_capture(CaptureMode.IDLE)
            try:
                await db.end_session()
            except Exception as rollback_err:
                loggers.log_system_logger(f"Failed to roll back session after stack deploy failure: {rollback_err}", True)

            return {
                "error": f"Failed to deploy stack(s): {', '.join(failed_stacks)}",
                "success": False,
            }

        # The IMU nodes only see a Data_Start that comes after they've
        # (re)started, so the robot has to wait for them
        if RECORD_STACK_ENV["IMU_PLC_TRIGGER"] == "true" and (
            selected is None or any(key.startswith("imu/") for key in selected)
        ):
            await broadcast_message(misc_manager, "IMUs are (re)starting to wait for the robot's PLC Data_Start -- "
                                                  "start the robot once they show as running", "info")

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

        loggers.log_event(f"Failed to start session '{label}': {e}", category="session", level=logging.ERROR)
        loggers.cur_camera_logger.error(f"Camera session failed to start with label: {label}. Error: {e}")
        loggers.cur_imu_logger.error(f"IMU session failed to start with label: {label}. Error: {e}")
        loggers.cur_robot_logger.error(f"Robot session failed to start with label: {label}. Error: {e}")

        await broadcast_message(misc_manager, f"Failed to start a session with label '{label}': {e}", "error")

        return {"error": str(e), "success": False}

# API to stop a session. Works with the DB down too: the stacks still come
# down and the gate closes; the session row is ended once the DB is back
# (apply_pending_session_end), with the time the stop was requested.
@app.get("/session/stop")
async def stop_session() -> dict[str, Any]:
    async with session_lock:
        # The dashboard learns about a stop it didn't make on its next poll, so a
        # click can land just after the PLC already stopped the session
        if capture.mode == CaptureMode.IDLE and last_stop and time.monotonic() - last_stop[1] < ALREADY_STOPPED_WINDOW:
            session_id, _at, reason = last_stop
            because = f" ({reason})" if reason else ""
            return {"message": f"Session {session_id} was already stopped{because}", "success": True, "already_stopped": True}
        return await _stop_session()

# The stop itself, shared by the button (stop_session) and the PLC
# (stop_session_from_plc). Callers hold session_lock. reason, if given, is
# added to the "stopped" log line and dashboard message.
async def _stop_session(reason: str | None = None) -> dict[str, Any]:
  global pending_session_end, last_stop

  session_id = capture.session_id
  stopped_at = time.time()
  because = f" ({reason})" if reason else ""

  try:

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

    # With the DB down nothing can flush, so don't wait out the drain timeout
    db_up = app.state.db is not None and health.components["db"]["status"] != "down"
    drained, still_buffered = await drain_queues() if db_up else (False, ["imu", "camera", "robot"])
    if not drained and db_up:
        loggers.log_system_logger(f"Timed out waiting for queue(s) to drain before stopping session: {', '.join(still_buffered)}", True)
        await broadcast_message(misc_manager, f"Warning: stopping session with data still buffered in: {', '.join(still_buffered)}", "error")

    try:
        await require_db().end_session()
    except Exception as e:
        if not is_db_connection_error(e) or session_id is None:
            raise
        pending_session_end = (session_id, stopped_at)
        await set_capture(CaptureMode.IDLE)

        msg = (f"Session {session_id} stopped{because}, but the database is unreachable ({describe_exc(e)}). "
               f"Its end time will be saved when the database is back; rows still buffered were not stored.")
        loggers.log_event(msg, category="session", level=logging.WARNING, session_id=session_id)
        await broadcast_message(misc_manager, msg, "error")
        last_stop = (session_id, time.monotonic(), reason)

        return {
            "message": msg,
            "success": True,
            "degraded": True,
            "backup": {"success": False, "error": "Skipped: database unreachable"},
            "stack_removal_failed": failed_stacks or None,
        }

    await set_capture(CaptureMode.IDLE)

    loggers.log_event(f"Session {session_id} stopped{because}", category="session", session_id=session_id)
    loggers.cur_camera_logger.info(f"Camera session ended.")
    loggers.cur_imu_logger.info(f"IMU session ended.")
    loggers.cur_robot_logger.info(f"Robot session ended.")

    await broadcast_message(misc_manager, f"Session ended with logs successfully{because}")

    msg = await try_backup()
    last_stop = (session_id, time.monotonic(), reason)

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

    loggers.log_event(f"Failed to stop the current session: {e}", category="session", level=logging.ERROR)
    loggers.cur_camera_logger.error(f"Camera session failed to stop. Error: {e}")
    loggers.cur_imu_logger.error(f"IMU session failed to stop. Error: {e}")
    loggers.cur_robot_logger.error(f"Robot session failed to stop. Error: {e}")

    await broadcast_message(misc_manager, f"Failed to stop the current session: {e}", "error")

    return {"error": str(e), "success": False}

# Ends a session whose stop was requested while the DB was down. Called on
# every DB (re)connect; a failure keeps it pending for the next one.
async def apply_pending_session_end() -> None:
    global pending_session_end

    if pending_session_end is None or app.state.db is None:
        return

    session_id, stopped_at = pending_session_end
    try:
        await app.state.db.end_session_at(session_id, stopped_at)
    except Exception as e:
        loggers.log_event(f"Still can't save the end of session {session_id}: {describe_exc(e)}",
                          category="session", level=logging.WARNING, important=False, session_id=session_id)
        return

    pending_session_end = None
    msg = f"Saved the end of session {session_id} (stopped while the database was down)"
    loggers.log_event(msg, category="session", session_id=session_id)
    await broadcast_message(misc_manager, msg, "info")

# Starts the PLC watcher thread and the task that reacts to its pulses
def start_plc_listener() -> None:
    global plc_watcher

    plc_watcher = PLCSignalWatcher(
        build_plc_factory(PLC_PATH, fake=PLC_FAKE, fake_speed=PLC_FAKE_SPEED),
        tags=(PLC_TAG_STOP,),
        poll_s=PLC_POLL_S,
        retry_delay_s=PLC_RETRY_S,
    )
    plc_watcher.start()
    start_background(run_forever("plc_supervisor", plc_supervisor))
    loggers.log_event(f"Watching PLC {PLC_PATH}{' (fake)' if PLC_FAKE else ''} tag {PLC_TAG_STOP}: "
                      f"a pulse stops the recording session", category="system")

# Checks the watcher's pulse count every 0.1 s. The watcher thread does the
# counting, so a pulse can't slip by between two checks here.
async def plc_supervisor() -> None:
    seen = plc_watcher.count(PLC_TAG_STOP)
    while True:
        await asyncio.sleep(0.1)
        count = plc_watcher.count(PLC_TAG_STOP)
        if count != seen:
            seen = count
            await stop_session_from_plc()

# The robot finished: stop the session exactly as the Stop button does. Only a
# recording session is stopped -- monitoring and idle ignore the pulse, and so
# does a start or stop already in progress (a pulse during a start belongs to
# the robot's previous run, not the session being started).
async def stop_session_from_plc() -> dict[str, Any] | None:
    session_id = capture.session_id

    if session_lock.locked() or capture.mode != CaptureMode.RECORD:
        state = "a session start/stop is in progress" if session_lock.locked() else f"capture is {capture.mode.value}"
        loggers.log_event(f"PLC {PLC_TAG_STOP} pulse ignored ({state})", category="session", important=False)
        return None

    # Free and checked above with no await in between, so this can't block
    async with session_lock:
        loggers.log_event(f"PLC {PLC_TAG_STOP} pulse (robot finished): stopping session {session_id}",
                          category="session", session_id=session_id)
        await broadcast_message(misc_manager, f"Robot finished (PLC {PLC_TAG_STOP}): stopping session {session_id}", "info")
        return await _stop_session(reason=f"robot finished, PLC {PLC_TAG_STOP}")

# Background tasks started at boot -- kept referenced so they aren't GC'd
_background_tasks: set[asyncio.Task] = set()

def start_background(coro) -> asyncio.Task:
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return task

# Runs a long-lived loop and restarts it (with backoff) if it ever raises, so a
# bug or a dropped connection can't silently kill a worker for good
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

# FastAPI Startup -- returns immediately. The DB and MQTT broker are connected
# by background supervisors that retry with backoff, so the API (and the
# dashboard behind it) is up even while either is unreachable.
@app.on_event("startup")
async def startup():

    # Creates the loggers instances to be ready
    loggers.create_loggers()
    loggers.log_event("fastapi-app starting", category="system")

    # Idle until the DB says otherwise. Always set() so the version is fresh --
    # tcp_server may still hold a RECORD state from before a restart.
    await set_capture(CaptureMode.IDLE)

    start_background(db_supervisor())
    start_background(mqtt_supervisor())
    if PLC_AUTO_STOP:
        start_plc_listener()
    start_background(health_monitor())

# Connects to the DB, retrying with backoff until it works, then resumes an
# open session and starts the IMU/camera workers. Later outages are spotted by
# health_monitor(); asyncpg's pool reconnects on its own once the DB is back.
async def db_supervisor() -> None:
    attempt = 0
    while True:
        attempt += 1
        try:
            db = await DatabaseSingleton.get_instance()
            break
        except Exception as e:
            delay = backoff_delay(attempt)
            reason = describe_db_error(e)
            loggers.log_event(f"DB connect attempt {attempt} failed: {reason} -- retrying in {delay}s",
                              category="health", level=logging.WARNING, important=False, component="db")
            await health.down("db", reason, attempts=attempt, retry_in=delay,
                              host=os.getenv("DB_HOST"), port=os.getenv("DB_PORT"))
            await asyncio.sleep(delay)

    app.state.db = db
    await health.ok("db", host=os.getenv("DB_HOST"), port=os.getenv("DB_PORT"))

    await apply_pending_session_end()
    await restore_capture()

    # Creates workers for IMU and CAMERA
    batch_size = int(os.getenv("BATCHES", 50))
    flush_interval = float(os.getenv("B_TIMEOUT", 2.0))
    start_background(run_forever("camera_worker", lambda: camera_worker(batch_size=batch_size, flush_interval=flush_interval)))
    start_background(run_forever("imu_worker", lambda: imu_worker(batch_size=batch_size, flush_interval=flush_interval)))

# Makes the first MQTT connection, retrying with backoff. After that gmqtt
# reconnects by itself (reconnect_retries=-1); this loop only reports status.
async def mqtt_supervisor() -> None:
    attempt = 0
    connected_once = False
    target = f"{mqtt_config.host}:{mqtt_config.port}"

    while True:
        if mqtt.client.is_connected:
            connected_once = True
            attempt = 0
            await health.ok("mqtt", broker=target, topics=sorted(mqtt.subscriptions))
            await asyncio.sleep(5)
            continue

        attempt += 1
        if connected_once:
            await health.down("mqtt", f"connection to {target} lost, reconnecting", attempts=attempt, broker=target)
            await asyncio.sleep(5)
            continue

        try:
            await asyncio.wait_for(mqtt.mqtt_startup(), timeout=10)
        except Exception as e:
            delay = backoff_delay(attempt)
            loggers.log_event(f"MQTT connect attempt {attempt} to {target} failed: {describe_exc(e)} -- retrying in {delay}s",
                              category="health", level=logging.WARNING, important=False, component="mqtt")
            await health.down("mqtt", f"can't connect to {target}: {describe_exc(e)}", attempts=attempt,
                              retry_in=delay, broker=target)
            await asyncio.sleep(delay)

def _probe_backup_dir() -> str:
    probe = BACKUP_DIR / f".health-{os.getpid()}"
    probe.write_text("ok")
    probe.unlink()
    return str(BACKUP_DIR)

_backup_probe = PathProbe(_probe_backup_dir, timeout=5)

# Re-checks every dependency each HEALTH_INTERVAL s and records the result
async def health_monitor() -> None:

    async def check_db() -> None:
        db = app.state.db
        if db is None:
            return  # db_supervisor reports until the first connect
        try:
            await asyncio.wait_for(db.pool.fetchval("SELECT 1"), timeout=3)
        except Exception as e:
            await health.down("db", describe_db_error(e), retry_in=HEALTH_INTERVAL,
                              host=os.getenv("DB_HOST"), port=os.getenv("DB_PORT"))
            return
        was_down = health.components["db"]["status"] == "down"
        await health.ok("db", host=os.getenv("DB_HOST"), port=os.getenv("DB_PORT"))
        if was_down:
            await apply_pending_session_end()

    async def check_stack_controller() -> None:
        host = os.getenv("STACK_CONTROLLER_HOST", "stack-controller")
        port = os.getenv("STACK_CONTROLLER_PORT", "8080")
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"http://{host}:{port}/health", timeout=aiohttp.ClientTimeout(total=3)) as resp:
                    if resp.status != 200:
                        raise RuntimeError(f"/health returned {resp.status}")
        except Exception as e:
            await health.down("stack_controller", f"{host}:{port} unreachable: {describe_exc(e)}", retry_in=HEALTH_INTERVAL)
            return
        await health.ok("stack_controller")

    async def check_tcp() -> None:
        status = await get_robot_queue_status()
        if "error" in status:
            await health.down("tcp", f"tcp status server unreachable: {status['error']}", retry_in=HEALTH_INTERVAL)
            return
        tcp_db = status.get("db") or {}
        if tcp_db.get("status") == "down":
            await health.down("tcp", f"tcp can't reach the database: {tcp_db.get('error')}",
                              retry_in=HEALTH_INTERVAL, connections=status.get("connections"))
            return
        await health.ok("tcp", connections=status.get("connections"), depth=status.get("depth"))

    async def check_logs() -> None:
        status = loggers.file_logging_status()
        if status["ok"]:
            await health.ok("logs", dir=status["dir"], dropped=status["dropped"])
        else:
            await health.down("logs", f"can't write {status['dir']}, logging to stdout only: {status['error']}",
                              dir=status["dir"], dropped=status["dropped"])

    async def check_backups() -> None:
        try:
            await _backup_probe.run()
        except Exception as e:
            await health.down("backups", f"backup folder {BACKUP_DIR} not writable: {describe_exc(e)}",
                              retry_in=HEALTH_INTERVAL)
            return
        await health.ok("backups", dir=str(BACKUP_DIR))

    async def check_plc() -> None:
        if plc_watcher is None:
            return
        snap = plc_watcher.snapshot()
        detail = dict(path=PLC_PATH, tag=PLC_TAG_STOP, value=snap["values"][PLC_TAG_STOP],
                      pulses=snap["counts"][PLC_TAG_STOP], fake=PLC_FAKE)
        age = snap["last_read_age_s"]
        if not snap["connected"]:
            if plc_watcher.last_error is None:
                return  # first connect still in progress
            await health.down("plc", f"can't reach PLC at {PLC_PATH}: {plc_watcher.last_error}",
                              retry_in=PLC_RETRY_S, **detail)
        elif age is not None and age > max(5.0, PLC_POLL_S * 50):
            await health.down("plc", f"no answer from PLC at {PLC_PATH} for {age:g}s", **detail)
        elif plc_watcher.tag_errors:
            await health.down("plc", f"PLC tag problem: {plc_watcher.tag_errors}", **detail)
        else:
            await health.ok("plc", **detail)

    checks = (check_db, check_stack_controller, check_tcp, check_logs, check_backups, check_plc)
    while True:
        results = await asyncio.gather(*(check() for check in checks), return_exceptions=True)
        for check, result in zip(checks, results):
            if isinstance(result, Exception):
                loggers.log_event(f"Health check {check.__name__} failed: {describe_exc(result)}",
                                  category="health", level=logging.ERROR, important=False)
        await asyncio.sleep(HEALTH_INTERVAL)

# Liveness + dependency report. Always 200 while the process is alive (it's
# also the container healthcheck); "overall" is ok/degraded/starting.
@app.get("/health")
async def get_health() -> dict[str, Any]:
    return {
        **health.snapshot(),
        "capture": capture.to_dict(),
        "pending_session_end": pending_session_end[0] if pending_session_end else None,
        "backlog": {
            name: {"since": f["since"], "dropped": f["dropped"]} for name, f in insert_failures.items()
        },
    }

# Sets the capture state from the DB: RECORD if a session is open, else IDLE.
# Skipped if monitoring was started while the DB was still unreachable.
async def restore_capture() -> None:
    try:
        session_id = await app.state.db.get_latest_session()
    except Exception as e:
        loggers.log_system_logger(f"Could not check for an open session at startup: {e}", True)
        session_id = None

    if capture.mode == CaptureMode.MONITOR:
        if session_id:
            loggers.log_event(f"Session {session_id} is still open in the database, but monitoring started while "
                              f"the database was down; leaving monitor mode as is -- stop it from the dashboard if it's stale",
                              category="session", level=logging.WARNING, session_id=session_id)
        return

    if session_id:
        try:
            devices = await app.state.db.get_session_devices(session_id)
        except Exception as e:
            # Fail open to every device rather than dropping a live session's data
            loggers.log_system_logger(f"Could not read device selection for session {session_id}: {e}", True)
            devices = None
        await set_capture(CaptureMode.RECORD, session_id=session_id, devices=devices)
        loggers.log_event(f"Resumed recording session {session_id} (was open at startup)",
                          category="session", session_id=session_id)
    else:
        await set_capture(CaptureMode.IDLE)

# FastAPI Shutdown
@app.on_event("shutdown")
async def shutdown_event():
    loggers.log_event("fastapi-app shutting down", category="system")
    if plc_watcher is not None:
        await asyncio.to_thread(plc_watcher.close)
    try:
        await mqtt.mqtt_shutdown()
    except Exception:
        pass
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
        now = time.time()
        failing = insert_failures.setdefault(name, {"since": now, "last_report": 0.0, "dropped": 0})
        # One report per BACKLOG_REPORT_INTERVAL, not one per retry
        if now - failing["last_report"] >= BACKLOG_REPORT_INTERVAL:
            failing["last_report"] = now
            msg = (f"{name} inserts failing for {describe_age(now - failing['since'])} ({describe_exc(e)}) -- "
                   f"holding {len(batch)} rows" + (f", dropped {failing['dropped']}" if failing["dropped"] else ""))
            logger.error(msg)
            loggers.log_event(msg, category="ingest", level=logging.ERROR, worker=name,
                              rows_held=len(batch), dropped=failing["dropped"])
            await broadcast_message(manager, msg, "error")
        return False

    failing = insert_failures.pop(name, None)
    if failing:
        msg = (f"{name} inserts recovered after {describe_age(time.time() - failing['since'])}"
               + (f" ({failing['dropped']} rows dropped while failing)" if failing["dropped"] else ""))
        loggers.log_event(msg, category="ingest", worker=name, dropped=failing["dropped"])
        await broadcast_message(manager, msg, "info")

    logger.info(f"Inserted {len(current)} {name} rows")
    await broadcast_message(manager, f"Inserted {len(current)} {name} rows")
    return True

# Keeps a failing worker's batch at MAX_BACKLOG_ROWS by dropping the oldest rows
def trim_backlog(batch: list, name: str, logger) -> None:
    overflow = len(batch) - MAX_BACKLOG_ROWS
    if overflow > 0:
        del batch[:overflow]
        failing = insert_failures.setdefault(name, {"since": time.time(), "last_report": 0.0, "dropped": 0})
        failing["dropped"] += overflow
        logger.warning(f"{name} backlog over {MAX_BACKLOG_ROWS} rows, dropped the oldest {overflow}")

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
                trim_backlog(batch, "CAMERA", loggers.cur_camera_logger)
                camera_pending = len(batch)
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
                trim_backlog(batch, "IMU", loggers.cur_imu_logger)
                imu_pending = len(batch)
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
