"""
mqtt_tester.py
Improved IMU and Camera MQTT publishing test utilities.
Compatible with the master test harness.
IMPROVED: Standardized return values and better error tracking
"""

import time
import numpy as np
import pandas as pd
from package.client import Client
from logging_config import logger, colorize


# -----------------------------
# CONFIGURATION
# -----------------------------
BROKER_IP = "192.168.1.76"
BROKER_PORT = 1883


# -----------------------------
# DATA GENERATION HELPERS
# -----------------------------
def create_imu_csv(num_records: int = 1) -> list[str]:
    """
    Generates mock IMU CSV rows.
    Returns list[str] instead of one giant CSV string for speed.
    """
    now = pd.Timestamp.now()
    times_ms = np.arange(num_records) * 10 + int(now.timestamp() * 1000)

    df = pd.DataFrame({
        "time_ms": times_ms,
        "ax": np.random.uniform(-2, 2, num_records),
        "ay": np.random.uniform(-2, 2, num_records),
        "az": np.random.uniform(-2, 2, num_records),
        "gx": np.random.uniform(-180, 180, num_records),
        "gy": np.random.uniform(-180, 180, num_records),
        "gz": np.random.uniform(-180, 180, num_records),
        "mx": np.random.uniform(-50, 50, num_records),
        "my": np.random.uniform(-50, 50, num_records),
        "mz": np.random.uniform(-50, 50, num_records),
        "yaw": np.random.uniform(-180, 180, num_records),
        "pitch": np.random.uniform(-90, 90, num_records),
        "roll": np.random.uniform(-180, 180, num_records)
    })

    return df.to_csv(index=False, header=False).strip().splitlines()


def create_camera_csv(num_records: int = 1) -> list[str]:
    """
    Generates mock Camera CSV rows.
    Returns list[str].
    """
    now = pd.Timestamp.now()
    recorded_at = np.arange(num_records) * 33 + int(now.timestamp() * 1000)

    df = pd.DataFrame({
        "recorded_at": recorded_at,
        "frame_idx": np.arange(num_records),
        "capture_time": recorded_at,
        "marker_idx": np.random.randint(0, 10, num_records),
        "rvecx": np.random.uniform(-3.14, 3.14, num_records),
        "rvecy": np.random.uniform(-3.14, 3.14, num_records),
        "rvecz": np.random.uniform(-3.14, 3.14, num_records),
        "tvecx": np.random.uniform(-100, 100, num_records),
        "tvecy": np.random.uniform(-100, 100, num_records),
        "tvecz": np.random.uniform(0, 500, num_records)
    })
    return df.to_csv(index=False, header=False).strip().splitlines()


# -----------------------------
# FIXED-SCHEDULE SENDER
# -----------------------------
def _send_rows_fixed_interval(client, rows, interval, stop_event, device_type, device_id):
    """
    Sends CSV rows while keeping a **true fixed send interval**.
    Returns (sent_count, error_count).
    """
    errors = 0
    sent = 0

    next_send = time.perf_counter()

    for i, row in enumerate(rows, 1):
        if stop_event and stop_event.is_set():
            logger.info(colorize(device_type, f"[{device_type}] {device_id} stopping at row {i}/{len(rows)}"))
            break

        try:
            client.publish(row)
            sent += 1
            logger.debug(colorize(device_type, f"[{device_type}] {device_id} sent row {i}/{len(rows)}"))
        except Exception as e:
            errors += 1
            logger.error(colorize(device_type, f"[{device_type}] {device_id} error sending row {i}: {e}"))

        # maintain fixed schedule
        next_send += interval
        remaining = next_send - time.perf_counter()
        if remaining > 0:
            time.sleep(remaining)

    return sent, errors


# -----------------------------
# PUBLIC TEST FUNCTIONS
# -----------------------------
def test_imu_client(samples, interval, id, stop_event=None):
    """
    Thread-safe IMU test publisher compatible with master harness.
    
    Args:
        samples: Number of samples to send
        interval: Interval between samples (seconds)
        id: Device identifier
        stop_event: Threading event for graceful shutdown
        
    Returns:
        dict: {
            "samples_sent": int,
            "errors": int,
            "duration_s": float
        }
    """
    device_type = "IMU Client"
    logger.info(colorize(device_type, f"[{device_type}] Starting MQTT test for {id}"))

    client = None
    sent = 0
    errors = 0
    start = time.perf_counter()

    try:
        client = Client(
            broker_ip=BROKER_IP,
            broker_port=BROKER_PORT,
            client_type=Client.IMU,
            device_id=id
        )
        logger.debug(colorize(device_type, f"[{device_type}] {id} connected to broker"))

        rows = create_imu_csv(samples)
        sent, errors = _send_rows_fixed_interval(client, rows, interval, stop_event, device_type, id)

    except Exception as e:
        errors += 1
        logger.error(colorize(device_type, f"[{device_type}] {id} failed to initialize: {e}"))

    finally:
        duration = time.perf_counter() - start

        if client:
            try:
                client.disconnect()
                logger.debug(colorize(device_type, f"[{device_type}] {id} disconnected"))
            except Exception as e:
                logger.warning(colorize(device_type, f"[{device_type}] {id} disconnect error: {e}"))

        logger.info(colorize(device_type, 
            f"[{device_type}] {id} completed: {sent}/{samples} sent, {errors} errors, {duration:.3f}s"))

    return {
        "samples_sent": sent,
        "errors": errors,
        "duration_s": duration
    }


def test_camera_client(samples, interval, id, stop_event=None):
    """
    Thread-safe Camera test publisher compatible with master harness.
    
    Args:
        samples: Number of samples to send
        interval: Interval between samples (seconds)
        id: Device identifier
        stop_event: Threading event for graceful shutdown
        
    Returns:
        dict: {
            "samples_sent": int,
            "errors": int,
            "duration_s": float
        }
    """
    device_type = "Camera Client"
    logger.info(colorize(device_type, f"[{device_type}] Starting MQTT test for {id}"))

    client = None
    sent = 0
    errors = 0
    start = time.perf_counter()

    try:
        client = Client(
            broker_ip=BROKER_IP,
            broker_port=BROKER_PORT,
            client_type=Client.CAMERA,
            device_id=id
        )
        logger.debug(colorize(device_type, f"[{device_type}] {id} connected to broker"))

        rows = create_camera_csv(samples)
        sent, errors = _send_rows_fixed_interval(client, rows, interval, stop_event, device_type, id)

    except Exception as e:
        errors += 1
        logger.error(colorize(device_type, f"[{device_type}] {id} failed to initialize: {e}"))

    finally:
        duration = time.perf_counter() - start

        if client:
            try:
                client.disconnect()
                logger.debug(colorize(device_type, f"[{device_type}] {id} disconnected"))
            except Exception as e:
                logger.warning(colorize(device_type, f"[{device_type}] {id} disconnect error: {e}"))

        logger.info(colorize(device_type, 
            f"[{device_type}] {id} completed: {sent}/{samples} sent, {errors} errors, {duration:.3f}s"))

    return {
        "samples_sent": sent,
        "errors": errors,
        "duration_s": duration
    }


# -----------------------------
# MANUAL RUN
# -----------------------------
if __name__ == "__main__":
    logger.info(colorize("Camera Client", "Manual mode: sending 10 Camera samples"))
    result = test_camera_client(10, 0.1, id="manual_test")
    print(f"\nTest result: {result}")