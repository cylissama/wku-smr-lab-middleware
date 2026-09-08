# Database uses

The system uses a single PostgreSQL database (hosted on the Synology NAS) as the source of truth for all telemetry. All access goes through `db/database.py`'s `DatabaseSingleton`, an `asyncpg` connection pool shared by both `fastapi-app` (IMU/camera) and `tcp` (robot).

## Session-scoped ingestion

Nothing is written to the telemetry tables without an active **session**:

- `GET /session/start/{label}` creates a `session` row and caches it as the "current" session.
- Every insert (`insert_imu_batch`, `insert_robot_batch`, `insert_camera_batch`, …) first calls `get_latest_session()` and raises `SessionNotStarted` if none is active — this is why the dashboard shows red "batch insert failed: No current active session" messages when devices publish before a session is started. Per the lab's running-a-test SOP (dashboard Info library), these are expected and safe to ignore.
- `GET /session/stop` closes the session (`ended_at`) and **automatically triggers a database backup** — see [Automations](/docker/automations).

Devices are also tracked and cached per-session: the first time a `device_label` is seen, `get_or_create_device_id()` inserts (or looks up) a `device` row and links it to the current session via `session_device`, so it's always possible to answer "which devices reported data in session X."

## Batched writes

Both the FastAPI app and the TCP server buffer incoming messages in an in-memory `asyncio.Queue` and flush them in batches (`insert_*_batch`) rather than one row per message. A flush happens when either threshold is hit first:

- `BATCHES` messages have queued up, or
- `B_TIMEOUT` seconds have passed since the last flush.

Both are tunable via `.env` (`BATCHES`, `B_TIMEOUT`, `QUEUE_SIZE`). This keeps insert volume manageable under high-frequency IMU sampling (100 Hz by default) without adding ingestion latency that operators would notice.

## Reading data back

| Endpoint | Returns |
| --- | --- |
| `GET /sessions` | All sessions (`id`, `label`) |
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

Because parsing, database inserts, and table columns all have to agree on field order, schema changes follow a fixed sequence (see `project/SOP/database-updates.md` and `project/db/migrations.md` for the full history):

1. **Add the column(s)** in Postgres (pgAdmin or `ALTER TABLE ... ADD COLUMN`), without `NOT NULL` — existing rows would violate that constraint immediately. Backfill first, then tighten the constraint later if needed.
2. **Update parsing** — `fast_server/parsing.py` for IMU/camera, `tcp_server/tcp_server.py` for the robot. Field order here must match the order the device actually sends data in.
3. **Update the matching insert method(s)** in `db/database.py` — both the `_item()` and `_batch()` variants for that device type, keeping the tuple order aligned with the `INSERT ... VALUES` column list.
4. **Rebuild and restart**: `docker compose down && docker compose up --build` on the Data Broker Mini PC so the new code is actually running.

See [Database structure](/data/database-structure) for the current table layout.
