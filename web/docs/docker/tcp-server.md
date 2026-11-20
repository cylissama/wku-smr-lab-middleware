# TCP Server (Robot Ingestion)

The `tcp` service is a raw TCP listener dedicated to the robot arm. Unlike IMU and camera devices, which publish over MQTT to `fastapi-app`, the robot streams directly over a plain TCP socket to this container. It's built from `tcp_server/dockerfile` and run as its own service in `docker-compose.yml` — see [Compose](/docker/compose) for how it fits into the rest of the stack.

## How the robot connects

The robot is started manually by a human operator in the lab rather than being remotely orchestrated (see [Robot Arm](/hardware/robot-arm)). Once started, its controller opens a persistent TCP connection to the Data Broker Mini PC:

```
<mini-pc-ip>:${ROBOT_TCP_PORT}
```

`ROBOT_TCP_PORT` is set in `.env` (5001 by default). There's no handshake or auth beyond the TCP connect itself — once connected, the robot just streams CSV lines continuously for as long as it's running. It is *not* request/response: nothing is sent back to the robot on this socket.

## How the container listens

`tcp_server.py`'s `main()` does two things at startup:

1. Creates the camera/imu/robot loggers (`fast_server/loggers.py`). Per-line data logs go to **files** under `LOG_DIR=/tcp-server/logs` (the NAS `logs` share, shared with `fastapi-app`). The system log and every warning or error also go to stdout as JSON records, so `docker logs AMS-tcp-listener` and the dashboard's Logs box show what matters. See [Health & logs](/docker/health-and-logs#logs).
2. Calls `asyncio.start_server(handle_robot, host="0.0.0.0", port=ROBOT_TCP_PORT)`, which binds and logs a line like:
   ```
   [TCP] Listening on ('0.0.0.0', 5001)
   ```

It also starts a small HTTP **status server** on port `8090` (internal, not published), used by `fastapi-app`:

| Route | Used for |
| --- | --- |
| `GET /queue/status` | queue depth, open robot connections, DB status and receiving rate. Used by the Devices box, the System Health strip, the session-stop drain, and the container health check. |
| `PUT /capture` | `fastapi-app` pushes the [capture mode](/overview/capture-modes) and device selection here on every change |

`tcp` also re-reads `GET /capture` from `fastapi-app` every `CAPTURE_SYNC_INTERVAL` seconds (default 5), in case a push was missed.

From there, per connection, `handle_robot()`:

- Reads up to 4096 bytes at a time, normalizes `\r\n`/`\r` to `\n`, and splits on newlines to recover individual samples (the robot doesn't need to send exactly one sample per TCP packet).
- Parses each line as comma-separated fields (see format below), then applies the capture gate. While idle, or if `robot/main` isn't selected, the line is dropped. While monitoring (not while recording), at most one `[live]` line per second goes to the dashboard's Robot box. Only while **recording** is the line tagged with the session id and pushed onto an in-memory `asyncio.Queue` (`robot_queue`, capacity `QUEUE_SIZE`).
- A line that fails to parse is logged as a parse error and dropped — it does **not** close the connection or crash the handler, so one bad sample doesn't take down the rest of the run.
- When the robot disconnects (or a `read()` returns empty), the handler closes the writer and logs `Writer Closed`.

A separate background task, `robot_worker()`, drains `robot_queue` and flushes to Postgres in batches — the same batch/timeout pattern used for IMU and camera ingestion (see [Automations](/docker/automations)):

- Flush when `BATCHES` rows have queued up, **or**
- `B_TIMEOUT` seconds have elapsed since the last flush,
- whichever comes first.

On a successful flush, it also POSTs a short summary (`"Inserted N robot rows."`) to `fastapi-app`'s `/send/robot` endpoint so it shows up in the dashboard's live message feed.

## Data format on the wire

Each sample is a single newline-terminated line of comma-separated values, in this exact order:

| Position | Field | Type | Notes |
|---|---|---|---|
| 0 | `frame_id` | Integer | Karel loop counter (`count`) |
| 1 | `ts_epoch` | Integer | Robot controller clock from Karel `GET_TIME`: **packed FANUC date-time, not epoch seconds**, 2 s resolution, not NTP-synced. See [Robot Arm → Timestamps](/hardware/robot-arm#timestamps) |
| 2 | `ts_string` | String | Same time as text (`CNV_TIME_STR`); not stored |
| 3–8 | `joint_1`…`joint_6` | Float | Joint angles/positions |
| 9–11 | `x`, `y`, `z` | Float | TCP (tool center point) position |
| 12–14 | `w`, `p`, `r` | Float | TCP orientation (yaw/pitch/roll) |

Example line:
```
1, 1567387795,12-NOV-26 14:04 , .001552, .001158, -.000283, .000938, -90.000603, -.000223, 1783.117, -2205.963, 928.994, 179.999, .000, .001
```

(A real line from session 544. The robot also sends a header line `count,ts_int,ts_str,J1,...` on connect, which fails to parse and is logged as a parse error.)

This maps directly onto the `robot` table columns described in [Robot Arm](/hardware/robot-arm) and [Database structure](/data/database-structure), plus `recorded_at`/`ingested_at`/`device_id`/`session_id` added at insert time.

`tcp_server` adds two timestamps from the AMS host clock, which is NTP-synced:

- `recorded_at`: set as each line arrives (`datetime.now(timezone.utc)` in the read loop).
- `ingested_at`: set once per batch in `insert_robot_batch()` when the batch is written, so all rows in a batch share it.

`ts_epoch` is stored unchanged. For cross-device timing use `recorded_at` (see [Robot Arm → Timestamps](/hardware/robot-arm#timestamps)).

> **Note:** the read loop also runs `strptime(parts[0], "%m/%d/%Y %H:%M")` with a US/Eastern conversion into a local `ts_epoch`. Field 0 is the frame counter, so this always fails, and nothing uses the result. The tcp image also has no tzdata, so `ZoneInfo("US/Eastern")` would fail anyway. The stored `ts_epoch` is field 1 as-is. This block is dead code and can be removed.

## Failure modes

- **Not recording**: lines are dropped at the gate and never queued, so nothing from before a session leaks into it.
- **Session ended while a batch was queued**: the batch is dropped ("Robot batch of N dropped: no active session") instead of being written into the next session.
- **Database unreachable**: the TCP socket binds and accepts connections independently of the database. The worker waits for the database with backoff, keeps at most `MAX_BACKLOG_ROWS` rows while inserts fail, and reports this in the log and on the dashboard's **Robot TCP server** health chip.
- **Malformed line**: logged as a parse error and skipped; the connection stays open.

## Manually testing the socket

To confirm the listener is up without waiting for the robot:

```bash
nc -vz <mini-pc-ip> <ROBOT_TCP_PORT>
```

A bare `-z` probe (no data sent) still exercises the full accept path — you'll see a `Writer Closed` line appear in the log for that connection, confirming `handle_robot` ran end-to-end. To exercise parsing too, send an actual line:

```bash
printf "1,1710000000.0,2024-03-09T12:00:00,0.1,0.2,0.3,0.4,0.5,0.6,10.0,20.0,30.0,1.0,0.0,0.0\n" | nc <mini-pc-ip> <ROBOT_TCP_PORT>
```

If the dashboard is monitoring with the robot selected, a `[live]` line appears in the Robot box (recording doesn't show them; check the robot tile's rate instead). While idle, the line is accepted on the socket and then dropped, which is expected and doesn't mean the TCP layer failed.
