"""
Minimal stand-in for fast_server.connection_manager, just for standalone
testing of database.py / mqtt_server.py. Replace with the real package
once you have access to it.
"""

misc_manager = object()


async def broadcast_message(manager, msg, level="info"):
    print(f"[broadcast:{level}] {msg}")