import os, asyncio, time
from dotenv import load_dotenv
load_dotenv()  # reads .env in the current working directory, if present

import paho.mqtt.client as mqtt
from fast_server import loggers
from db.database import DatabaseSingleton

# Batched queue for IMU data, same pattern as robot_queue in tcp_server.py
queue_size = int(os.getenv("QUEUE_SIZE", 5000))
imu_queue = asyncio.Queue(maxsize=queue_size)

# Column order must match what imu_edge actually publishes.
# Confirm this against a live sample before trusting it in production.
IMU_FIELDS = [
    "frame_id",          # was "counter" on the wire
    "capture_time",
    "recorded_at",
    "accel_x", "accel_y", "accel_z",
    "gyro_x", "gyro_y", "gyro_z",
    "mag_x", "mag_y", "mag_z",
    "yaw", "pitch", "roll",
    "device_label",       # was "device_id" on the wire
]


def parse_imu_line(payload: str) -> dict:
    """Parses one comma-separated MQTT payload line into the dict shape
    that DatabaseSingleton.insert_imu_batch expects."""
    parts = [p.strip() for p in payload.split(",")]

    if len(parts) != len(IMU_FIELDS):
        raise ValueError(
            f"Expected {len(IMU_FIELDS)} fields, got {len(parts)}: {payload!r}"
        )

    data = {}
    for field, value in zip(IMU_FIELDS, parts):
        if field == "device_label":
            data[field] = value  # keep as string label
        elif field in ("frame_id",):
            data[field] = int(float(value))
        else:
            data[field] = float(value)

    return data


# Continuously consumes the queue and performs batched DB insertions
async def imu_worker(batch_size=50, flush_interval=2.0):
    db = await DatabaseSingleton.get_instance()
    batch = []
    last_flush = time.monotonic()

    while True:
        try:
            item = await asyncio.wait_for(imu_queue.get(), timeout=0.5)
            batch.append(item)
        except asyncio.TimeoutError:
            pass

        now = time.monotonic()
        if (len(batch) >= batch_size) or (batch and (now - last_flush) >= flush_interval):
            try:
                await db.insert_imu_batch(batch)
                loggers.log_system_logger(f"Inserted {len(batch)} imu rows.")
                batch.clear()
                last_flush = now
            except Exception as e:
                loggers.log_system_logger(f"IMU DB batch insert failed: {e}")
                await asyncio.sleep(1)

        await asyncio.sleep(0)


def make_mqtt_client(loop: asyncio.AbstractEventLoop) -> mqtt.Client:
    broker_host = os.getenv("MQTT_BROKER_IP", "127.0.0.1")
    broker_port = int(os.getenv("MQTT_BROKER_PORT", 1883))

    # Supports either MQTT_TOPICS="imu4,imu5,imu6" (preferred, multiple topics)
    # or the older single MQTT_TOPIC="imu4" (still works, kept for compatibility)
    topics_raw = os.getenv("MQTT_TOPICS") or os.getenv("MQTT_TOPIC", "imu4")
    topics = [t.strip() for t in topics_raw.split(",") if t.strip()]

    client_id = os.getenv("MQTT_CLIENT_ID", "imu-db-subscriber")
    client = mqtt.Client(client_id=client_id)

    def on_connect(client, userdata, flags, rc):
        print(f"[MQTT] Connected (rc={rc}), subscribing to {topics}")
        for t in topics:
            client.subscribe(t)

    def on_message(client, userdata, msg):
        payload = msg.payload.decode("utf-8", errors="replace").strip()
        try:
            data = parse_imu_line(payload)
        except Exception as e:
            print(f"[MQTT PARSE ERROR] {e}")
            return

        # mqtt callbacks run on paho's own thread, so hop back onto the
        # asyncio loop to put the item on the queue safely
        asyncio.run_coroutine_threadsafe(imu_queue.put(data), loop)

    client.on_connect = on_connect
    client.on_message = on_message

    client.connect(broker_host, broker_port, keepalive=60)
    return client


async def start_mqtt_server():
    batch_size = int(os.getenv("BATCHES", 50))
    batch_timeout = float(os.getenv("B_TIMEOUT", 2.0))

    loop = asyncio.get_running_loop()
    client = make_mqtt_client(loop)

    # paho's loop_start() runs its own background thread for network I/O
    client.loop_start()

    asyncio.create_task(imu_worker(batch_size=batch_size, flush_interval=batch_timeout))

    try:
        while True:
            await asyncio.sleep(3600)
    finally:
        client.loop_stop()
        client.disconnect()


def main():
    loggers.create_loggers()
    print("Starting MQTT IMU subscriber...")

    try:
        asyncio.run(start_mqtt_server())
    except KeyboardInterrupt:
        print("MQTT IMU subscriber stopped by user.")
    except Exception as e:
        print(f"MQTT IMU subscriber crashed: {e}")
    finally:
        asyncio.run(DatabaseSingleton.close())


if __name__ == "__main__":
    main()