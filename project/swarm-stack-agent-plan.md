# Stack Controller Agent — Implementation Plan

Automating Docker Swarm stack start/stop (IMU stack, Camera stack) from the dashboard, via a dedicated agent service integrated into the AMS `docker-compose.yml`.

> **Status:** Grounded in a review of `wku-smr-lab-middleware` (main branch). AMS is the manager (confirmed), agent is FastAPI, agent links to the existing `fastapi-app` container. One open question below (camera) needs your call before that part can be finalized.

---

## 0. What the repo review changed vs. the previous draft

- **Confirmed AMS = manager.** The docs (`project/web/docs/operations/running-a-test.md`) show the same host that runs `docker-compose.yml` is SSH'd into as the Swarm manager to run `docker stack deploy`. Path A (direct `docker.sock` mount) is correct — no SSH/remote-context layer needed.
- **The dashboard's "Start Session" / "Stop Session" buttons already exist** and already call exact endpoints: `GET /session/start/{label}` and `GET /session/stop` in `project/fast_server/main.py` (frontend caller: `project/web/src/api/sessionApi.js`). This is the real hook point — no new dashboard UI is needed, just extending these two handlers.
- **The IMU Swarm stack file already exists**: `project/deploy/swarm-imu-edge-nodes.yml`, deployed today as `docker stack deploy --resolve-image never -c swarm.yml imu` (per the docs — the actual file has since moved/renamed to `project/deploy/swarm-imu-edge-nodes.yml`; the plan below uses the real path). Stack name is `imu`.
- **No custom Docker network or secrets are used anywhere in this repo today** — services resolve each other by plain service name on Compose's default project network (`mqtt-broker`, `fastapi-app`, etc.), and config comes from `.env` + `environment:`, not Docker secrets. The plan below follows that convention rather than introducing new patterns, and just flags where a stronger option (secrets) would diverge from house style.
- **`fastapi-app` has no auth today** (just CORS middleware). We're still adding a bearer token on the *new* agent specifically because `docker.sock` access is a much bigger blast radius than anything the app currently exposes — noted as an intentional, isolated exception, not a repo-wide auth push.
- **`aiohttp` is already a dependency** and already used for exactly this kind of internal call — `project/tcp_server/tcp_server.py`'s `send_to_fastapi()` POSTs to `fastapi-app` using `aiohttp.ClientSession`. The dashboard-backend → agent call below mirrors that same pattern instead of introducing `httpx` or anything new.
- **⚠️ Camera nodes are not currently a Swarm stack.** `project/web/docs/operations/running-a-test.md` and `camera-ops.md` both describe cameras running via plain `docker compose up -d`, SSH'd into two *separate* hosts (`192.168.1.80`, `192.168.1.92`, from the `camera_sensor_fusion` repos) — not `docker stack deploy`, and not on the AMS/manager host at all. This is a real gap between the original ask and what's actually in the repo — see §7, need your call before I lock in the camera side of this plan.

The new changes we have made change this. The camera nodes are now a swarm stack and we can deploy it the same way we deploy the imu stack.

---

## 1. Goal (unchanged)

- Dashboard "Start Session" → IMU Swarm stack deployed, DB session starts
  - Note that the session should always start first, then we start the IMU and Camera stacks. This should be a requirement and should be implemented accordingly.
- Dashboard "Stop Session" → DB session stops (+ existing backup), IMU Swarm stack removed
  - Notes that the IMU and Camera swarm stacks should be stopped first, then we confirm that all the data is stored, then we stop the session automatically. It is important to ensure no data is left in the buffer before stopping the session.
- No SSH in the loop; the two existing session endpoints do double duty

---

## 2. Architecture (resolved)

AMS host runs `docker-compose.yml` (the always-on broker stack: `mqtt-broker`, `fastapi-app`, `web`, `tcp`, `ntp`) **and** is the Swarm manager for `project/deploy/swarm-imu-edge-nodes.yml`. The new agent joins the same `docker-compose.yml`, mounts `/var/run/docker.sock` directly (no SSH), and is called by `fastapi-app` over the plain default Compose network — same mechanism `fastapi-app` and `tcp` already use to reach each other.

`docker.sock` access is root-equivalent on the AMS host. Since AMS also runs the middleware that everything else depends on, the agent stays its own minimal, separately-reviewed service rather than being folded into `fastapi-app`'s already-broad surface (MQTT ingestion, batch workers, WebSocket broadcast, backups).

I assume that we are creating a new container for this agent, and we add it to our existing docker compose file, this way the AMS now includes this agent.

---

## 3. Real integration point: `fast_server/main.py`

Current code (`project/fast_server/main.py`, lines 303–366):

```python
@app.get("/session/start/{label}")
async def start_session(label: str, session_label: str, is_test_session: bool = True) -> dict[str, Any]:
    loggers.create_loggers()
    try:
        db = app.state.db
        session_id = await db.create_session(label=label, session_label_name=session_label, is_test_session=is_test_session)
        ...
        return {"message": f"Session started with label: {label}", "id": session_id, "success": True}
    except Exception as e:
        ...

@app.get("/session/stop")
async def stop_session() -> dict[str, Any]:
    try:
        db = app.state.db
        await db.end_session()
        ...
        msg = await try_backup()
        return {"message": "Current Session Ended", "backup": msg, "success": True}
    except Exception as e:
        ...
```

This is where the agent call gets added — before creating the DB session on start, after ending it on stop — following the exact pattern `tcp_server.py` already uses to call `fastapi-app`:

```python
# fast_server/main.py — new helper, mirrors tcp_server.py's send_to_fastapi()
import aiohttp

async def call_stack_controller(action: str, stack: str = "imu") -> dict[str, Any]:
    host = os.getenv("STACK_CONTROLLER_HOST", "stack-controller")
    port = os.getenv("STACK_CONTROLLER_PORT", "8080")
    token = os.getenv("STACK_CONTROLLER_TOKEN")
    url = f"http://{host}:{port}/stacks/{stack}/{action}"

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers={"Authorization": f"Bearer {token}"}) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    loggers.log_system_logger(f"stack-controller {action} failed ({resp.status}): {text}", True)
                    return {"success": False, "error": text}
                return await resp.json()
    except Exception as e:
        loggers.log_system_logger(f"Could not reach stack-controller for {action}: {e}", True)
        return {"success": False, "error": str(e)}
```

```python
# inside start_session(), before db.create_session(...):
deploy_result = await call_stack_controller("deploy", "imu")
if not deploy_result.get("success"):
    await broadcast_message(misc_manager, f"IMU stack deploy failed: {deploy_result.get('error')}", "error")
    # decide: block the session start, or proceed and let the operator retry the stack separately —
    # your call; recommend blocking, since the whole point is data arriving from a running stack

# inside stop_session(), after db.end_session():
remove_result = await call_stack_controller("remove", "imu")
if not remove_result.get("success"):
    await broadcast_message(misc_manager, f"IMU stack removal failed: {remove_result.get('error')}", "error")
    # session/backup already completed at this point either way — surface the error, don't fail the whole endpoint
```

No frontend changes needed — `sessionApi.js`'s `startSessionByLabel()` / `stopSessionRequest()` already call these two endpoints.

---

## 4. Agent service design

### 4.1 Location & stack

New sibling directory `project/stack_controller/`, matching the existing `fast_server/` / `tcp_server/` layout convention from `CLAUDE.md`. FastAPI, Python 3.13, same base pattern as `project/Dockerfile`.

### 4.2 Stack whitelist config (`stack_controller/stacks.yml`, mounted read-only)

```yaml
stacks:
  imu:
    compose_file: /stacks/swarm-imu-edge-nodes.yml
    stack_name: imu
    deploy_flags: ["--resolve-image", "never"]   # matches the existing manual SOP
  # camera: pending — see §7
```

Mount `project/deploy/` directly into the agent (`./deploy:/stacks:ro`) rather than duplicating the compose file — the agent reads the same file already used for manual deploys today.

### 4.3 API surface

| Method | Path | Description |
|---|---|---|
| `POST` | `/stacks/{name}/deploy` | `docker stack deploy --resolve-image never -c /stacks/swarm-imu-edge-nodes.yml imu` |
| `POST` | `/stacks/{name}/remove` | `docker stack rm imu` |
| `GET`  | `/stacks/{name}/status` | Rolled-up state from `docker stack services imu` |
| `GET`  | `/health` | Liveness for the compose healthcheck and `fastapi-app`'s `depends_on` |

Bearer token from `STACK_CONTROLLER_TOKEN`, checked on the three state/status endpoints.

### 4.4 Docker connectivity

Direct `docker.sock` mount, shelling out to the CLI for `deploy`/`rm` (matches the SOP exactly, and `docker stack deploy` is a client-side compose-parsing operation with no single Engine API equivalent):

```python
import subprocess

def deploy_stack(compose_file: str, stack_name: str, extra_flags: list[str]) -> subprocess.CompletedProcess:
    cmd = ["docker", "stack", "deploy", *extra_flags, "-c", compose_file, stack_name]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=120)

def remove_stack(stack_name: str) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", "stack", "rm", stack_name], capture_output=True, text=True, timeout=60)
```

Use the `docker` Python SDK (`docker.from_env()`) for `/status`, which is cleaner as a structured call than parsing CLI text output.

---

## 5. `project/docker-compose.yml` changes

```yaml
services:
  # ...existing mqtt-broker, fastapi-app, web, tcp, ntp...

  stack-controller:
    build:
      context: .
      dockerfile: stack_controller/Dockerfile
    container_name: AMS-stack-controller
    env_file:
      - .env
    environment:
      - STACK_CONTROLLER_TOKEN=${STACK_CONTROLLER_TOKEN}
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - ./deploy:/stacks:ro
      - ./stack_controller/stacks.yml:/config/stacks.yml:ro
    healthcheck:
      test: ["CMD", "python3", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')"]
      interval: 30s
      timeout: 5s
      retries: 3
    # No published port — only fastapi-app on the same default network needs to reach it

  fastapi-app:
    # ...existing config...
    environment:
      # ...existing entries...
      - STACK_CONTROLLER_HOST=stack-controller
      - STACK_CONTROLLER_PORT=8080
      - STACK_CONTROLLER_TOKEN=${STACK_CONTROLLER_TOKEN}
    depends_on:
      - mqtt-broker
      - stack-controller
```

No `networks:` block needed — `docker-compose.yml` doesn't declare one today, and `fastapi-app`/`tcp`/`mqtt-broker` already resolve each other by service name on Compose's default project network. `stack-controller` joins the same way automatically.

`STACK_CONTROLLER_TOKEN` goes in `.env` (and `.env.example`) alongside the existing `DB_PASSWORD`-style entries, matching how every other credential in this repo is handled — Docker secrets would be more defensible given what this token protects, but would be the first use of secrets anywhere in the repo; flagging as an optional upgrade rather than baking in a new pattern unilaterally.

`fastapi-app`'s `depends_on` here uses the same short-list style already in the file. If you want `fastapi-app` to actually wait for the agent to be *healthy* (not just started), that needs the long-form `depends_on: stack-controller: condition: service_healthy` — compatible with Compose v2, just a style change from what's there today; your call whether it's worth it here.

---

## 6. New files for the agent

```
project/stack_controller/
├── Dockerfile
├── main.py          # FastAPI app: /health, /stacks/{name}/deploy|remove|status
├── docker_ops.py     # deploy_stack / remove_stack / get_status, subprocess + docker SDK
├── auth.py           # bearer token dependency
└── stacks.yml
```

`project/requirements.txt` doesn't need changes for `fastapi-app` (it already has `aiohttp`). The agent's own `stack_controller/requirements.txt` needs `fastapi`, `uvicorn[standard]`, `docker` (SDK), `pyyaml`.

---

## 7. Open question: the Camera stack

Per the current docs, camera nodes aren't Swarm-managed — they're two separate hosts running plain `docker compose up -d` over SSH, outside the AMS/manager entirely. That's a different mechanism than `docker stack deploy`, and outside what a `docker.sock`-mounted agent on AMS can reach at all without adding SSH back in for just this piece.

Worth confirming before I lock in that part of the plan:

- Is there a newer camera Swarm setup not reflected in `running-a-test.md` / `camera-ops.md`?
- Should the agent grow a second, SSH-based code path just for the camera hosts (reintroducing SSH, but now scoped to one whitelisted, forced-command flow instead of ad hoc access)?
- Or should this rollout scope to the IMU stack only for now, with camera automation as a follow-up once/if it's migrated onto Swarm the way IMU was?

Now the camera stack exists and we use the same schema for deploying that stack as we do for the IMUs. All the neccacary IPs and Ports will also live in the .env file on the AMS host device.
---

## 8. Operational concerns

- **Per-stack locking** — reject/queue a `deploy` while one's already in flight for that stack name.
- **Idempotency** — `deploy` on an already-running stack is a no-op-ish update (native `docker stack deploy` behavior); `remove` on an already-removed stack returns cleanly.
- **Status polling** — `docker stack services imu` rolled into `not_deployed` / `deploying` / `running` / `removing` / `error`.
- **Timeouts** — 30–60s before reporting `error` rather than hanging `start_session`/`stop_session`.
- **Audit** — log stack actions the same way `loggers.log_system_logger` already logs session start/stop, so it shows up in the same place operators already look.

---

## 9. Security checklist

- [ ] `docker.sock` mounted only into `stack-controller` — no other AMS service gets it
- [ ] Bearer token required on `/stacks/*` endpoints, even though the call is same-host/default-network — the one deliberate exception to this repo's current no-auth pattern, because of what `docker.sock` grants
- [ ] Agent only ever deploys/removes stacks listed in `stacks.yml` — never accepts compose content or shell input from `fastapi-app`
- [ ] `STACK_CONTROLLER_TOKEN` lives in `.env` (gitignored, like `DB_PASSWORD`), not committed
- [ ] No published port for `stack-controller`
- [ ] Stack actions are logged via the existing `loggers` module

---

## 10. Testing plan

1. Local: `docker swarm init` on a dev machine, mount its local `docker.sock`, run the agent against `swarm-imu-edge-nodes.yml` directly (adjust placement constraints or run on a single-node swarm for dev).
2. Wire `fast_server/main.py`'s new `call_stack_controller()` in and hit `/session/start/{label}` end to end in `docker-compose.local.yml`.
3. Failure injection: kill the agent mid-deploy, double-click start, confirm locking/timeouts behave.
4. Staging/lab: same `docker-compose.yml`, real manager, one full test-session cycle before trusting it for a live run.

---

## 11. Rollout milestones

- **M1** — Agent skeleton: `/health`, `/stacks/imu/status` only
- **M2** — `deploy`/`remove` for `imu`, whitelist config, locking
- **M3** — Add to `docker-compose.yml`, wire `call_stack_controller()` into `start_session()`/`stop_session()` in `main.py`
- **M4** — End-to-end test in `docker-compose.local.yml`, then staging
- **M5** — Cut over on a real lab test session, monitor
- **M6** — Camera stack, once §7 is resolved

---

## 12. Remaining open questions

- Camera stack direction (§7) — blocks M6, doesn't block M1–M5 FIXED ABOVE
- Should `start_session` **block** on a failed stack deploy (recommended) or proceed and just surface the error? YES
- Who owns rotating `STACK_CONTROLLER_TOKEN`? The AMS will have this token 
- Worth adding `condition: service_healthy` to `fastapi-app`'s `depends_on` for `stack-controller`, or keep the short-list style consistent with the rest of the file? KEEP previous
