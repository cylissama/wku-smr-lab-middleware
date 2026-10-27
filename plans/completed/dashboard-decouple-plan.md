# Dashboard Decouple — Start Without the Database, Show Why It's Broken

> Plan for the ask in `dashboard-decouple.md`: the web container (and fastapi-app)
> must come up even when the database or NAS is unreachable, every container should
> restart itself when it faults, and the dashboard plus `docker logs` should say
> plainly *what* is down and *why*. Follow-ups added on review: use Docker's
> built-in health checks with a **Container Health** box (§D), and add a **Logs**
> box that shows recent Docker logs plus important system events, in a record
> format that can take priority levels later (§G).

> **Status (2026-10-09):** A, B, C, D, E and G are implemented on `dev/monitor-mode`
> (A+E+B deployed and verified on prod; C/D/G built, awaiting deploy). F (host NFS
> automount) is deliberately last and needs `sudo` on IIoT. Deviation from §D: the
> read-only `/containers` and `/logs` routes are unauthenticated instead of using a
> token injected by nginx. The content is public by decision, and nginx exposes
> only those two GET routes, so no token handling was needed. Operator docs:
> `web/docs/docker/health-and-logs.md` and `web/docs/operations/troubleshooting.md`.

---

## 1. Why the stack fails today (verified on the prod host, 2026-10-09)

The web container never talks to Postgres itself. It goes down along with
fastapi-app, and fastapi-app goes down whenever the DB or NAS does. Six coupling
points, in the order they bite:

| # | Coupling | Where | What happens when the NAS/DB (`192.168.1.104`) is down |
|---|---|---|---|
| 1 | **NFS volumes mounted by Docker** | `docker-compose.yml` `nas_backups`, `logs` (`addr=${DB_HOST}`) | Docker can't mount the volume, so it never creates `fastapi-app` or `tcp`. No Python runs and nothing is logged. |
| 2 | **Startup awaits the DB pool** | `fast_server/main.py` `startup()` → `DatabaseSingleton.get_instance()` → `asyncpg.create_pool` (default 60 s connect timeout) | The pool creation raises, uvicorn logs "Application startup failed. Exiting.", and the container exits. |
| 3 | **Startup awaits the MQTT broker** | `mqtt.init_app(app)` → `FastMQTT.mqtt_startup()` → gmqtt `connect()` | gmqtt only auto-reconnects after a *lost* connection. If the broker is down at boot, the first connect raises and fastapi-app exits. |
| 4 | **nginx resolves `fastapi-app` at config load** | `web/nginx.conf` `proxy_pass http://fastapi-app:8000/` | `nginx: [emerg] host not found in upstream "fastapi-app"`, and the web container exits (confirmed with `nginx -t`). It's the same for the docs site. |
| 5 | **`web` `depends_on: fastapi-app`** | `docker-compose.yml` | `docker compose up web` also has to create fastapi-app. If #1 fails, compose aborts before it reaches web. |
| 6 | **No restart policy** | `fastapi-app`, `tcp`, `web`, `mqtt-broker`, `stack-controller` are all `restart=no` | Once any of the above exits, it stays down until someone runs compose by hand. |

Related gaps that hide the cause or turn an outage into data loss:

- **Errors are invisible.** The system log is file-only, written into the NFS
  `logs` volume, so `docker logs AMS-fastapi` shows nothing useful. The dashboard
  reports errors by POSTing them to fastapi-app's `/send/*`, which is the thing
  that's down. Status polls swallow errors (`DataDashboard.jsx` "stay quiet on poll
  failures").
- **A hung NFS mount freezes the API.** `loggers.py` writes synchronously from the
  event loop. With a `soft` NFS mount, every write can block for the full
  `timeo×retrans` period while the NAS is unreachable.
- **tcp's robot worker dies silently.** `robot_worker` calls
  `DatabaseSingleton.get_instance()` inside a background task. If the DB is down,
  that task raises once and never comes back, even after the DB recovers.
- **tcp logs go nowhere durable.** `loggers.create_logger` hard-codes
  `/fast_server/logs`, but compose mounts tcp's logs volume at `/tcp-server/logs`.
  tcp's logs live in the container layer and are lost when it's recreated.
- **A DB outage mid-session grows memory without bound.** If an insert fails,
  `flush_batch` keeps the batch and the worker keeps appending to it. The batch
  grows past `BATCHES` with no cap, and an error is broadcast every second.

---

## 2. Target behavior

```
                   ┌─────────── always starts ────────────┐
 web (nginx)  ──►  SPA + docs served, /api/* proxied lazily, /api/system/* → stack-controller
 fastapi-app  ──►  HTTP/WS up immediately; DB + MQTT connect in background with backoff
 tcp          ──►  TCP + status ports up immediately; worker waits for DB
 stack-ctrl   ──►  watchdog: restarts unhealthy AMS containers, serves container state + normalized logs
```

fastapi-app reports one of these health states, per component and overall:

| Overall | Meaning | What still works |
|---|---|---|
| `ok` | DB, MQTT, stack-controller, tcp, NAS paths all fine | everything |
| `degraded` | DB *or* NAS *or* tcp down; API and MQTT up | dashboard, **monitor mode** (needs no DB), live feeds; session start/stop, history, backups refused with a clear 503 |
| `down` | (seen by the dashboard, not reported by the API) API unreachable | dashboard still loads and shows container state from stack-controller (§3.D) |

---

## 3. Phases

### A. Every container starts regardless of its dependencies

1. **Compose** (`docker-compose.yml` and `docker-compose.local.yml`):
   - `restart: unless-stopped` on `mqtt-broker`, `fastapi-app`, `tcp`, `web` and
     `stack-controller`.
   - Remove `depends_on: fastapi-app` from `web`. Keep fastapi-app's `depends_on`
     list; it only sets start order.
2. **nginx** (`web/nginx.conf`): resolve at request time instead of at load.
   ```nginx
   resolver 127.0.0.11 valid=10s ipv6=off;        # Docker's embedded DNS
   location /api/ {
     set $fastapi http://fastapi-app:8000;
     rewrite ^/api/(.*)$ /$1 break;
     proxy_pass $fastapi;
     proxy_http_version 1.1;                       # + Upgrade/Connection headers for WS
     proxy_intercept_errors on;
     error_page 502 503 504 = @api_down;
   }
   location @api_down {
     default_type application/json;
     return 503 '{"success":false,"error":"fastapi-app is not reachable from the web container"}';
   }
   ```
   The `/docs/` and SPA locations don't change. They now always work.
3. **fastapi-app startup** (`fast_server/main.py`) returns immediately:
   - Replace `mqtt.init_app(app)` with our own startup task. It calls
     `mqtt.mqtt_startup()` in a retry loop (1, 2, 5, 10, 30 s backoff, capped) and
     records the last error. After the first successful connect, gmqtt handles
     reconnects itself (unlimited retries).
   - Replace `app.state.db = await DatabaseSingleton.get_instance()` with a
     `db_supervisor()` task (new module `fast_server/health.py`):
     - Connect loop with the same backoff. `create_pool(..., timeout=DB_CONNECT_TIMEOUT)`
       (new env var, default 5 s, instead of asyncpg's 60 s). After the first
       success, it runs `restore_capture()` and starts `camera_worker`/`imu_worker`,
       which today run inside `startup()`.
     - Then a liveness loop: `SELECT 1` with a 3 s timeout every
       `DB_HEALTH_INTERVAL` (default 10 s) flips the DB component between `ok` and
       `down`. asyncpg's pool replaces dead connections on its own, so we track
       health but never rebuild the pool. The one exception is
       `restore_backup`, which closes and reopens the pool itself and keeps doing so.
   - `app.state.db` starts as `None`. Keep `@app.on_event("startup")` (not lifespan)
     so the tests' `app.router.on_startup.clear()` pattern keeps working.
4. **tcp** (`tcp_server/tcp_server.py`): `robot_worker` waits for the DB with the
   same backoff instead of dying, and wraps its loop so an unexpected exception
   logs, sleeps and restarts the loop. `handle_robot` stops calling
   `get_instance()` per connection; it only needs the queue.

### B. Health model, 503s and safe degraded behavior

1. **`fast_server/health.py`** keeps a small registry:
   `{component: {status, error, since, last_ok, attempts, next_retry_s}}` for `db`,
   `mqtt`, `stack_controller`, `tcp` (probe `/queue/status`), `logs` and `backups`.
   For the NAS paths, it writes and deletes a probe file in a thread with a timeout.
   Status *transitions* are logged and broadcast on `/ws/misc`: once per change,
   not every retry.
2. **`GET /health`** always returns 200 while the process is alive (it doubles as
   the container healthcheck). Its body has `overall` plus every component, so it
   can't fail just because the DB is down.
3. **DB-backed endpoints** (`/session*`, `/sessions`, `/imu|camera|robot/{label}`,
   `/backup*`, session start/stop) use a `require_db()` helper. If the DB isn't
   connected, it returns **503** with `{"success": false, "error": "Database
   unavailable: <last error> (down since …, retrying in Ns)"}`. That matches the
   `error` key `apiClient.handleResponse` already reads. `/capture`, `/devices`,
   `/listen/*`, `/send/*` and WebSockets don't need the DB and keep working, so
   **monitor mode works during a DB outage**.
4. **Worker backlog cap**: if inserts fail because the DB is down, keep at most
   `MAX_BACKLOG_ROWS` (default `QUEUE_SIZE`) rows per worker. Drop the oldest beyond
   that and post one summary every 10 s instead of an error per second ("DB down
   45 s — holding 5000 IMU rows, dropped 1200"). When the DB returns, the backlog
   flushes into the same session, as today.
5. **tcp** adds `db` (status/error/since) to its `/queue/status`, so fastapi-app's
   `tcp` probe and the dashboard see robot-side DB problems too.

### C. Dashboard shows the system state (`web/src/`)

1. **`SystemHealth` component** (new, on top of `DataDashboard`), polling every 5 s:
   - It calls `GET /health`. If the fetch itself throws (`TypeError: Failed to
     fetch`, i.e. the API is unreachable), it shows a red banner saying "API
     (fastapi-app) unreachable", followed by the container state from §3.D.
   - Otherwise it shows one chip per component (green/amber/red). Each red chip
     shows the error, how long it has been down and the next retry. The banner
     collapses to a single green line when the overall state is `ok`.
2. **Disable session actions** while `db` is down (Start/Stop Session, labels,
   backups), with a tooltip giving the reason. Start Monitoring stays enabled.
3. **Local error reporting**: `sendMessage(...)` currently posts errors to the API
   in order to display them. Keep that, but also record them in the health panel's
   local "recent errors" list, so they still appear when the API is down.
4. The 5 s status poll stops swallowing errors silently. It feeds the same banner.

### D. Docker health checks, self-healing, and a Container Health box

**What Docker gives us for free.** A `healthcheck:` in compose (or `HEALTHCHECK` in
a Dockerfile) runs a command inside the container on an interval. Exit code 0 means
healthy, 1 means unhealthy. Docker stores the result in `docker inspect` under
`.State.Health`:
- `Status`: `starting`, `healthy` or `unhealthy`.
- `FailingStreak`: how many probes in a row have failed.
- `Log`: the last 5 probes, each with its exit code and the first 4 KB of its output.

It also emits `health_status` events (`docker events`). This host runs Docker
29.8, so all the options work: `interval`, `timeout`, `retries`, `start_period`
and `start_interval`. stack-controller, pgadmin and ntp already have health
checks. **fastapi-app, tcp, web and mqtt-broker don't.**

**What it doesn't do.** Plain Docker/compose only *reports* `unhealthy`. It never
restarts the container; Swarm does, compose doesn't. `restart: unless-stopped`
only fires when the process exits, so a hung but alive process stays broken
forever. We add our own restarter (item 3).

1. **Health checks on every AMS container.** Each probe prints a one-line reason,
   so Docker's own `Health.Log` explains the failure:

   | Container | Probe | Unhealthy when |
   |---|---|---|
   | fastapi-app | `python -m fast_server.healthcheck` → `GET /health` | the API doesn't answer within 5 s (hung loop, crashed worker) |
   | tcp | `python -c ...` → `GET :8090/queue/status` | the status server doesn't answer |
   | web | `wget -q -O /dev/null http://localhost/` | nginx doesn't serve the SPA |
   | mqtt-broker | `mosquitto_sub -t '$SYS/broker/uptime' -C 1 -W 3` | the broker doesn't answer a subscribe |

   Common settings: `interval: 15s`, `timeout: 5s`, `retries: 3`,
   `start_period: 30s`, `start_interval: 2s`.

   **Rule: container health means "this container works", not "its dependencies
   are up".** If fastapi-app went `unhealthy` whenever the DB was down, the
   restarter would bounce it in a loop, and a restart can't fix the NAS. So the
   probe exits 0 while the API answers, but prints the degraded parts. For example,
   `Health.Log` shows `alive; degraded: db down 3m (connection refused)`. Docker's
   own record then tells the whole story.
2. **Labels** `smr.monitor=true` (shown in the box) and `smr.autoheal=true`
   (restartable) go on mqtt-broker, fastapi-app, tcp, web, stack-controller,
   pgadmin and ntp. stack-controller doesn't get `autoheal`, since it can't
   restart itself; its `restart:` policy covers it.
3. **Restarter (watchdog) in stack-controller.** It already has `docker.sock` on
   this host. Every 30 s it restarts `smr.autoheal=true` containers that are
   `unhealthy`, with a limit of 3 restarts per container per 15 min. After that it
   stops and reports "giving up, needs a person" so it can't loop forever. It keeps
   the last 50 restart events.
4. **`GET /containers`** on stack-controller (read-only, filtered on
   `smr.monitor=true`). For each container it returns name, service, state
   (running/restarting/exited), health status, failing streak, the last probe's
   output and exit code, Docker's restart count, `started_at`/uptime, the last exit
   code, and watchdog restarts. These come straight from the Docker SDK's
   `container.attrs["State"]`, so nothing is computed by hand.
   **Crashed containers also return their last 20 log lines.** That's any
   container that is exited, restarting, or has a non-zero last exit code. A
   crashed container's health check never runs, so the log tail is the only
   explanation. This uses the same normalizer as §G, so the lines arrive as
   `LogRecord`s with levels.
5. **nginx exposes only that read-only route** (plus `/logs`, §G) as
   `/api/system/containers`, GET only. *(As built: stack-controller serves these
   two routes without its bearer token. They're read-only and public by decision,
   and its deploy/remove routes still require the token and aren't proxied.)*
   This route doesn't go through fastapi-app, so **the box keeps working when the
   API is down**.
6. **Dashboard: a separate "Container Health" box** (`web/src/components/ContainerHealth.jsx`),
   below the System Health banner from §C and polling `/api/system/containers` every 10 s:

   ```
   ┌ Container Health ──────────────────────────────────── updated 3s ago ┐
   │ ● fastapi-app      healthy    up 2h 14m   restarts 0                 │
   │     alive; degraded: db down 3m (connection refused)                 │
   │ ● tcp              healthy    up 2h 14m   restarts 0                 │
   │ ● web              healthy    up 2h 15m   restarts 0                 │
   │ ● mqtt-broker      healthy    up 6d       restarts 0                 │
   │ ● stack-controller healthy    up 6d       restarts 0                 │
   │ ● pgadmin          healthy    up 6d       restarts 0                 │
   │ ● ntp              unhealthy  up 6d       failing 4×                 │
   │     ntpd: no reachable server                       [watchdog: 1/3]  │
   └──────────────────────────────────────────────────────────────────────┘
   ```
   - Dot color: green = healthy, amber = starting or restarting, red = unhealthy
     or exited, grey = no health check.
   - A row expands to show the last 5 probes from Docker's `Health.Log`, the
     recent watchdog restarts, and, for a crashed container, its last 20 log lines
     (for example, uvicorn's `Application startup failed` traceback). It links to
     that container's filter in the Logs box (§G).
   - If `/api/system/containers` itself fails, the box says "stack-controller
     unreachable". That's the one dependency it has.

   **The two boxes answer different questions.** System Health (§C) reports
   dependencies, as seen by the app: is the DB reachable, is MQTT connected.
   Container Health reports processes, as seen by Docker: is each container up
   and answering.

### E. Logging that survives outages (`fast_server/loggers.py`)

1. The **system logger and every WARNING-or-higher record** also go to
   **stdout**, as one JSON `LogRecord` per line (§G.1). That way `docker logs`
   always has the story, including startup and each retry/backoff line, and the
   Logs box can parse it exactly. High-volume data-path lines ("Inserted 50 IMU
   rows") stay file-only, so they don't drown the Docker logs.
2. File logging goes through `QueueHandler`/`QueueListener`. Writes happen on a
   separate thread, so a hung NFS mount can't block the event loop.
3. If the log directory isn't writable, fall back to stdout-only and report the
   `logs` component as `degraded` instead of raising.
4. `LOG_DIR` env var (default `/fast_server/logs`); compose sets
   `LOG_DIR=/tcp-server/logs` for tcp so its logs reach the NAS again.

### F. NAS mounts stop being a container-start dependency (host change, needs sudo)

> **Detailed rollout, drill and rollback:** `plans/nas-mounts-plan.md`.

Docker's NFS volume driver can't start a container without its mount (coupling #1).
**Verified 2026-10-09:** a throwaway container with an NFS volume pointed at an
unreachable address hung for **185 s**, then failed with `error while mounting volume
… connection timed out`, and never started. No code in the container runs, so
none of the fixes in A–E (retries, health, logs) can apply. A restart policy
doesn't help either, because the container never started in the first place. The
realistic trigger is a lab power blip where IIoT boots faster than the NAS:
fastapi-app and tcp stay down until someone runs compose. After A, the dashboard
still loads, and §D/§G would *show* the mount error, but nothing would fix it.

Once a container has started, the NFS mount itself is fine. A `soft` mount
reconnects when the NAS comes back. **So F only fixes "the NAS is down while a
container is starting".**

Move the NFS mounts to the host and bind-mount them into the containers:

- `/etc/fstab` on IIoT, using systemd automount so a missing NAS never blocks
  boot or container start:
  ```
  192.168.1.104:/volume1/docker/postgres/backups /mnt/nas/backups nfs soft,timeo=50,retrans=2,nolock,_netdev,nofail,x-systemd.automount,x-systemd.mount-timeout=10 0 0
  192.168.1.104:/volume1/docker/postgres/logs    /mnt/nas/logs    nfs soft,timeo=50,retrans=2,nolock,_netdev,nofail,x-systemd.automount,x-systemd.mount-timeout=10 0 0
  ```
- Compose uses bind mounts with `bind: {propagation: rslave}`, so a mount that
  appears after the container starts (the NAS came back) is visible inside it.
- With automount, the path is either the NAS or an error, never the host's
  local disk. The `backups` health probe refuses backups when it fails, and the
  `logs` probe falls back to stdout (§E).
- The `docker-compose.local.yml` copy keeps its local volumes and doesn't change.

### G. Logs box: recent Docker logs and important events, ready for priorities

**Goal.** One dashboard box shows two kinds of log:
- the most recent **Docker logs** of the AMS containers
- the **important events** a person should notice, such as a dependency going down
  or recovering, a watchdog restart, session start/stop, backup results, dropped
  data batches, or a stack deploy failure

Both use **one record format**, which has a slot for a `priority` we don't assign
yet.

**1. One record format: `LogRecord`** (`common/log_schema.py`, a tiny module copied
into the fastapi-app, tcp and stack-controller images):

```python
{
  "id":        "AMS-fastapi:2026-10-09T13:45:28.123456Z:0",  # stable, used for dedup and cursors
  "ts":        "2026-10-09T13:45:28.123Z",          # UTC ISO-8601
  "source":    "fastapi-app",                       # compose service (or container name)
  "logger":    "system",                            # logger / component that wrote it
  "level":     40,                                  # severity, Python numbers: 10 DEBUG … 50 CRITICAL
  "level_name":"ERROR",
  "priority":  None,                                # RESERVED: how urgently a person must act (see 4)
  "category":  "health",                            # health|session|ingest|backup|deploy|watchdog|system|other
  "important": True,                                # goes to the "Important" tab
  "message":   "Database down: connection refused (192.168.1.104:5433)",
  "context":   {"component": "db", "attempt": 7}    # optional structured extras
}
```
- **`level`** is the *severity* of the event, set when it's written.
- **`priority`** is how urgently a *person* should act on it. Today it's always
  `None` and nothing depends on it. Keeping the two separate means a future
  priority scheme can rank events without touching how severity is logged.
  For example, "WARNING, but P1 because a session is recording" vs "ERROR, but
  P3 during monitor mode".

**2. Producers write `LogRecord`s.**
- **fastapi-app and tcp**: a `JsonLineFormatter` on the stdout handler (§E.1)
  emits each record as one JSON line. A helper
  `log_event(category, message, level=INFO, important=True, **context)` in
  `fast_server/loggers.py` is the one call site for important events. It's used by
  the health transitions (§B.1), session start/stop, `try_backup`, stack
  deploy/remove failures, the backlog-drop summaries (§B.4) and the capture
  restore at startup. Existing `log_system_logger(...)` calls keep working and
  become plain (`important=False`) records.
- **stack-controller**: watchdog restarts and give-ups go through the same
  `log_event`.
- **Third-party containers** (nginx, mosquitto, pgadmin, ntp) can't be changed.
  Their plain-text lines are normalized when they're read (item 3).

**3. One reader: `GET /logs` on stack-controller** (read-only, same
`smr.monitor=true` whitelist, proxied by nginx as `/api/system/logs` like §D.5,
so **it works when fastapi-app is down**):
- Query: `since` (cursor = last `ts` seen), `tail` (default 200, max 1000),
  `source` (repeatable), `min_level`, `important_only`.
- Reads with the Docker SDK (`container.logs(timestamps=True, since=…, tail=…)`)
  for each container, merges by time, and returns `{"records": [...], "cursor": "..."}`.
- **Normalizer** (`stack_controller/log_normalize.py`):
  - JSON lines that parse as a `LogRecord` pass through.
  - Our existing text format `YYYY-MM-DD HH:MM:SS [LEVEL] name: msg` is parsed
    by regex.
  - nginx (`[emerg]`, `[error]`, `[warn]`), mosquitto and uvicorn
    (`ERROR:`/`WARNING:`) have small per-source patterns.
  - Python tracebacks are folded into the record they belong to.
  - Anything else becomes INFO.

  Each source's patterns live in one table, so adding a container means adding
  one row.
- **Redaction**: a final pass masks `password=`, `PGPASSWORD`, `Bearer …` and
  `postgres://user:pass@`, so a misbehaving container can't leak a credential
  onto the dashboard.
- **Retention**: compose gets `logging: {driver: json-file, options: {max-size:
  "10m", max-file: "5"}}` on every AMS service. History survives restarts (not
  recreates) and disk use is bounded.

**4. Room for priority later.** Nothing in this phase assigns a priority, but the
plumbing is in place:
- A `classify(record) -> record` hook in `common/log_schema.py`, a no-op today,
  is where a priority policy will go. Rules like "db down while RECORD → P1"
  would read the record plus the current capture mode, and nothing else changes.
- `/logs` already accepts `min_priority`; it's ignored while every record has
  `priority: None`.
- The UI shows a priority badge only when `priority` is set, and its filter menu
  is built from the levels/priorities actually present.

**5. Dashboard: a "Logs" box** (`web/src/components/LogsPanel.jsx`, below Container
Health):

```
┌ Logs ─────────────── [Important | All] [source ▾] [level ≥ ▾] [⏸ pause] ┐
│ 13:45:28  ERROR  fastapi-app  health   Database down: connection refused │
│ 13:45:31  WARN   watchdog     watchdog Restarted AMS-tcp (unhealthy 3×)  │
│ 13:46:02  INFO   fastapi-app  health   Database recovered after 34s      │
│ 13:47:10  INFO   fastapi-app  session  Session 812 started (imu/106, …)  │
│ ▸ 13:47:12 ERROR nginx        [emerg] host not found in upstream …       │
└─────────────────────────────────────────── showing 200 · updated 2s ago ┘
```
- **Important** tab (default): `important` records plus anything WARNING or
  above. **All** tab: every Docker log line from the selected sources.
- It polls `/api/system/logs?since=<cursor>` every 3 s and appends. It keeps the
  last 1000 records in memory, pauses auto-scroll while you're reading, and
  multi-line records (tracebacks) expand.
- It doesn't replace the live message boxes. Those stay for the per-device data
  feed; this box is the system's own record.
- Errors the dashboard itself hits (failed fetches, §C.3) are added locally as
  `source: "dashboard"` records, so they appear even when everything server-side
  is unreachable.

---

## 4. Rollout order and testing

Phases are independent enough to ship one at a time. Recommended order:
**A + E** (stop the crashes, make logs visible) → **B** → **C** → **D** → **G** → **F**.
E already writes JSON `LogRecord`s to stdout, so G only has to add the reader
and the box.

**Tests** (new `tests/health_test.py`, plain `unittest` like the rest):
- Startup with `DatabaseSingleton.get_instance` patched to raise. The app serves
  `/health` with `db: down`; DB routes return 503 with an `error` body; `/capture`
  and `/listen/start` still work. A later successful attempt starts the workers
  and runs `restore_capture`.
- The MQTT connect retry loop recovers after N failures.
- The backlog cap drops the oldest rows and summarizes instead of spamming.
- tcp: `robot_worker` survives `get_instance` raising and then flushes once it
  succeeds (extends `tests/tcp_capture_test.py`).
- stack-controller: the `/containers` whitelist and the watchdog restarting only
  labelled, unhealthy containers (docker SDK mocked, extends
  `tests/stack_controller_test.py`), and the 3-per-15-min restart cap.
- Logs: `JsonLineFormatter` output round-trips through the normalizer. The
  normalizer handles sample lines from nginx/mosquitto/uvicorn/our text format and
  folds tracebacks. Redaction masks the credential patterns. `/logs` applies the
  `since` cursor and merges sources in time order. `classify()` is a no-op and
  leaves `priority: None`.

**On prod** (with no session active; `GET /session`):
- Tag rollback images as before. You recreate containers yourself
  (`docker compose up -d --build ...`).
- Fault drills, each read-only from my side: point `DB_HOST` at a dead address
  in a throwaway compose override or stop the `local-db` postgres. Run
  `docker stop AMS-mqtt-broker`, then `docker stop AMS-fastapi`. Each time check
  that the dashboard still loads, the banner names the failing piece and its
  error, `docker logs` explains it, and things recover by themselves when the
  dependency returns.
- Phase F needs a maintenance window (host fstab change, then recreate
  fastapi-app/tcp) and an NFS unmount/remount drill.

**Docs**: add `web/docs/operations/troubleshooting.md` ("dashboard says X is down
— what to check"), update `web/docs/docker/compose.md` (restart policies, health,
host NFS mounts, log rotation), document the `LogRecord` format and `log_event()` in a new `web/docs/docker/logging.md`, and update the CLAUDE.md architecture bullet.

---

## 5. Decisions needed

1. **Phase F (host NFS automount)** changes `/etc/fstab` on IIoT and needs `sudo`.
   You'd run those steps. Without F, everything else still helps, but a NAS outage
   *at container start* still blocks fastapi-app and tcp from starting. (The web
   container is fine after A.)

**Decided:**
- **Container state and logs (§D, §G) are public** to anyone who can open the
  dashboard. There's no login on `/api/system/*`. They stay read-only and limited
  to labelled AMS containers, with credentials redacted.
