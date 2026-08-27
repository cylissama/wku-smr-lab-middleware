Apr 21

# IMU On-Demand Deployment in Docker Swarm

## Purpose

The IMU services in `swarm.yml` are configured to stay dormant by default.

This prevents IMU nodes from starting to stream data as soon as the Swarm stack is deployed.

The new default behavior is:

- `deploy.replicas: 0` for each IMU service
- `IMU_AUTO_START_SESSION=false` in `.env`

This gives us two layers of protection:

1. The IMU containers do not run until an operator explicitly scales them up.
2. When an IMU container starts, it does not automatically begin a session unless the application is told to do so.

## Why We Changed This

Previously, the IMU services were deployed with one running replica and were configured to auto-start sessions. That caused data streaming to begin immediately after stack deployment.

For Swarm and Portainer operations, we want the IMU nodes to be available for controlled activation only when a user starts them from an operator workflow or a future dashboard button.

## Files Changed

- `swarm.yml`
- `.env`

## New Default Behavior

After running:

```bash
docker stack deploy -c swarm.yml smr --with-registry-auth
```

the following IMU services will exist in the Swarm stack but will have zero running tasks:

- `smr_imu_83_joint1`
- `smr_imu_84_joint2`
- `smr_imu_85_joint3`

## How To Start IMU Services

Run these commands from the Swarm manager node:

```bash
docker service scale smr_imu_83_joint1=1
docker service scale smr_imu_84_joint2=1
docker service scale smr_imu_85_joint3=1
```

To start only one IMU node, scale only that specific service:

```bash
docker service scale smr_imu_83_joint1=1
```

## How To Stop IMU Services

To stop the IMU services again, scale them back to zero:

```bash
docker service scale smr_imu_83_joint1=0
docker service scale smr_imu_84_joint2=0
docker service scale smr_imu_85_joint3=0
```

## How To Check Status

List services in the stack:

```bash
docker stack services smr
```

Inspect task state for a specific IMU service:

```bash
docker service ps smr_imu_83_joint1
```

## Portainer Usage

This same behavior can be controlled from Portainer:

1. Open the Swarm environment.
2. Go to `Services`.
3. Locate the IMU service.
4. Use the scale control to change replicas from `0` to `1` when you want it active.
5. Scale back to `0` when you want it stopped.

## Future Dashboard Integration

The intended long-term flow is:

1. User presses a dashboard button.
2. The backend or an automation layer calls Docker Swarm or Portainer.
3. The selected IMU service is scaled from `0` to `1`.
4. A session or stream start action is triggered explicitly.

This keeps deployment control separate from data collection control and avoids accidental streaming after stack deployment.
