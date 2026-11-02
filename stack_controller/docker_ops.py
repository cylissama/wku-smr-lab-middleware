import os
import subprocess
from datetime import datetime

import docker
from docker.errors import APIError, DockerException


# stack_env is layered over this process's environment, since `docker stack
# deploy` interpolates ${VAR}s in the compose file from its own environment.
def deploy_stack(
    compose_file: str, stack_name: str, extra_flags: list[str], stack_env: dict[str, str] | None = None
) -> subprocess.CompletedProcess:
    cmd = ["docker", "stack", "deploy", *extra_flags, "-c", compose_file, stack_name]
    env = {**os.environ, **(stack_env or {})}
    return subprocess.run(cmd, capture_output=True, text=True, timeout=120, env=env)


def remove_stack(stack_name: str) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", "stack", "rm", stack_name], capture_output=True, text=True, timeout=60)


# Task states in which a container may still exist on its node (still
# starting, running or shutting down). Earlier states haven't got a container
# yet and later ones are terminal.
LIVE_TASK_STATES = {"assigned", "accepted", "preparing", "ready", "starting", "running"}


# The stack's tasks whose containers may still be up, as "<task name>@<node>".
# `docker stack rm` returns once the services are deleted; the containers on
# the nodes stop a few seconds later, and until then a redeploy would run two
# copies of a device (same MQTT client id, same IMU socket). Tasks on nodes
# that aren't Ready are left out: they can't be waited for. Raises if Docker
# can't be reached.
def live_tasks(stack_name: str) -> list[str]:
    client = docker.from_env()
    try:
        nodes = {n["ID"]: n for n in client.api.nodes()}
        tasks = client.api.tasks(filters={"label": f"com.docker.stack.namespace={stack_name}"})
    finally:
        client.close()

    live = []
    for task in tasks:
        node = nodes.get(task.get("NodeID") or "")
        if not node or node.get("Status", {}).get("State") != "ready":
            continue
        if task.get("Status", {}).get("State") in LIVE_TASK_STATES:
            name = task.get("Annotations", {}).get("Name") or task.get("ID", "?")[:12]
            live.append(f"{name}@{node.get('Description', {}).get('Hostname', node['ID'][:12])}")
    return sorted(live)


# The parts of a container spec a redeploy of ours changes (env overrides,
# image, command). A task whose spec differs belongs to an older deploy.
_SPEC_KEYS = ("Image", "Env", "Args", "Command")


def _spec_key(container_spec: dict | None) -> tuple:
    container_spec = container_spec or {}
    return tuple(repr(container_spec.get(k)) for k in _SPEC_KEYS)


# Docker's RFC 3339 timestamps (nanoseconds, "Z") as unix seconds
def _ts(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).timestamp()
    except ValueError:
        return None


# Rolls up per-service task state for a stack into one of:
# not_deployed / deploying / running / removing / error
#
# Only tasks of the current deploy count: during a redeploy the old task can
# still be running (or not yet told to stop) for a moment, and counting it
# would call a device ready before its new container has even started.
# "running" means Swarm saw the healthcheck pass; since is when the last
# needed task reached it (Status.Timestamp, set by the node).
def get_stack_status(stack_name: str) -> dict:
    try:
        client = docker.from_env()
    except DockerException as e:
        return {"state": "error", "services": [], "error": f"Could not reach Docker: {e}"}

    try:
        services = client.services.list(filters={"label": f"com.docker.stack.namespace={stack_name}"})
    except APIError as e:
        client.close()
        return {"state": "error", "services": [], "error": str(e)}

    try:
        if not services:
            return {"state": "not_deployed", "services": []}

        service_states = []

        for service in services:
            spec = service.attrs.get("Spec", {})
            spec_mode = spec.get("Mode", {})
            replicated = spec_mode.get("Replicated", {})
            desired = replicated.get("Replicas", len(spec_mode.get("Global", {})) or None)
            current_spec = _spec_key(spec.get("TaskTemplate", {}).get("ContainerSpec"))

            tasks = service.tasks()
            current = [
                t for t in tasks
                if t.get("DesiredState") == "running"
                and _spec_key(t.get("Spec", {}).get("ContainerSpec")) == current_spec
            ]
            running = [t for t in current if t.get("Status", {}).get("State") == "running"]
            failed = any(t.get("Status", {}).get("State") == "failed" for t in tasks)

            since = None
            if desired is not None and len(running) < desired:
                svc_state = "error" if failed else "deploying"
            elif not running and desired != 0:
                svc_state = "deploying"
            else:
                svc_state = "running"
                stamps = [_ts(t.get("Status", {}).get("Timestamp")) for t in running]
                since = max((x for x in stamps if x is not None), default=None)

            service_states.append(
                {
                    "name": service.name,
                    "desired": desired,
                    "running": len(running),
                    "state": svc_state,
                    "since": since,
                }
            )
    except APIError as e:
        return {"state": "error", "services": [], "error": str(e)}
    finally:
        client.close()

    if any(s["state"] == "error" for s in service_states):
        overall = "error"
    elif any(s["state"] == "deploying" for s in service_states):
        overall = "deploying"
    else:
        overall = "running"

    return {"state": overall, "services": service_states}
