# Troubleshooting

What to do when the dashboard says something is wrong. The dashboard has three places that explain problems:

- **System strip** at the bottom of the session box, with the **System Health** card under it whenever something is down: what the API can't reach, the error, and when it retries.
- **Container Health** at the bottom of the page: each container's state from Docker, its health checks, restarts, and the last log lines of anything that crashed.
- **Logs** next to it: recent logs from every container. The **Important** tab shows only what needs attention.

Most problems fix themselves: connections are retried, and crashed or unhealthy containers are restarted. Act when something stays red.

## "API unreachable"

`fastapi-app` isn't answering. Sessions can't be started or stopped until it's back.

1. Look at `fastapi-app` in **Container Health**. If it's `restarting` or `exited`, its last log lines say why (for example a Python traceback).
2. If it isn't coming back on its own, on the Data Broker Mini PC:
   ```bash
   cd /home/ubuntu/wku-smr-lab-middleware
   docker compose ps fastapi-app
   docker logs --tail 50 AMS-fastapi
   docker compose up -d fastapi-app
   ```

If Container Health also says **stack-controller unreachable**, check `docker compose ps` for the whole stack.

## Database down

The **Database** chip is red; Start Session and backups are disabled with the reason as a tooltip. Monitoring still works, and an active session can still be stopped.

- `no answer within 5s (host down or unreachable?)`: the NAS (`192.168.1.104`) is off, rebooting, or not reachable from the Mini PC. Check that the NAS is on and reachable (`ping 192.168.1.104`).
- `Connection refused`: the NAS is up but Postgres isn't running on port 5433. Check the Postgres container on the NAS.
- `password authentication failed`: `DB_USER`/`DB_PASSWORD` in `.env` don't match the database.

The API reconnects by itself (every 30 s at most) once the database is back. Nothing needs restarting.

If a session was stopped while the database was down, the System Health card says so; its end time is saved automatically when the database returns. Data that was still buffered at that moment was not stored.

## MQTT broker down

IMU and camera data can't arrive. Check `mqtt-broker` in Container Health; it's restarted automatically if it crashes or stops answering its health check. The API reconnects by itself once the broker is back.

## Log files or backup folder down

The NAS share (`/volume1/docker/postgres/logs` or `/backups`) isn't writable. Logs still go to `docker logs` and the Logs box; backups fail until it's back. Usually the NAS itself is down; see "Database down".

If the NAS was down when the Mini PC (or `fastapi-app`/`tcp`) started, those containers may not start at all: Docker can't mount the NFS volumes. Container Health then shows them as `created` or `exited` with a mount error. Once the NAS is back:

```bash
docker compose up -d fastapi-app tcp
```

## "Watchdog gave up — needs a person"

A container failed its health check, was restarted 3 times in 15 minutes, and is still unhealthy. Expand it in Container Health: the last health checks and log lines say why. Fix the cause, then restart it with `docker compose up -d <service>`; the watchdog resets once it's healthy again.

## Robot TCP server down

The robot can't stream. Check `tcp` in Container Health. A red **Robot TCP server** chip with `tcp can't reach the database` is the database problem above, seen from the robot side.
