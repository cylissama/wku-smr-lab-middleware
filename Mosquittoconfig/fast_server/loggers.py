"""
Minimal stand-in for the real fast_server.loggers module, just so
mqtt_server.py and database.py can run standalone for testing.
Replace with the real package once you have access to it.
"""
 
 
class _SimpleLogger:
    def info(self, msg):
        print(f"[INFO] {msg}")
 
    def error(self, msg):
        print(f"[ERROR] {msg}")
 
 
cur_robot_logger = _SimpleLogger()
cur_imu_logger = _SimpleLogger()
 
 
def create_loggers():
    print("[stub] create_loggers() called (no-op)")
 
 
def log_system_logger(msg):
    print(f"[SYSTEM] {msg}")
 