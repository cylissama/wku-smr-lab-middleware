import asyncio
import os
import re
import subprocess
import tempfile
from typing import Any

import yaml
from dotenv import dotenv_values
from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel

from stack_controller.auth import verify_token
from stack_controller import docker_ops

app = FastAPI()

STACKS_CONFIG_PATH = os.getenv("STACKS_CONFIG_PATH", "/config/stacks.yml")

# One lock per stack name so a deploy/remove can't overlap itself; created lazily
# since stack names come from the config file rather than being known up front.
_locks: dict[str, asyncio.Lock] = {}


def load_stacks() -> dict[str, Any]:
    with open(STACKS_CONFIG_PATH) as f:
        data = yaml.safe_load(f) or {}
    return data.get("stacks", {})


def get_stack_config(name: str) -> dict[str, Any]:
    stacks = load_stacks()
    if name not in stacks:
        raise HTTPException(404, f"Unknown stack '{name}' (not in stacks.yml)")
    return stacks[name]


# Reads the stack's optional env_file (e.g. /stacks/.env) fresh on every deploy,
# so edits to it apply on the next deploy without restarting this container.
def load_stack_env(name: str, cfg: dict[str, Any]) -> dict[str, str]:
    env_file = cfg.get("env_file")
    if not env_file:
        return {}

    if not os.path.isfile(env_file):
        raise HTTPException(500, f"env_file '{env_file}' for stack '{name}' does not exist")

    return {k: v for k, v in dotenv_values(env_file).items() if v is not None}


# ${VAR} / ${VAR:-default} / ${VAR-default}, the forms docker stack deploy
# interpolates -- used only to read the smr.* labels for the device catalog
_VAR_REF = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::?-([^}]*))?\}")


def interpolate(value: str, env: dict[str, str]) -> str:
    return _VAR_REF.sub(lambda m: env.get(m.group(1)) or (m.group(2) or ""), value)


def load_compose(cfg: dict[str, Any]) -> dict[str, Any]:
    with open(cfg["compose_file"]) as f:
        return yaml.safe_load(f) or {}


def service_labels(spec: dict[str, Any] | None) -> dict[str, str]:
    labels = ((spec or {}).get("deploy") or {}).get("labels") or {}
    if isinstance(labels, list):
        labels = dict(item.split("=", 1) for item in labels if "=" in item)
    return {str(k): str(v) for k, v in labels.items()}


# One entry per service in the stack's compose file, with the device it runs
# (from its smr.category / smr.device deploy labels, interpolated like the
# real deploy would). Services without those labels get None for both.
def list_services(name: str, cfg: dict[str, Any]) -> list[dict[str, Any]]:
    env = {**os.environ, **load_stack_env(name, cfg)}
    services = []

    for service, spec in (load_compose(cfg).get("services") or {}).items():
        labels = service_labels(spec)
        services.append({
            "service": service,
            "category": interpolate(labels.get("smr.category", ""), env) or None,
            "device_label": interpolate(labels.get("smr.device", ""), env) or None,
        })

    return services


# Writes a copy of the stack's compose file containing only the given services
# (everything else -- networks, volumes, x- keys -- kept as is). ${VAR}s are left
# untouched for docker stack deploy to interpolate. Caller deletes the file.
def write_filtered_compose(cfg: dict[str, Any], services: list[str]) -> str:
    compose = load_compose(cfg)
    all_services = compose.get("services") or {}

    unknown = sorted(set(services) - set(all_services))
    if unknown:
        raise HTTPException(400, f"Unknown service(s): {', '.join(unknown)}")

    compose["services"] = {k: v for k, v in all_services.items() if k in services}

    with tempfile.NamedTemporaryFile("w", suffix=".yml", prefix="stack-", delete=False) as f:
        yaml.safe_dump(compose, f, sort_keys=False)
        return f.name


class DeployRequest(BaseModel):
    # Only deploy these services (others in the stack are pruned); omit for all
    services: list[str] | None = None


def get_lock(name: str) -> asyncio.Lock:
    if name not in _locks:
        _locks[name] = asyncio.Lock()
    return _locks[name]


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/stacks/{name}/services", dependencies=[Depends(verify_token)])
async def services(name: str) -> dict[str, Any]:
    cfg = get_stack_config(name)
    return {"stack": name, "services": list_services(name, cfg)}


# With a body listing services, deploys only those and prunes the rest of the
# stack (so de-selected services stop); with no body, deploys the whole stack.
@app.post("/stacks/{name}/deploy", dependencies=[Depends(verify_token)])
async def deploy(name: str, body: DeployRequest | None = None) -> dict[str, Any]:
    cfg = get_stack_config(name)
    stack_env = load_stack_env(name, cfg)
    lock = get_lock(name)
    selected = body.services if body else None

    if selected is not None and not selected:
        raise HTTPException(400, "No services selected -- remove the stack instead")

    if lock.locked():
        raise HTTPException(409, f"Stack '{name}' already has an action in progress")

    compose_file = cfg["compose_file"]
    flags = list(cfg.get("deploy_flags", []))
    if selected is not None:
        compose_file = write_filtered_compose(cfg, selected)
        flags.append("--prune")

    try:
        async with lock:
            try:
                result = await asyncio.to_thread(
                    docker_ops.deploy_stack,
                    compose_file,
                    cfg["stack_name"],
                    flags,
                    stack_env,
                )
            except subprocess.TimeoutExpired:
                raise HTTPException(504, f"Timed out deploying stack '{name}'")
    finally:
        if compose_file != cfg["compose_file"]:
            os.unlink(compose_file)

    if result.returncode != 0:
        raise HTTPException(500, (result.stderr or result.stdout).strip())

    return {"success": True, "stack": name, "services": selected, "output": result.stdout.strip()}


@app.post("/stacks/{name}/remove", dependencies=[Depends(verify_token)])
async def remove(name: str) -> dict[str, Any]:
    cfg = get_stack_config(name)
    lock = get_lock(name)

    if lock.locked():
        raise HTTPException(409, f"Stack '{name}' already has an action in progress")

    async with lock:
        try:
            result = await asyncio.to_thread(docker_ops.remove_stack, cfg["stack_name"])
        except subprocess.TimeoutExpired:
            raise HTTPException(504, f"Timed out removing stack '{name}'")

    if result.returncode != 0:
        raise HTTPException(500, (result.stderr or result.stdout).strip())

    return {"success": True, "stack": name, "output": result.stdout.strip()}


@app.get("/stacks/{name}/status", dependencies=[Depends(verify_token)])
async def status(name: str) -> dict[str, Any]:
    cfg = get_stack_config(name)
    return await asyncio.to_thread(docker_ops.get_stack_status, cfg["stack_name"])
