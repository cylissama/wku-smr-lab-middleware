from typing import Any

# Helper method to parse CAMERA messages
def parse_camera_message(topic, payload) -> dict[str, Any]:

    # Get device and topic info -- Topic should be 'IMU/<device_ID>' or similar
    parts = topic.split("/")

    # If more or less parts, raise an error
    if len(parts) != 2:
        raise ValueError(f"Invalid topic: {topic!r}")

    device_label = parts[1]

    # Messages should be in CSV format
    msg = [part.strip() for part in payload.decode().split(",")]

    # If less parts, raise an error
    if len(msg) < 10:
        raise ValueError(f"Expected at least 10 fields, got {len(msg)}")

    return {
            "device_label": device_label,

            "frame_idx": int(msg[0]),
            "capture_time": float(msg[1]),
            "recorded_at": float(msg[2]),
            "marker_idx": int(msg[3]),

            "rvec_x": float(msg[4]), "rvec_y": float(msg[5]), "rvec_z": float(msg[6]),
            "tvec_x": float(msg[7]), "tvec_y": float(msg[8]), "tvec_z": float(msg[9]),

            "image_path": "" # TODO - Remove image path from DB
    }

# Helper method to parse IMU messages
def parse_imu_message(topic, payload) -> dict[str, Any]:

    # Get device and topic info -- Topic should be 'IMU/<device_ID>' or similar
    parts = topic.split("/")

    # If more or less parts, raise an error
    if len(parts) != 2:
        raise ValueError(f"Invalid topic: {topic!r}")

    device_label = parts[1]

    # Messages should be in CSV format
    msg = [part.strip() for part in payload.decode().split(",")]

    # If less parts, raise an error
    if len(msg) < 15:
        raise ValueError(f"Expected at least 15 fields, got {len(msg)}")
    
    # this is in order that msg is received from the IMU device
    return { 
        "device_label": device_label,

        "frame_id": float(msg[0]), #counter
        "capture_time": float(msg[1]),
        "recorded_at": float(msg[2]), #time_ms
        "accel_x": float(msg[3]),
        "accel_y": float(msg[4]),
        "accel_z": float(msg[5]),
        "gyro_x": float(msg[6]),
        "gyro_y": float(msg[7]),
        "gyro_z": float(msg[8]),
        "mag_x": float(msg[9]),
        "mag_y": float(msg[10]),
        "mag_z": float(msg[11]),
        "yaw": float(msg[12]),
        "pitch": float(msg[13]),
        "roll": float(msg[14]),
    }