# Bringing a node online



## IMU Node

0. The physical node device is assumed to be a Raspberry Pi device that is already connected to the SMR lab network. [Bring a device onto the network]
1. Join the Pi to the Swarm as a worker: `docker swarm join --token <worker-token> <manager-ip>:2377`.
2. From the manager, label the node so placement constraints can match it: `docker node update --label-add device_id=<pi-ip> <node-name>`.
3. On the Pi, install and start the `imu-hw` systemd service (the `imu_host` process — see [Hardware](/hardware/)) and confirm `/v1/readyz` reports healthy over the Unix socket.
4. From the manager, deploy or refresh the stack:

   ```bash
   set -a; source ./.env; set +a
   docker stack deploy --resolve-image never -c swarm.yml imu
   ```

5. Verify scheduling and health:

   ```bash
   docker service ps imu_imu_83_joint1
   docker service logs -f imu_imu_83_joint1
   ```

To tear the IMU stack down: `docker stack rm imu`.