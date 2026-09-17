# Compose vs. Swarm network parity

A point-in-time review (Apr 21, 2026) comparing `swarm.yml` networking against the original [`docker-compose.yml`](/docker/compose) networking, to answer one operational question: does the [Swarm](/docker/swarm) stack keep the same network behavior as the Compose deployment?

Short answer: application hostname behavior is mostly preserved for the central services, the underlying Docker network implementation is not identical, and a few intentional Swarm-specific changes were introduced that are worth understanding before deployment.

Source files reviewed: `docker-compose.yml`, `swarm.yml`, `web/nginx.conf`, `.env`.

## What stayed compatible

### Core internal service discovery names

The application still uses the same internal service names for container-to-container traffic: `mqtt-broker`, `fastapi-app`, `ntp`. For example, FastAPI uses `MQTT_HOST=mqtt-broker` and `NTP_SERVER=ntp`, nginx in the web container proxies to `http://fastapi-app:8000/`, and the TCP service uses `FASTAPI_HOST=fastapi-app`. This is the most important compatibility point, and it held.

### External published ports

The same external-facing ports remain in use: Web UI `80`, FastAPI `8000`, TCP `5001`, MQTT `1883`, NTP `123/udp`. External clients and operators can keep using the same manager-node ports they already expect.

### Shared manager-hosted application pattern

The central services (`mqtt-broker`, `fastapi-app`, `web`, `tcp`, `ntp`, `portainer`) are all still constrained to the manager node, matching the original Compose deployment's effectively single-host shape.

## What changed

- **Network driver**: Compose used the default local project network; Swarm now defines two overlay networks, `smr_app` and `portainer_agent`. This is the standard Swarm networking model, not a bug — the behavior is similar in intent but not identical in implementation.
- **Portainer has its own network** (`portainer_agent`) — new relative to Compose, since Portainer wasn't part of that file. Intentional and appropriate.
- **IMU services now join the app overlay network** (`smr_app`) — previously they lived in their own Swarm file, separate from the local Compose app topology. Now they can resolve and reach app-side service names across the stack.
- **Mosquitto config delivery** changed from a bind mount (`./mqtt_conf:/mosquitto/config`) to a Swarm config object sourced from `./mqtt_conf/mosquitto.conf` — safer and more Swarm-appropriate than a relative bind mount in a stack file.
- **Portainer's published ports** are `9443` and `9000` only — `8000` was intentionally left unpublished to avoid conflicting with FastAPI's host port `8000`.

## Important behavioral notes

1. **TCP-to-FastAPI communication improved.** Compose relied on `HOST_IP` with an app-level fallback; Swarm explicitly uses `FASTAPI_HOST=fastapi-app`, which is the correct internal hostname model for container-to-container communication.
2. **Browser-to-backend traffic depends on how the frontend image was built.** Container networking can be entirely correct while the browser-facing API URL is still wrong, if the deployed frontend image was built with `VITE_API_URL` / `VITE_WS_URL` / `VITE_PORTAINER_URL` values that don't match the Swarm manager host. This is separate from Docker overlay networking — verify the frontend build args whenever this looks broken.
3. **Swarm service names, not `container_name`, drive DNS now.** The old Compose deployment set explicit `container_name` values, but those don't affect networking in Swarm — service DNS names do. Operational expectations should shift from "container names" to "service names."

## Compatibility by traffic flow

| Flow | Status | Notes |
| --- | --- | --- |
| Web → FastAPI | Preserved | `nginx.conf` still proxies to `http://fastapi-app:8000/`; `fastapi-app` is on the shared app network. |
| FastAPI → MQTT broker | Preserved | `MQTT_HOST=mqtt-broker`, same app network. |
| FastAPI → NTP | Preserved in naming intent | `ntp` exists on the same app network; whether the app actually uses it successfully at runtime still depends on app/NTP library behavior. |
| TCP → FastAPI | Improved | Explicit `FASTAPI_HOST=fastapi-app` beats relying on the manager host IP. |
| IMU → MQTT broker | Preserved in intent, integrated networking added | IMU services are now on `smr_app` and can reach the broker by service name — but `.env` may still point `MQTT_BROKER_IP` at the manager IP rather than the service DNS name, which isn't wrong, just a different model than pure service-name resolution. |

## Residual risks to test after deployment

1. Web UI loads data from FastAPI.
2. Web UI websocket connections succeed.
3. FastAPI can publish and consume through Mosquitto.
4. TCP service can reach FastAPI via `fastapi-app`.
5. Portainer is reachable at the expected URL and port.
6. IMU services can be scaled from `0` to `1` (see [On-demand IMU activation](/docker/swarm#on-demand-imu-activation)) and still reach MQTT.

## Conclusion

The Swarm stack doesn't keep Docker networking byte-for-byte identical to Compose, but it does preserve what matters operationally: the same central published ports, the same core internal service names, and the same manager-hosted central-service model. The differences — overlay networks, a dedicated Portainer network, shared app overlay for IMU services, Swarm config for Mosquitto — are intentional and appropriate for Swarm. Treat it as a Swarm-native deployment to be tested on its own terms, not assumed to be a network-equivalent clone of Compose.
