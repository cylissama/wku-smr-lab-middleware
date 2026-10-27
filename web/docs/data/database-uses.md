# Database uses

The system uses a single PostgreSQL database (hosted on the Synology NAS) as the source of truth for all telemetry. All access goes through `db/database.py`'s `DatabaseSingleton`, which wraps an `asyncpg` connection pool. `fastapi-app` (IMU/camera) and `tcp` (robot) are separate containers, so each has its own pool and its own caches, but both write to the same database.

## Session-scoped ingestion

Nothing is written to the telemetry tables outside a recording **session**. Two things gate it:

- **Capture mode.** Only `RECORD` stores data. In `IDLE` nothing is deployed, and in `MONITOR` the dashboard shows live samples but nothing is queued for the database. See [Capture modes & sessions](/overview/capture-modes).
- **The session row.** `GET /session/start/{label}?session_label=…` creates a `session` row (its type must exist in `session_label`, and the device selection and run parameters are stored with it), then switches to `RECORD`. Inserts call `get_latest_session()` and raise `SessionNotStarted` if none is open.

Each queued message carries the id of the session it arrived in. When a session ends, workers drop anything left from it instead of writing it into the next one. `GET /session/stop` (or a [PLC pulse](/operations/plc-auto-stop)) closes the session (`ended_at`) and **automatically triggers a database backup**; see [Automations](/docker/automations).

Devices are also tracked per session: the first time a `device_label` is seen, `get_or_create_device_id()` inserts (or looks up) a `device` row and links it to the current session via `session_device`, so it's always possible to answer "which devices reported data in session X."

## Batched writes

Both the FastAPI app and the TCP server buffer incoming messages in an in-memory `asyncio.Queue` and flush them in batches (`insert_*_batch`) rather than one row per message. A flush happens when either threshold is hit first:

- `BATCHES` messages have queued up, or
- `B_TIMEOUT` seconds have passed since the last flush.

Both are tunable via `.env` (`BATCHES`, `B_TIMEOUT`, `QUEUE_SIZE`). This keeps insert volume manageable under high-frequency IMU sampling (100 Hz by default, changeable per run as a [run parameter](/operations/run-parameters)) without adding ingestion latency that operators would notice.

## Reading data back

These return a whole session at once; for analysis, query the database directly ([Accessing the database](/data/accessing-database)). Full route list: [API reference](/docker/api).

| Endpoint | Returns |
| --- | --- |
| `GET /sessions` | All sessions (`id`, `label`) |
| `GET /session/labels` | Session types from `session_label` |
| `GET /session` | The currently active session, if any |
| `GET /imu/{label}` | All `imu_measurement` rows for a session label |
| `GET /camera/{label}` | All `image_detection` rows for a session label |
| `GET /robot/{label}` | All `robot` rows for a session label, in two shapes |

`GET /robot/{label}` is notable: alongside the raw rows, it also returns a `twins` array — one object per row shaped as `{ ts, joints: [...6], tcp: [x,y,z], quat: [w,p,r,1] }` — reshaped specifically for the digital-twin visualization consumers.

## Backup and restore

- `db.create_backup()` runs `pg_dump -F c` into the NFS-mounted `/db_backups` volume (backed by the Synology NAS), named `<db>_<UTC timestamp>.dump`. This runs automatically on every `session/stop`, and can also be triggered directly via `GET /backup`.
- `GET /backup/list` lists available `.dump` files.
- `POST /backup/restore/{filename}` is destructive: it terminates all other connections to the database, drops it, recreates it, and runs `pg_restore` from the chosen dump — then reconnects the pool and clears all in-memory caches (devices, session history, current session).

## Changing the schema

Because parsing, database inserts, and table columns all have to agree on field order, schema changes follow a fixed sequence — see [Updating the production database schema](/data/schema-changes) for the full walkthrough (adding a column, and adding a new linked table), and `db/migrations.md` for the change history.

See [Database structure](/data/database-structure) for the current table layout.
