# Network Parity Review - 2026-04-21

## Purpose

This note documents how the current `swarm.yml` networking compares to the original `docker-compose.yml` networking.

The goal is to answer a specific operational question:

Does the new Swarm stack keep the network behavior the same as the Compose deployment?

Short answer:

- Application hostname behavior is mostly preserved for the central services.
- The underlying Docker network implementation is not identical.
- A few intentional Swarm-specific changes were introduced and should be understood before deployment.

## Source Files Reviewed

- `docker-compose.yml`
- `swarm.yml`
- `web/nginx.conf`
- `.env`

## Executive Summary

The Swarm stack preserves the most important service-to-service hostnames used by the application:

- `mqtt-broker`
- `fastapi-app`
- `ntp`

This means the main internal traffic patterns still line up with the Compose deployment model.

However, the networking is not exactly the same in Docker terms:

- Compose used the default project network behavior for a local deployment.
- Swarm now uses explicit overlay networks.
- Portainer now has its own dedicated overlay network.
- The IMU services are now attached to the same overlay app network as the manager-hosted services.
- Mosquitto configuration delivery changed from a bind mount to a Swarm config object.

These changes are expected for a Swarm deployment and were introduced intentionally.

## What Stayed Compatible

### 1. Core internal service discovery names

The application still uses these internal service names:

- `mqtt-broker`
- `fastapi-app`
- `ntp`

These are the names that matter to the application code and container-to-container traffic.

Examples:

- FastAPI uses `MQTT_HOST=mqtt-broker`
- FastAPI uses `NTP_SERVER=ntp`
- Nginx in the web container proxies to `http://fastapi-app:8000/`
- TCP now uses `FASTAPI_HOST=fastapi-app`

This is the most important compatibility point, and it was preserved.

### 2. External published service ports

The same external-facing ports remain in use for the central application services:

- Web UI: host port `80`
- FastAPI: host port `8000`
- TCP service: host port `5001`
- MQTT: host port `1883`
- NTP: host port `123/udp`

This means external clients and operators should still use the same central manager node ports they were already expecting.

### 3. Shared manager-hosted application pattern

The central services in `swarm.yml` are constrained to the manager node:

- `mqtt-broker`
- `fastapi-app`
- `web`
- `tcp`
- `ntp`
- `portainer`

That preserves the current deployment shape reasonably well, because the original Compose deployment was also effectively centralized on one machine.

## What Changed

### 1. Network driver changed from local Compose networking to Swarm overlay networking

In Compose, the services ran on the Compose-created local project network.

In Swarm, the stack now defines:

- `smr_app`
- `portainer_agent`

Both are overlay networks.

This is not a bug. It is the standard Swarm networking model.

Operationally, this means the networking behavior is similar in intent, but not identical in implementation.

### 2. Portainer now has a separate network

Portainer and its agent are isolated onto:

- `portainer_agent`

This is a new network compared with the original Compose file, because Portainer was not part of that file.

This separation is intentional and appropriate.

### 3. IMU services now join the app overlay network

The IMU services in `swarm.yml` are attached to:

- `smr_app`

This is a meaningful change.

Previously, the IMU services were defined in their own Swarm file and were not part of the original local Compose app topology.

Now they can resolve and reach app-side service names across the stack, which is useful and expected for the integrated Swarm model.

### 4. Mosquitto config delivery changed

In Compose, Mosquitto used:

```yaml
volumes:
  - ./mqtt_conf:/mosquitto/config
```

In Swarm, Mosquitto now uses a Swarm config object sourced from:

- `./mqtt_conf/mosquitto.conf`

This is safer and more Swarm-appropriate than a relative bind mount in a stack file.

### 5. Port mapping for Portainer was adjusted

Portainer’s default stack typically exposes:

- `9443`
- `9000`
- `8000`

In the current integrated `swarm.yml`, only these are published:

- `9443`
- `9000`

Port `8000` was intentionally not published for Portainer because it would conflict with FastAPI on host port `8000`.

This is an intentional compatibility fix, not a regression.

## Important Behavioral Notes

### 1. TCP-to-FastAPI communication changed for the better

In the Compose file, the TCP service relied on:

- `HOST_IP=${HOST_IP}`

and the app code would fall back to `HOST_IP` when calling FastAPI.

In the Swarm file, the TCP service now explicitly uses:

- `FASTAPI_HOST=fastapi-app`

This is better for container-to-container communication inside Swarm and is the correct internal hostname model.

### 2. Browser-to-backend traffic depends on how the frontend image was built

The container networking may be correct while the browser-facing API URL is still wrong if the pushed frontend image was built with environment values that do not match the Swarm manager host.

This is separate from Docker overlay networking.

The frontend image should be verified for:

- `VITE_API_URL`
- `VITE_WS_URL`
- `VITE_PORTAINER_URL`

If those values were baked incorrectly at image build time, the browser may point to the wrong place even though service-to-service networking is correct.

### 3. Swarm service names, not container names, are what matter now

The old Compose deployment used explicit `container_name` values.

In Swarm, those do not drive networking behavior. Service DNS names do.

That means operational expectations should shift from “container names” to “service names”.

## Compatibility Assessment by Traffic Flow

### Web container -> FastAPI

Status: Preserved

Reason:

- `web/nginx.conf` still proxies to `http://fastapi-app:8000/`
- `fastapi-app` exists as a Swarm service on the shared app network

### FastAPI -> MQTT broker

Status: Preserved

Reason:

- FastAPI uses `MQTT_HOST=mqtt-broker`
- `mqtt-broker` exists on the same app network

### FastAPI -> NTP

Status: Preserved in naming intent

Reason:

- FastAPI still references `ntp`
- `ntp` exists as a service on the same app network

Note:

Whether the application actually uses that container successfully at runtime still depends on the app logic and the NTP library behavior.

### TCP -> FastAPI

Status: Improved

Reason:

- Swarm now explicitly uses `FASTAPI_HOST=fastapi-app`
- This is better than relying on the manager host IP for internal service communication

### IMU -> MQTT broker

Status: Preserved in intent, with integrated networking added

Reason:

- IMU services are now attached to `smr_app`
- they can reach the broker by service name if configured that way

Note:

Your current `.env` still uses `MQTT_BROKER_IP=192.168.1.76`, so the IMUs may still be targeting the manager IP rather than the Swarm service DNS name.

That is not necessarily wrong, but it is different from a pure service-name-based internal network model.

## Residual Risks To Test

Before treating the stack as production-ready, validate these flows after deployment:

1. Open the web UI and confirm it can load data from FastAPI.
2. Confirm the web UI websocket connections succeed.
3. Confirm FastAPI can publish and consume through Mosquitto.
4. Confirm the TCP service can reach FastAPI via `fastapi-app`.
5. Confirm Portainer is reachable at the expected URL and port.
6. Confirm IMU services can be scaled from `0` to `1` and still reach MQTT.

## Conclusion

The new Swarm stack does not keep the Docker networking “exactly the same” as the Compose deployment.

What it does preserve is the important operational behavior for the main app services:

- the same central published ports
- the same core internal service names
- the same manager-hosted central-service model

The networking differences are mostly intentional and appropriate for Swarm:

- overlay networks instead of Compose-local networking
- dedicated Portainer network
- shared app overlay for the IMU services
- Swarm config for Mosquitto

From an application-connectivity perspective, the stack is mostly aligned with the old model, but it should still be tested as a Swarm-native deployment rather than assumed to be a byte-for-byte network equivalent of Compose.
