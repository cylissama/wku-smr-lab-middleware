# The hardware behind the project

The system spans an always-on AMS host, a Synology NAS, Raspberry Pi edge nodes, the cell PLC and a FANUC robot arm, all on the lab network described in [Network topology](/network/topology). Addresses for everything are in the [IP Address Table](/network/ip-addresses).

## Core infrastructure

| Machine | Address | Role |
| --- | --- | --- |
| [AMS host](/hardware/data-broker-mini-pc) (mini PC, hostname `IIoT`) | 192.168.2.100 | Runs the always-on `docker-compose.yml` stack and is the Docker Swarm manager for the edge nodes |
| **Synology NAS** | 192.168.1.104 | PostgreSQL (port 5433), plus the NFS shares for database backups and log files |
| [Cell PLC](/hardware/plc) (Allen-Bradley 1769-L32E) | 192.168.1.103 | Signals the start and end of each robot run; drives [PLC auto stop](/operations/plc-auto-stop) and the IMUs' PLC trigger |
| [FANUC robot arm](/hardware/robot-arm) | 192.168.1.100 | Streams joint angles and tool pose to the AMS over TCP |
| **Alienware PC** | 192.168.1.119 | Lab workstation; runs Portainer |

## Edge nodes

| Kind | Nodes | Page |
| --- | --- | --- |
| IMU | RPIIMUJ1–RPIIMUJ5 (192.168.1.106–110), RPI-IMU-BENCH | [IMU nodes](/hardware/imu) |
| Camera | RPiCamFront, CameraPi2 | [Camera nodes](/hardware/camera) |

Every edge node is a Docker Swarm worker. The dashboard deploys its container when you start monitoring or a session; see [Swarm](/docker/swarm).

## Time synchronization

All containers share time through the `ntp` container (`cturra/ntp`), which syncs from Google's public NTP pool. On hosts where this matters, the host's own `chrony` / `systemd-timesyncd` are stopped, disabled and masked, so the container is the only time source and telemetry timestamps stay comparable across devices. See [Automations](/docker/automations#time-synchronization).

## Related repositories

See [GitHub repos](/overview/repositories).
