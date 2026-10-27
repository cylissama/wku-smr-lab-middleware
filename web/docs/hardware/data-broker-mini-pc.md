# AMS host (mini PC)

The mini PC is the home of the Active Middleware Services: every container in `docker-compose.yml` runs here. It's also the Docker **Swarm manager**, so the edge stack is deployed from here (by `stack-controller`).

| | |
| --- | --- |
| Hostname | `IIoT` |
| Address | 192.168.2.100 |
| SSH | `ssh data-team@192.168.2.100` (password in the lab's password manager) |
| Repository | `/home/ubuntu/wku-smr-lab-middleware`; the running containers are built from this checkout |
| OS | Ubuntu 24.04.3 LTS (x86) |
| CPU / RAM | Intel N150, 4 cores @ 3.6 GHz / 16 GB |
| Location | Downstairs, in the server rack |

Services it publishes are listed in [Network topology](/network/topology#ports).

::: info Placeholder
TODO: power-on/boot behavior (does everything come back by itself after a power cut? `restart: unless-stopped` says the containers do), and who to contact for physical access.
:::
