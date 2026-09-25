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
