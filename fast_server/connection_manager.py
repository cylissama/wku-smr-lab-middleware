from fastapi import WebSocket
from datetime import datetime, timezone
from typing import List
from zoneinfo import ZoneInfo
import json

# Global method to get the time -- Uses system or container time -- Returns American timezone time
def get_time():
    try:
        unix_time = datetime.now(timezone.utc).timestamp()
        dt = datetime.fromtimestamp(unix_time, tz=ZoneInfo("UTC"))

        return dt.astimezone(ZoneInfo("America/Chicago")).strftime("%Y-%m-%d %I:%M:%S %p %Z")


    except(ValueError, IOError) as e:
        print(f"Error: {e}")
        return None


# Connection class for webhooks (device message for web interface)
class ConnectionManager:

    def __init__(self):
        self.active: List[WebSocket] = []

    # Webhook connect
    async def connect(self, ws: WebSocket):

        await ws.accept()
        self.active.append(ws)

    # Webhook Disconnect
    def disconnect(self, ws: WebSocket):

        if ws in self.active:
            self.active.remove(ws)

    # Send message from source to web interface
    async def broadcast_json(self, payload: dict):

        payload = payload.copy()
        payload["timestamp"] = get_time()

        msg = json.dumps(payload)
        for ws in self.active:
            try:
                await ws.send_text(msg)
            except Exception:
                self.disconnect(ws)

# Global managers for use in other scripts
camera_manager = ConnectionManager()
imu_manager = ConnectionManager()
robot_manager = ConnectionManager()
misc_manager = ConnectionManager()

MANAGERS = {
    "camera": camera_manager,
    "imu": imu_manager,
    "robot": robot_manager,
    "misc": misc_manager
}

# Helper method that sends a message to be pushed onto the web interface
async def broadcast_message(manager, msg:str, msg_type:str = "normal") -> None:

    await manager.broadcast_json({
        "type": msg_type,
        "text": msg
    })