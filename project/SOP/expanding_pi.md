# IMU Node Setup — Local Raspberry Pi Guide

This guide covers setting up `imu_node_smr` on a joint Raspberry Pi from scratch,
testing it end-to-end against a laptop-hosted MQTT broker and database, and then
rolling it into a Docker Swarm deployment across multiple joint Pis.

---

## Architecture Overview

Each joint Pi runs two components together:

- **`imu_host`** — bare metal / systemd only, never containerized. Owns the
  physical I2C connection to the BNO08X sensor and exposes readings over a
  local Unix socket (`/run/imu-hw/imu.sock`).
- **`imu_edge`** — containerized. Reads from `imu_host`'s socket and forwards
  data out over MQTT to a broker.

Data flow: `sensor → imu_host (socket) → imu_edge (MQTT) → broker → subscriber
(mqtt_server.py) → Postgres`.

---

## Part 1 — Prerequisites on a Fresh Pi

```bash
sudo apt update
sudo apt install -y git python3 python3-venv python3-pip i2c-tools swig \
    python3-dev build-essential liblgpio-dev
```

## Part 2 — Clone and Install

```bash
git clone https://github.com/cylissama/imu_node_smr.git
cd imu_node_smr
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-host.txt
pip install -r requirements-edge.txt
```


## Part 3 — Enable and Verify I2C

```bash
sudo raspi-config    # Interface Options → I2C → Enable → reboot if prompted
i2cdetect -y 1
```

You should see an address appear in the grid (BNO08X is typically `0x4A` or
`0x4B`). **An empty grid means a hardware problem, not software** — check:
- SDA/SCL not swapped
- VCC on 3.3V (not 5V)
- GND connected
- All jumper wires firmly seated
- Board's protocol-select pin/jumper is set to I2C (not SPI/UART)



---

## Part 4 — Run and Test `imu_host`

```bash
sudo mkdir -p /run/imu-hw
sudo chown $USER:$USER /run/imu-hw
IMU_SERVICE_BACKEND=real python -m imu_host
```

`"IMU connection successfully initialized"` with no further output is
**correct** — `imu_host` is a server and just waits idle for requests.



## Part 5 — Set Up a Local Test Broker (Laptop)

On your laptop (not the Pi), install Mosquitto and create a minimal config:

```
listener 1883 0.0.0.0
allow_anonymous true
```


Start it:
```
mosquitto -c mosquitto.conf -v
```

> **Windows gotcha:** the Mosquitto installer often registers itself as an
> auto-starting Windows service using its own default config, which will
> silently fight your manual instance for port 1883 and cause
> `"not authorised"` errors. Check with `sc query mosquitto`; if `RUNNING`,
> either `net stop mosquitto` before testing, or disable it permanently:
> ```
> sc config mosquitto start=disabled
> ```
> Also check for orphaned duplicate processes: `tasklist | findstr mosquitto`.

Find your laptop's LAN IP (`ipconfig` / `ifconfig`) and ensure your firewall
allows inbound connections on port 1883.

---

## Part 6 — Run and Test `imu_edge`

On the Pi, in a **new terminal** (with `imu_host` still running elsewhere),
set all variables and run in the **same** terminal session — env vars set in
one terminal do not carry to another:

```bash
export MQTT_BROKER_IP=<laptop's LAN IP>
export MQTT_BROKER_PORT=1883
export MQTT_TOPIC=<unique topic per Pi, e.g. imu4>
export DEVICE_ID=<unique id per Pi, e.g. 201>
export IMU_SOCKET_PATH=/run/imu-hw/imu.sock
export IMU_AUTO_START_SESSION=true
export IMU_SAMPLE_HZ=65
python -m imu_edge
```

On the laptop, in a **new terminal**, subscribe and watch for live data:
```
mosquitto_sub -h 127.0.0.1 -t <same topic> -v
```

> **Keep every terminal open and untouched** once running — `imu_host`,
> `imu_edge`, the broker, and the subscriber all need to run simultaneously.
> Pressing Ctrl+C on any one of them breaks the chain.

Give each additional joint Pi its **own unique `MQTT_TOPIC` and `DEVICE_ID`**
so multiple Pis' data doesn't collide on the same topic.

---

## Part 7 — Test Database Ingestion (`mqtt_server.py`)

`mqtt_server.py` subscribes to the MQTT topic, parses each line, and batch
inserts into Postgres via `db/database.py`'s `insert_imu_batch`.

**Dependencies (run where `mqtt_server.py` lives, not on the Pi):**
```
pip install paho-mqtt asyncpg
```

**Never point this at a production database while testing.** Spin up a
disposable local Postgres in Docker instead:
```
docker run --name imu-test-db -e POSTGRES_PASSWORD=testpass \
  -e POSTGRES_DB=imu_test -p 5433:5432 -d postgres:16
```
*(remapped to host port `5433` to avoid clashing with any pre-existing local
Postgres install — check `docker ps` / `netstat -ano | findstr :5432` if you
hit password/connection errors that suggest a port conflict)*

Load the schema (see `test_schema.sql`) and create a test session row:
```
docker exec -i imu-test-db psql -U postgres -d imu_test < test_schema.sql
docker exec -it imu-test-db psql -U postgres -d imu_test -c \
  "INSERT INTO session (label, started_at, is_test_session) VALUES ('test1', extract(epoch from now()), true);"
```

Set env vars and run:
```
set DB_HOST=localhost
set DB_PORT=5433
set DB_NAME=imu_test
set DB_USER=postgres
set DB_PASSWORD=testpass
set MQTT_BROKER_IP=127.0.0.1
set MQTT_BROKER_PORT=1883
set MQTT_TOPIC=<matching topic>
python mqtt_server.py
```
*(PowerShell: use `$env:VAR="value"` instead of `set VAR=value`)*

Watch for `Inserted N imu rows.` Verify with Adminer (`docker run --name
imu-adminer -p 8080:8080 -d adminer`, connect at `http://localhost:8080` with
System = **PostgreSQL**, Server = `host.docker.internal:5433`) or via `psql`
directly.

> `mqtt_server.py` imports from an internal `fast_server` package. If you
> don't have access to that repo, use minimal stub modules (empty loggers /
> connection_manager) so it can run standalone for testing.

> If running multiple `mqtt_server.py` instances at once (one per topic), give
> each a unique MQTT client ID — a shared hardcoded client ID causes the
> broker to repeatedly disconnect/reconnect both instances in a loop.

---

## Common Pitfalls Checklist

- [ ] Env vars set with `export`/`set` only apply to that exact terminal —
      always set vars and run the command in the same window
- [ ] `pip install -r file.txt` needs the `-r` flag, or pip tries to install a
      package literally named `file.txt`
- [ ] PowerShell needs `& "path with spaces\program.exe" args`, not a bare
      quoted path
- [ ] Windows Mosquitto/Postgres services can silently conflict with manually
      run instances on the same port — check `sc query <name>` and
      `tasklist | findstr <name>`
- [ ] A running server (`imu_host`, broker, `mqtt_server.py`) sitting idle
      with no output is normal — it's waiting, not stuck
- [ ] Don't Ctrl+C any terminal in the chain while testing end-to-end
- [ ] QoS 0 MQTT messages are not retained — if you subscribe *after* a burst
      of messages already published, they're gone

---

## Part 8 — Docker Swarm Rollout (Multiple Pis)

Once `imu_host` + `imu_edge` are individually verified working on every Pi,
roll them into a swarm so one command deploys `imu_edge` to all joints.

### 8.1 Initialize the swarm (on the laptop, as manager)
```
docker swarm init --advertise-addr <laptop's LAN IP>
```
Save the `docker swarm join --token ...` command it prints.

### 8.2 Join each Pi as a worker
```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER   # log out and back in after
sudo docker swarm join --token SWMTKN-... <laptop-ip>:2377
```
Confirm from the laptop: `docker node ls` should list the laptop plus every
Pi, all `Ready`.

### 8.3 Build the image on each Pi
```bash
cd ~/imu_node_smr
docker build -t imu-edge:local .
```
Must be done on **each Pi individually** — Pis are ARM64, a laptop build
(x86/AMD64) won't run on them.

### 8.4 Set per-Pi identity
On each Pi, create `/etc/imu/device.env` with that Pi's own values:
```bash
sudo mkdir -p /etc/imu
printf "DEVICE_ID=201\nMQTT_TOPIC=imu4\n" | sudo tee /etc/imu/device.env
```
Same file path on every Pi, different content — this is what lets one
`swarm.yml` correctly serve every joint.

### 8.5 Confirm `swarm.yml`
Key settings:
```yaml
deploy:
  mode: global                 # one task per node automatically
  placement:
    constraints:
      - node.role == worker    # keep it off the manager (laptop)
environment:
  MQTT_BROKER_IP: "<laptop LAN IP>"
env_file:
  - /etc/imu/device.env
volumes:
  - /run/imu-hw:/run/imu-hw    # bind mount to reach imu_host's socket
```

### 8.6 Deploy
Make sure `imu_host` is already running (bare metal) on every Pi first —
Swarm only manages the containerized `imu_edge`, not `imu_host`. Then, from
the laptop:
```
docker stack deploy -c swarm.yml imu
docker service ls
docker service ps imu_imu-edge
```
You should see one running task per Pi.

---

## Part 9 — After the Swarm Is Running

*(fill in / expand this section once the swarm deployment is live and
verified — placeholders below based on the plan so far)*

- **Verify data from every Pi is reaching the broker and database**, not just
  one — check `mosquitto_sub` on a wildcard/each topic, and query Postgres
  grouped by device label:
  ```sql
  SELECT d.label, count(*)
  FROM imu_measurement m
  JOIN device d ON m.device_id = d.id
  GROUP BY d.label;
  ```
- **Check logs per node**, not just the aggregate service log:
  ```
  docker service logs imu_imu-edge
  # or, on a specific Pi:
  docker ps
  docker logs <container-id>
  ```
- **Adding a new joint Pi later**: join it to the swarm (8.2), build the image
  on it (8.3), create its own `/etc/imu/device.env` (8.4) — no redeploy
  needed, `global` mode picks it up automatically.
- **Updating the image after a code change**: rebuild on every Pi, then
  `docker service update --force imu_imu-edge` to roll the new image out.
- **Restarting after a Pi reboot**: confirm `imu_host` restarts (ideally via
  systemd so this is automatic) — Swarm will restart the `imu_edge` container
  on its own, but it depends on `imu_host`'s socket being available again.
- **Moving off the laptop-hosted broker/DB to the real production
  broker/database**: update `MQTT_BROKER_IP` in `swarm.yml` and redeploy the
  stack; no changes needed on the Pi side beyond that.