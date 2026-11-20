# Automations

Things that happen automatically, without an operator running a manual command:

## Automatic database backups

Every time a session ends (`GET /session/stop`, or a PLC stop), `fastapi-app` starts `try_backup()` in the background once the session is ended — a `pg_dump` runs unprompted and lands in the NFS-mounted `/db_backups` volume on the NAS. The stop doesn't wait for it (it takes about 20 s), so the next session can start right away. If another session ends while it runs, one more backup follows it; manual backups and restores are refused until it's done. Operators don't need to remember to back up after a test; the only manual backup path (`GET /backup`) exists for on-demand use outside of a session. See [Database uses](/data/database-uses) for the full backup/restore flow.

## Batched ingestion flushing

Both `fastapi-app` (IMU/camera) and `tcp` (robot) run background `asyncio` workers that automatically flush their queues to Postgres whenever `BATCHES` messages have queued up **or** `B_TIMEOUT` seconds have elapsed — whichever comes first. Nothing manual triggers a flush; it's purely time/size driven, which keeps ingestion latency bounded even at low device throughput.

## Container restarts, health checks and the watchdog

- Every AMS container has `restart: unless-stopped` and a Docker health check. stack-controller's **watchdog** restarts containers labelled `smr.autoheal` that turn `unhealthy`, at most 3 times per 15 minutes. See [Health & logs](/docker/health-and-logs).
- Each edge service has a 10 s health check (`imu_edge healthcheck` / `camera_edge healthcheck`). Swarm restarts IMUs `on-failure` and cameras on `any` exit.

## Edge stack up and down with each run

Start Monitoring and Start Session deploy the selected edge devices; Stop Monitoring and Stop Session remove them. The exception is a PLC stop with [Keep edge running](/operations/plc-auto-stop#back-to-back-sessions-keep-edge-running) on, which leaves them up for the next session. Nobody runs `docker stack deploy` by hand. See [Stack controller & device selection](/docker/stack-controller).

## PLC auto stop

When the robot finishes, the cell PLC pulses `Db_Stop` and the recording session stops by itself, with the same steps as the Stop button (minus the stack removal when Keep edge running is on). See [PLC auto stop](/operations/plc-auto-stop).

## Time synchronization

Two NTP clients run on the AMS, and only one of them sets the clock:

- **`systemd-timesyncd` on the host** syncs the AMS kernel clock from `ntp.ubuntu.com` (`timedatectl` shows `System clock synchronized: yes`). Every container reads this clock, so it's the source of `recorded_at`, `ingested_at`, session start/end times and log timestamps.
- **The `ntp` container** (`cturra/ntp`, chrony) syncs from `time1`–`time4.google.com` and serves NTP to the lab on UDP 123 (`NTP_PORT`). It runs `chronyd -x`, so it doesn't set the system clock even though it has `SYS_TIME`. Check it with `docker exec AMS-ntp chronyc tracking`.

On 2026-11-18 the two agreed to about 0.5 ms. The `NTP_SERVER=ntp` variable set on `fastapi-app` and `tcp` isn't read by any code.

The robot controller isn't synced to either; see [Robot Arm → Timestamps](/hardware/robot-arm#timestamps).

## Dashboard document library generation

The dashboard's "Info" page (SOPs, diagrams, reference files under `public/info/`) is backed by `manifest.json`, but that file isn't hand-edited during normal development. `npm run manifest:info` (`scripts/generate-info-manifest.mjs`) runs automatically as the `prebuild` step before every `vite build`:

- scans `public/info/` for files,
- keeps any hand-authored `title`/`description`/`category`/`tags` for files it already knows about,
- fills in sensible defaults (title-cased filename, type-based category) for anything new,
- and rewrites `manifest.json`.

Dropping a new SOP or diagram into `public/info/` and rebuilding is enough for it to show up in the dashboard — no manifest editing required.
