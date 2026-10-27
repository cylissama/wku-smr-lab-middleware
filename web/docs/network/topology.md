# Topology

How the parts of the system reach each other. Every address is in the [IP Address Table](/network/ip-addresses), copied from the lab SharePoint sheet. That sheet is the authoritative source: update it there first, then sync the table.

```text
 192.168.1.x  (robot cell)                         192.168.2.x
 ┌─────────────────────────────────────┐          ┌──────────────────────────┐
 │ FANUC robot       192.168.1.100 ────┼─ TCP ───►│ AMS host "IIoT"          │
 │ Cell PLC (L32E)   192.168.1.103 ◄───┼─ CIP ────│ 192.168.2.100            │
 │ NAS (Postgres)    192.168.1.104 ◄───┼─ SQL/NFS─│  docker-compose stack    │
 │ IMU Pis           192.168.1.106–110 ┼─ MQTT ──►│  + Swarm manager         │
 │ Camera Pis        192.168.1.113–114 ┼─ MQTT ──►│                          │
 └─────────────────────────────────────┘          └──────────────────────────┘
        IMU Pis also read the PLC (CIP) directly.
        The bench IMU Pi (RPI-IMU-BENCH) is on 192.168.4.x.
```

::: info Placeholder
TODO: how the subnets are routed (which device routes between 192.168.1.x, 2.x and 4.x; the UniFi gateway at 192.168.1.1?), and whether any firewall rules matter for the AMS.
:::

## Ports

| Port | Proto | On | Used by |
| --- | --- | --- | --- |
| 80 | TCP | AMS | Dashboard and these docs (`web`); `/api/` proxies to `fastapi-app` |
| 8000 | TCP | AMS | `fastapi-app` directly ([API](/docker/api)) |
| 1883 | TCP | AMS | MQTT: IMUs and cameras publish here |
| 9001 | TCP | AMS | MQTT over WebSocket |
| 5001 | TCP | AMS | Robot CSV stream (`tcp`) |
| 123 | UDP | AMS | NTP |
| 5050 | TCP | AMS | pgAdmin |
| 2377, 7946, 4789 | TCP/UDP | AMS ↔ Pis | Docker Swarm management, gossip and overlay traffic |
| 5433 | TCP | NAS | PostgreSQL |
| 2049 | TCP | NAS | NFS (backups, logs) |
| 44818 | TCP | PLC | EtherNet/IP, read by `fastapi-app` and the IMU Pis |

Internal-only ports that stay on the Docker network: `stack-controller` 8080, the `tcp` status server 8090.

## Names inside the AMS stack

Containers reach each other by Compose service name: `mqtt-broker`, `fastapi-app`, `tcp`, `stack-controller`, `ntp`. nginx in `web` resolves `fastapi-app` per request, so the dashboard loads even while the API is down. Edge devices aren't on the Compose network; they use the host's address (`MQTT_BROKER_IP=192.168.2.100`).
