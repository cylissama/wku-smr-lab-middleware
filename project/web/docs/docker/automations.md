# Automations

Things that happen automatically, without an operator running a manual command:

## Automatic database backups

Every time a session ends (`GET /session/stop`), `fastapi-app` calls `try_backup()` before returning — a `pg_dump` runs unprompted and lands in the NFS-mounted `/db_backups` volume on the NAS. Operators don't need to remember to back up after a test; the only manual backup path (`GET /backup`) exists for on-demand use outside of a session. See [Database uses](/data/database-uses) for the full backup/restore flow.

## Batched ingestion flushing

Both `fastapi-app` (IMU/camera) and `tcp` (robot) run background `asyncio` workers that automatically flush their queues to Postgres whenever `BATCHES` messages have queued up **or** `B_TIMEOUT` seconds have elapsed — whichever comes first. Nothing manual triggers a flush; it's purely time/size driven, which keeps ingestion latency bounded even at low device throughput.

## Container restart policies and healthchecks

- `ntp` runs with `restart: unless-stopped`, so it comes back automatically after a host reboot or crash.
- Each IMU Swarm service has `restart_policy: condition: on-failure` and a 30s-interval healthcheck (`imu_edge healthcheck`) — Swarm restarts a task automatically if it starts failing that check.

## Time synchronization

The `ntp` container syncs from Google's public NTP pool automatically and is the shared clock for every other container. On hosts where this matters, the host's own `chrony`/`systemd-timesyncd` are stopped, disabled, and **masked**, so nothing on the host can silently re-enable a competing time source — the container's NTP sync is the only one running.

## Dashboard document library generation

The dashboard's "Info" page (SOPs, diagrams, reference files under `public/info/`) is backed by `manifest.json`, but that file isn't hand-edited during normal development. `npm run manifest:info` (`scripts/generate-info-manifest.mjs`) runs automatically as the `prebuild` step before every `vite build`:

- scans `public/info/` for files,
- keeps any hand-authored `title`/`description`/`category`/`tags` for files it already knows about,
- fills in sensible defaults (title-cased filename, type-based category) for anything new,
- and rewrites `manifest.json`.

Dropping a new SOP or diagram into `public/info/` and rebuilding is enough for it to show up in the dashboard — no manifest editing required.
