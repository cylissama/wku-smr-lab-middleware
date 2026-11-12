# The wire format between a camera Pi (camera_edge with CAMERA_PROCESSING=remote)
# and camera-processor. Both ends must agree on it; the Pi-side copy lives in
# the camera edge repo at camera_edge/frame_forwarder.py, so change both
# together and bump VERSION. Design: plans/camera-offload-plan.md.
#
# Topics, under CAMERA_FRAME_TOPIC_PREFIX (default "camera_frames"; it must not
# be "camera", which fastapi-app ingests as marker rows):
#
#   camera_frames/<device>/config   retained JSON, published by the Pi on every
#                                   (re)connect: calibration + detection settings
#   camera_frames/<device>/frame    one camera frame, binary (below)
#
# <device> is the device key without its category, <DEVICE_ID>_<CAMERA_NAME>
# (e.g. 113_cam1), the same as the smr.device label and the output topic
# camera/113_cam1.
#
# A frame payload is
#
#   4 bytes   big-endian length N of the header
#   N bytes   UTF-8 JSON header: {"v", "device_id", "camera_name", "run_id",
#             "frame_idx", "capture_time_ms", "sent_at_ms"}
#   the rest  the JPEG exactly as camera_host encoded it (never re-encoded)

import json
import struct

VERSION = 1
DEFAULT_PREFIX = "camera_frames"

FRAME = "frame"
CONFIG = "config"

_LEN = struct.Struct(">I")
# A header is a few hundred bytes; anything larger is a corrupt or foreign payload.
MAX_HEADER_BYTES = 64 * 1024

FRAME_HEADER_FIELDS = ("device_id", "camera_name", "run_id", "frame_idx", "capture_time_ms")


class ProtocolError(ValueError):
    pass


def device_label(device_id, camera_name) -> str:
    return f"{device_id}_{camera_name}"


def frame_topic(prefix: str, label: str) -> str:
    return f"{prefix}/{label}/{FRAME}"


def config_topic(prefix: str, label: str) -> str:
    return f"{prefix}/{label}/{CONFIG}"


def subscription(prefix: str) -> str:
    return f"{prefix}/+/+"


def parse_topic(topic: str, prefix: str) -> tuple[str, str]:
    """camera_frames/113_cam1/frame -> ("113_cam1", "frame")."""
    parts = topic.split("/")
    if len(parts) != 3 or parts[0] != prefix or not parts[1] or parts[2] not in (FRAME, CONFIG):
        raise ProtocolError(f"not a camera frame topic: {topic!r}")
    return parts[1], parts[2]


def encode_frame(header: dict, jpeg: bytes) -> bytes:
    raw = json.dumps({"v": VERSION, **header}, separators=(",", ":")).encode("utf-8")
    return _LEN.pack(len(raw)) + raw + bytes(jpeg)


def decode_frame(payload: bytes) -> tuple[dict, bytes]:
    if len(payload) < _LEN.size:
        raise ProtocolError("frame payload too short")
    (n,) = _LEN.unpack_from(payload, 0)
    if n > MAX_HEADER_BYTES or _LEN.size + n > len(payload):
        raise ProtocolError(f"bad frame header length {n}")
    try:
        header = json.loads(payload[_LEN.size:_LEN.size + n].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ProtocolError(f"frame header is not JSON: {error}") from error
    if not isinstance(header, dict):
        raise ProtocolError("frame header is not an object")
    if header.get("v") != VERSION:
        raise ProtocolError(f"unsupported frame version {header.get('v')!r} (expected {VERSION})")
    missing = [f for f in FRAME_HEADER_FIELDS if f not in header]
    if missing:
        raise ProtocolError(f"frame header missing {', '.join(missing)}")
    jpeg = bytes(payload[_LEN.size + n:])
    if not jpeg:
        raise ProtocolError("frame has no image")
    return header, jpeg


def encode_config(config: dict) -> bytes:
    return json.dumps({"v": VERSION, **config}).encode("utf-8")


def decode_config(payload: bytes) -> dict:
    try:
        config = json.loads(bytes(payload).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ProtocolError(f"camera config is not JSON: {error}") from error
    if not isinstance(config, dict):
        raise ProtocolError("camera config is not an object")
    if config.get("v") != VERSION:
        raise ProtocolError(f"unsupported config version {config.get('v')!r} (expected {VERSION})")
    for field in ("device_id", "camera_name", "camera_matrix", "dist_coeffs", "marker_length_m"):
        if field not in config:
            raise ProtocolError(f"camera config missing {field}")
    return config
