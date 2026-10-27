# Health & logs

How the broker stack keeps running when something it depends on is down, how it restarts itself, and where it says what's wrong. For "the dashboard says X is down, what do I do", see [Troubleshooting](/operations/troubleshooting).

## Starting without dependencies

No container waits for another one, the database, the NAS or the MQTT broker before it starts.

- **`fastapi-app`** starts its HTTP and WebSocket server immediately. The database and MQTT broker are connected in the background and retried with backoff: 1, 2, 5, 10, then every 30 seconds. Until the database connects, anything that needs it answers **503** with the reason, for example `Database unavailable: db down 14s: can't reach 192.168.1.104:5433: no answer within 5s (retrying in 3s)`. Live feeds, monitor mode, device selection and the capture state keep working.
- **Stop Session works with the database down.** The edge stacks are removed and recording stops right away; the session's end time is written once the database is back.
- **`tcp`** listens for the robot immediately and waits for the database the same way.
- **`web`** (nginx) looks `fastapi-app` up per request instead of at startup, so the dashboard and these docs load even when the API is down.
- If inserts fail mid-session, each worker keeps at most `MAX_BACKLOG_ROWS` rows (default `QUEUE_SIZE`) and drops the oldest beyond that. Failures are reported every `BACKLOG_REPORT_INTERVAL` seconds (default 10), and a "recovered" message follows when inserts work again.

## Two kinds of health

| | System Health (top of the dashboard) | Container Health (bottom of the dashboard) |
| --- | --- | --- |
| Question | Can the API reach what it needs? | Is each container up and answering? |
| Source | `GET /health` on `fastapi-app` | Docker health checks, read by `stack-controller` |
| Covers | Database, MQTT broker, stack-controller, robot TCP server, log folder, backup folder, and the PLC when [PLC auto stop](/operations/plc-auto-stop) is on | Every container labelled `smr.monitor` |
| When the API is down | Shows "API unreachable" | Still works (served through nginx → stack-controller) |

### `GET /health`

Always `200` while `fastapi-app` is alive. `overall` is `ok`, `degraded` (something is down) or `starting`. Each component has `status`, `error`, `for_s` (how long in this state), `retry_in_s` and `attempts`. `HEALTH_INTERVAL` (default 10 s) sets how often everything is re-checked. Changes of state (not every retry) are posted to the Misc message box and logged as important events.

### Docker health checks

| Container | Check |
| --- | --- |
| `fastapi-app` | `python -m fast_server.healthcheck` (calls `/health`) |
| `tcp` | `python -m fast_server.healthcheck http://127.0.0.1:8090/queue/status` |
| `web` | `wget` of the dashboard page |
| `mqtt-broker` | `mosquitto_sub` of `$SYS/broker/uptime` |
| `stack-controller`, `pgadmin`, `ntp` | their existing checks |

A container is **healthy if it works, even when its dependencies don't**. Restarting `fastapi-app` can't fix the NAS, so its check passes while the API answers, but it prints what's degraded. Docker's health record (and the Container Health box) then shows, for example, `alive; degraded; db down 3m (can't reach …)`:

```bash
docker inspect AMS-fastapi --format '{{json .State.Health}}'
```

### Watchdog

Plain Docker Compose only *reports* `unhealthy`; it never restarts the container. `restart: unless-stopped` only helps when the process exits. stack-controller runs a watchdog that, every `WATCHDOG_INTERVAL` seconds (default 30), restarts containers labelled `smr.autoheal: "true"` that are `unhealthy`. It allows at most `WATCHDOG_MAX_RESTARTS` restarts (default 3) per container per `WATCHDOG_WINDOW` seconds (default 15 min), then stops and reports **"giving up — needs a person"**, so it can never restart a container in a loop. Set `WATCHDOG_ENABLED=false` on stack-controller to turn it off.

## Logs

### The record format

Every service writes its log to stdout as **one JSON record per line**, so `docker logs AMS-fastapi` is the full story even with the NAS down. The format lives in `common/log_schema.py`:

```json
{
  "id": "fastapi-app:2026-10-09T14:38:39.123456+00:00:12",
  "ts": "2026-10-09T14:38:39.123Z",
  "source": "fastapi-app",
  "logger": "system",
  "level": 40,
  "level_name": "ERROR",
  "priority": null,
  "category": "health",
  "important": true,
  "message": "db down: can't reach 192.168.1.104:5433: no answer within 5s",
  "context": {"component": "db"}
}
```

- `level` is the **severity** (Python's numbers: 10 DEBUG, 20 INFO, 30 WARNING, 40 ERROR, 50 CRITICAL).
- `priority` is reserved for **how urgently a person must act**. It is always `null` today. A future policy goes in `classify()` in `common/log_schema.py`; the `/logs` endpoint already accepts `min_priority`, and the dashboard shows a priority badge as soon as one is set.
- `category` is one of `health`, `session`, `ingest`, `backup`, `deploy`, `watchdog`, `system`, `parameters`, `other`.
- `important: true` puts the record in the dashboard's **Important** tab (which also shows anything at WARNING or worse).

### Writing logs from code

```python
import logging
from fast_server import loggers

# An event a person should notice -> important, shows in the Important tab
loggers.log_event("Session 812 stopped", category="session", session_id=812)
loggers.log_event("Couldn't reach the NAS", category="backup", level=logging.ERROR)

# Plain system log line (important: false)
loggers.log_system_logger("Capture mode -> idle")
```

The system logger and every WARNING-or-worse record also go to stdout. High-volume data lines ("Inserted 50 IMU rows") stay in the log files only. The files are still written to `LOG_DIR` on the NAS, from a background thread, so a hung NFS mount can't freeze the API; if the folder isn't writable, logging falls back to stdout and the **Log files** chip on the dashboard turns red.

### Reading logs

stack-controller's `GET /logs` (on the dashboard: `/api/system/logs`) reads Docker's logs for every `smr.monitor` container and returns them as records, oldest first:

| Parameter | Meaning |
| --- | --- |
| `since` | ISO time or unix seconds; only newer lines |
| `tail` | lines per container, default 200, max 1000 |
| `source` | repeatable; compose service names |
| `min_level` | e.g. `30` for warnings and up |
| `important_only` | important records plus WARNING and up |
| `min_priority` | reserved; has no effect until priorities are assigned |

Lines from containers that don't write JSON records (nginx, mosquitto, pgadmin, ntp, uvicorn's own lines) are converted in `stack_controller/log_normalize.py`, one pattern per format; to support a new container, add a row to `PATTERNS`. Python tracebacks are folded into the record they belong to. Passwords, tokens and `postgres://user:pass@` URLs are masked before anything leaves stack-controller.

Docker keeps 5 × 10 MB of logs per container (`x-logging` in `docker-compose.yml`). They survive a restart but not a recreate (`docker compose up -d` after a rebuild); the files on the NAS are the long-term record.

## Configuration

| Variable | Service | Default | Meaning |
| --- | --- | --- | --- |
| `DB_CONNECT_TIMEOUT` | fastapi-app, tcp | `5` | Seconds to wait for the database per connection attempt |
| `HEALTH_INTERVAL` | fastapi-app, tcp | `10` | Seconds between dependency checks |
| `MAX_BACKLOG_ROWS` | fastapi-app, tcp | `QUEUE_SIZE` | Rows a worker holds while inserts fail |
| `BACKLOG_REPORT_INTERVAL` | fastapi-app, tcp | `10` | Seconds between "inserts failing" reports |
| `LOG_DIR` | fastapi-app, tcp | `/fast_server/logs` | Where log files are written (`tcp` sets `/tcp-server/logs`) |
| `SERVICE_NAME` | fastapi-app, tcp | hostname | `source` in log records |
| `WATCHDOG_ENABLED` | stack-controller | `true` | Turn the watchdog off |
| `WATCHDOG_INTERVAL` | stack-controller | `30` | Seconds between watchdog checks |
| `WATCHDOG_MAX_RESTARTS` / `WATCHDOG_WINDOW` | stack-controller | `3` / `900` | Restart limit per container per window (s) |
