import json
import os
from pathlib import Path
from typing import Any

# Settings the dashboard may change between runs (never while recording).
# edge ones go to stack-controller as env overrides for the edge stack, so each
# must also be listed under env_overrides in stack_controller/stacks.yml, and
# their defaults are deploy/.env's values. The others are read by fastapi-app
# itself and default to its own environment (the repo-root .env).
PARAMS: dict[str, dict[str, Any]] = {
    "IMU_SAMPLE_HZ": {
        "label": "IMU sample rate", "group": "imu", "type": "int", "min": 1, "max": 200, "unit": "Hz",
        "edge": True, "help": "Readings per second from every IMU",
    },
    "IMU_PLC_TRIGGER_ON_RECORD": {
        "label": "Wait for PLC start", "group": "imu", "type": "bool", "edge": False,
        "help": "When recording, the IMUs start sending on the PLC's Data_Start. Monitoring never waits.",
    },
    "IMU_PLC_MAX_RUN_S": {
        "label": "Max PLC run", "group": "imu", "type": "int", "min": 30, "max": 3600, "unit": "s",
        "edge": True, "help": "IMUs stop sending if Db_Stop hasn't come by then",
    },
}

EDGE_PARAMS = [key for key, p in PARAMS.items() if p["edge"]]

_TRUE = {"true", "1", "yes", "on"}
_FALSE = {"false", "0", "no", "off"}


# value (from JSON or an env file) checked against PARAMS[key]; raises ValueError
def parse(key: str, value: Any) -> bool | int | float:
    p = PARAMS[key]

    if p["type"] == "bool":
        text = str(value).strip().lower()
        if text not in _TRUE | _FALSE:
            raise ValueError(f"{key} must be true or false")
        return text in _TRUE

    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{key} must be a number")
    if isinstance(value, bool) or (p["type"] == "int" and not number.is_integer()):
        raise ValueError(f"{key} must be a whole number" if p["type"] == "int" else f"{key} must be a number")
    if not p["min"] <= number <= p["max"]:   # also false for NaN
        raise ValueError(f"{key} must be between {p['min']} and {p['max']}")

    return int(number) if p["type"] == "int" else number


# How a value is written into a stack's environment
def env_value(value: bool | int | float) -> str:
    return ("true" if value else "false") if isinstance(value, bool) else str(value)


# Saved overrides, plus a message per entry that was dropped (unknown key, or a
# value no longer valid). A missing file means no overrides.
def load(path: Path) -> tuple[dict[str, Any], list[str]]:
    try:
        raw = json.loads(path.read_text())
    except FileNotFoundError:
        return {}, []
    except (OSError, ValueError) as e:
        return {}, [f"Could not read {path}: {e}"]

    values, problems = {}, []
    for key, value in (raw if isinstance(raw, dict) else {}).items():
        if key not in PARAMS:
            problems.append(f"Ignoring unknown run parameter {key}")
            continue
        try:
            values[key] = parse(key, value)
        except ValueError as e:
            problems.append(f"Ignoring saved {key}: {e}")

    return values, problems


# Written to a temp file and renamed, so a crash mid-write can't leave half a file
def save(path: Path, values: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(values, indent=2, sort_keys=True))
    os.replace(tmp, path)
