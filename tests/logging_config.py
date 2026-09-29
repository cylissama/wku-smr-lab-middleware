import logging
import sys

# Global logger name so every script refers to the same logger
LOGGER_NAME = "system_test"

def get_logger():
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.DEBUG)

    if not logger.handlers:
        # Console handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(logging.Formatter(
            "[%(asctime)s] [%(levelname)s] [%(threadName)s] %(message)s",
            "%H:%M:%S"
        ))
        logger.addHandler(console_handler)

    return logger


# Shared global logger instance
logger = get_logger()


# ---- Optional color codes ----
class Color:
    IMU = "\033[94m"      # Blue
    CAM = "\033[93m"      # Yellow
    ROBOT = "\033[92m"    # Green
    END = "\033[0m"

def colorize(device_type: str, msg: str) -> str:
    if "IMU" in device_type:
        return f"{Color.IMU}{msg}{Color.END}"
    if "Camera" in device_type or "CAM" in device_type:
        return f"{Color.CAM}{msg}{Color.END}"
    if "Robot" in device_type:
        return f"{Color.ROBOT}{msg}{Color.END}"
    return msg