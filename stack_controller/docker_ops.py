import os
import subprocess

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


# Rolls up per-service task state for a stack into one of:
# not_deployed / deploying / running / removing / error
def get_stack_status(stack_name: str) -> dict:
    try:
        client = docker.from_env()
    except DockerException as e:
        return {"state": "error", "services": [], "error": f"Could not reach Docker: {e}"}

    try:
        services = client.services.list(filters={"label": f"com.docker.stack.namespace={stack_name}"})
    except APIError as e:
        return {"state": "error", "services": [], "error": str(e)}
    finally:
        client.close()

    if not services:
        return {"state": "not_deployed", "services": []}

    service_states = []
    overall = "running"

    for service in services:
        spec_mode = service.attrs.get("Spec", {}).get("Mode", {})
        replicated = spec_mode.get("Replicated", {})
        desired = replicated.get("Replicas", len(spec_mode.get("Global", {})) or None)

        tasks = service.tasks()
        running = sum(1 for t in tasks if t.get("Status", {}).get("State") == "running")
        failed = any(t.get("Status", {}).get("State") == "failed" for t in tasks)

        if desired is not None and running < desired:
            svc_state = "error" if failed else "deploying"
        else:
            svc_state = "running"

        service_states.append(
            {
                "name": service.name,
                "desired": desired,
                "running": running,
                "state": svc_state,
            }
        )

    if any(s["state"] == "error" for s in service_states):
        overall = "error"
    elif any(s["state"] == "deploying" for s in service_states):
        overall = "deploying"

    return {"state": overall, "services": service_states}
