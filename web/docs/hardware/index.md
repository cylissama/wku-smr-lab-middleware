# The hardware behind the project

The system spans an always-on AMS host, a Synology NAS, Raspberry Pi edge nodes, the cell PLC and a FANUC robot arm, all on the lab network described in [Network topology](/network/topology). Addresses for everything are in the [IP Address Table](/network/ip-addresses).

## Core infrastructure

| Machine | Address | Role |
| --- | --- | --- |
| [AMS host](/hardware/data-broker-mini-pc) (mini PC, hostname `AMS`) | 192.168.2.100 | Runs the always-on `docker-compose.yml` stack and is the Docker Swarm manager for the edge nodes |
| **Synology NAS** | 192.168.1.104 | PostgreSQL (port 5433), plus the NFS shares for database backups and log files |
| [Cell PLC](/hardware/plc) (Allen-Bradley 1769-L32E) | 192.168.1.103 | Signals the start and end of each robot run; drives [PLC auto stop](/operations/plc-auto-stop) and the IMUs' and cameras' PLC trigger |
| [FANUC robot arm](/hardware/robot-arm) | 192.168.1.100 | Streams joint angles and tool pose to the AMS over TCP |
| **Alienware PC** | 192.168.1.119 | Lab workstation; runs Portainer |

## Edge nodes

| Kind | Nodes | Page |
| --- | --- | --- |
| IMU | RPIIMUJ1–RPIIMUJ6 (192.168.1.106–111) | [IMU nodes](/hardware/imu) |
| Camera | RPICAM1–RPICAM4 (192.168.1.114, .113, .94, .60) | [Camera nodes](/hardware/camera), [ArUco markers](/hardware/aruco-markers) |

Every edge node is a Docker Swarm worker. The dashboard deploys its container when you start monitoring or a session; see [Swarm](/docker/swarm).

## Time synchronization

Containers have no clock of their own; they all read the AMS host's kernel clock. On the AMS that clock is set by `systemd-timesyncd` (from `ntp.ubuntu.com`). The `ntp` container (`cturra/ntp`) syncs from Google's NTP servers and serves NTP on UDP 123, but runs `chronyd -x`, so it doesn't set the AMS clock. The two agree to well under a millisecond. See [Automations](/docker/automations#time-synchronization).

| Device | Timestamp source | NTP-synced |
|---|---|---|
| AMS containers (`recorded_at`, `ingested_at`, session times) | AMS host clock | Yes |
| Robot controller (`robot.ts_epoch`) | Controller's own clock, packed FANUC format, 2 s resolution | **No**, drifts by tens of seconds ([details](/hardware/robot-arm#timestamps)) |

To compare robot data with other devices, use `recorded_at`, which comes from the AMS clock.

## Related repositories

See [GitHub repos](/overview/repositories).
