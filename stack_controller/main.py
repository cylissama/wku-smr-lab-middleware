import asyncio
import os
import subprocess
from typing import Any

import yaml
from dotenv import dotenv_values
from fastapi import Depends, FastAPI, HTTPException

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


def get_lock(name: str) -> asyncio.Lock:
    if name not in _locks:
        _locks[name] = asyncio.Lock()
    return _locks[name]


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/stacks/{name}/deploy", dependencies=[Depends(verify_token)])
async def deploy(name: str) -> dict[str, Any]:
    cfg = get_stack_config(name)
    stack_env = load_stack_env(name, cfg)
    lock = get_lock(name)

    if lock.locked():
        raise HTTPException(409, f"Stack '{name}' already has an action in progress")

    async with lock:
        try:
            result = await asyncio.to_thread(
                docker_ops.deploy_stack,
                cfg["compose_file"],
                cfg["stack_name"],
                cfg.get("deploy_flags", []),
                stack_env,
            )
        except subprocess.TimeoutExpired:
            raise HTTPException(504, f"Timed out deploying stack '{name}'")

    if result.returncode != 0:
        raise HTTPException(500, (result.stderr or result.stdout).strip())

    return {"success": True, "stack": name, "output": result.stdout.strip()}


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
