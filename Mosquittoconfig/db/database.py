import asyncio, asyncpg, os, subprocess
from datetime import datetime, timezone
from pathlib import Path
from fast_server import loggers
from fast_server.connection_manager import misc_manager, broadcast_message


# Custom Errors
class SessionNotStarted(Exception):

    def __init__(self, message, data=None):
        super().__init__(message)
        self.data = data
        self.message = message

class ExistingSessionLabel(Exception):

    def __init__(self, message, data=None):
        super().__init__(message)
        self.data = data
        self.message = message

class MissingDatabaseDetails(Exception):

    def __init__(self, message, data=None):
        super().__init__(message)
        self.data = data
        self.message = message

# Singleton of Database (only 1 per container)
class DatabaseSingleton:
    _instance = None
    _lock = asyncio.Lock()

    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool
        self.devices = {}
        self.current_session_id = None
        self.history = set()
        self._last_check = 0

        self.host = os.getenv("DB_HOST")
        self.port = os.getenv("DB_PORT")
        self.name = os.getenv("DB_NAME")
        self.user = os.getenv("DB_USER")
        self.password = os.getenv("DB_PASSWORD")

    @classmethod
    async def get_instance(cls, min_size: int = 1, max_size: int = 50):

        # If there is not a current DB object, create one
        if cls._instance is None:

            async with cls._lock:

                # Only let one coroutine create a pool
                if cls._instance is None:

                    # Uses pools to only have a set number of connections that are available... Can be increase to allow more devices if needed
                    pool = await asyncpg.create_pool(
                        host=os.getenv("DB_HOST"),
                        port=int(os.getenv("DB_PORT")),
                        database=os.getenv("DB_NAME"),
                        user=os.getenv("DB_USER"),
                        password=os.getenv("DB_PASSWORD"),
                        min_size=min_size,
                        max_size=max_size,
                    )

                    cls._instance = cls(pool)
                    loggers.log_system_logger("Database pool initialized.")

        return cls._instance

    # Closes a DB pool --- Needed for recovery
    @classmethod
    async def close(cls):

        # Only close if there is an active object
        if cls._instance:

            await cls._instance.pool.close()
            cls._instance = None
            loggers.log_system_logger("Database pool closed.")

    def get_time(self):
        try:
            return datetime.now(timezone.utc).timestamp()
        except (ValueError, IOError) as e:
            loggers.log_system_logger(f"DB could not get UTC time: {e}")
            return 0

    # Gets the latest session if there is one active
    async def get_latest_session(self):

        # Checks if a session is already active in the cache
        if self.current_session_id and (datetime.now(timezone.utc).timestamp() - self._last_check < 10):
            return self.current_session_id

        # If not, queries to see if the last created session is still active
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT id, ended_at
                FROM session
                ORDER BY started_at DESC, id DESC
                LIMIT 1
            """)

        # If not, create a new session
        if row and row["ended_at"] is None:
            self.current_session_id = row["id"]
            self._last_check = datetime.now(timezone.utc).timestamp()
            return row["id"]

        # If no session, ensure removed from cache
        self.current_session_id = None
        return None

    # Restores a backup
    async def restore_backup(self, file_path: str):

        await broadcast_message(misc_manager, "Recovery Started")

        try: 

            # Kill all connections
            async with self.pool.acquire() as conn:

                await conn.execute("""
                    SELECT pg_terminate_backend(pid)
                    FROM pg_stat_activity
                    WHERE datname = $1
                    AND pid <> pg_backend_pid();
                """, self.name)


            # Close current DB connections
            await self.pool.close()

            env = {**os.environ, "PGPASSWORD": self.password}

            # Drop + recreate the database
            subprocess.run(
                ["dropdb", "-h", self.host, "-p", self.port, "-U", self.user, self.name],
                env=env, check=True
            )

            subprocess.run(
                ["createdb", "-h", self.host, "-p", self.port, "-U", self.user, self.name],
                env=env, check=True
            )

            # Restore
            subprocess.run(
                ["pg_restore", "-h", self.host, "-p", self.port, "-U", self.user, "-d", self.name, file_path],
                env=env, check=True
            )

            await broadcast_message(misc_manager, "Recovery Successful")
        
        except Exception as e:
            await broadcast_message(misc_manager, f"Recovery failed: {e}", "error")

        finally:

            await broadcast_message(misc_manager, "DB Pool Connecting...")

            # Attempts to recreate connection pools
            try:
                self.pool = await asyncpg.create_pool(
                    host=self.host,
                    port=int(self.port),
                    database=self.name,
                    user=self.user,
                    password=self.password,
                    min_size=1,
                    max_size=100,
                )

                await broadcast_message(misc_manager, "DB Pool Connected")

                # Empty caches
                self.devices.clear()
                self.history.clear()
                self.current_session_id = None

            except Exception as e:
                await broadcast_message(misc_manager, f"DB Pool connection failed: {e}", "error")

    # Creates a backup
    def create_backup(self):

        # Ensure folder is mounted to docker
        backup_dir = Path("/db_backups")
        backup_dir.mkdir(parents=True, exist_ok=True)

        ts = datetime.fromtimestamp(self.get_time(), tz=timezone.utc).strftime("%Y%m%d_%H%M%S_UTC")
        db = os.environ["PGDATABASE"]
        out = backup_dir / f"{db}_{ts}.dump"

        # Batch command to create a backup
        cmd = [
            "pg_dump",
            "-h", os.environ.get("PGHOST", "database"),
            "-p", os.environ.get("PGPORT", "5432"),
            "-U", os.environ["PGUSER"],
            "-d", db,
            "-F", "c",
            "-f", str(out),
        ]

        env = {**os.environ, "PGPASSWORD": os.environ["PGPASSWORD"]}
        subprocess.run(cmd, check=True, env=env)
        return str(out)

    # Returns all IMU data from session label
    async def retrieve_imu(self, session_label):

        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT imu.*
                FROM imu_measurement AS imu
                JOIN session AS s ON imu.session_id = s.id
                WHERE s.label = $1
            """, session_label)
        
        # Convert to json
        data = [dict(r) for r in rows]

        return data

    # Returns all CAMERA data from session label
    async def retrieve_camera(self, session_label):
        
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT img.*
                FROM image_detection AS img
                JOIN session AS s ON img.session_id = s.id
                WHERE s.label = $1
            """, session_label)
        
        # Convert to json
        data = [dict(r) for r in rows]

        return data

    # Returns all ROBOT data from session label
    async def retrieve_robot(self, session_label): 
        
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT robt.*
                FROM robot AS robt
                JOIN session AS s ON robt.session_id = s.id
                WHERE s.label = $1
                ORDER BY robt.ts_epoch
            """, session_label)
        
        # Convert to json
        data = [dict(r) for r in rows]

        ## Updated to match the requirements for the TWINS Team ##
        twins = []
        for r in rows:
            item = {
                "ts": r["ts_epoch"], 

                "joints": [
                    r["joint_1"],
                    r["joint_2"],
                    r["joint_3"],
                    r["joint_4"],
                    r["joint_5"],
                    r["joint_6"],
                ],
                "tcp": [
                    r["x"],
                    r["y"],
                    r["z"],
                ],

                "quat": [
                    r["w"],
                    r["p"],
                    r["r"],
                    1,
                ],
            }

            twins.append(item)

        return twins

    # Returns all the sessions stored in DB
    async def retrieve_sessions(self): 
        
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT id, label
                FROM session
            """)
        
        # Convert to json
        data = [dict(r) for r in rows]

        return data

    # Creates or Retrieves from cache a device id
    async def get_or_create_device_id(self, device_label, category, ip="0.0.0.0") -> int:
        
        # Check if in Cache
        if device_label in self.devices:
            await self.insert_session_device(self.devices[device_label])
            return self.devices[device_label]

        # Search DB
        device_id = await self.check_device(device_label)

        # If does not exist, create a new device
        if device_id is None:
            device_id = await self.insert_device(device_label, category, ip)

        # Cache and Return id
        self.devices[device_label] = device_id

        # Insert combo
        await self.insert_session_device(self.devices[device_label])

        return device_id

    # Insert ROBOT in batches to DB
    async def insert_robot_batch(self, batch):

        session_id = await self.get_latest_session()
        if not session_id:
            raise SessionNotStarted("No current active session. Run a GET to start a new session.")

        device_id = await self.get_or_create_device_id("main", "robot")

        # Use one ingested_at timestamp per batch flush (optional but nice)
        ingested_at = self.get_time()

        records = [
            (
                d["frame_id"],     # NEW
                d["ts_epoch"],
                # ts_string no stored
                d["joint1"], d["joint2"], d["joint3"], d["joint4"], d["joint5"], d["joint6"],
                d["x"], d["y"], d["z"], d["w"], d["p"], d["r"],
                d["recorded_at"],
                
                ingested_at,
                device_id,
                session_id
            )
            for d in batch
        ]

        async with self.pool.acquire() as conn:
            async with conn.transaction():
                await conn.executemany("""
                    INSERT INTO robot (
                        frame_id,
                        ts_epoch,
                        joint_1, joint_2, joint_3, joint_4, joint_5, joint_6,
                        x, y, z, w, p, r,
                        recorded_at,
                        ingested_at,
                        device_id,
                        session_id
                    )
                    VALUES (
                        $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18
                    )
                """, records)


    # Insertion for single item in DB
    async def insert_robot_data(self, frame_id, ts_int, j1, j2, j3, j4, j5, j6, x, y, z, w, p, r, recorded_at):

        session_id = await self.get_latest_session()
        if not session_id:
            raise SessionNotStarted("No current active session. Run a GET to start a new session.")

        device_id = await self.get_or_create_device_id("main", "robot")

        async with self.pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute("""
                    INSERT INTO robot (
                        frame_id,
                        ts_epoch,
                        joint_1, joint_2, joint_3, joint_4, joint_5, joint_6,
                        x, y, z, w, p, r,
                        recorded_at,
                        ingested_at,
                        device_id,
                        session_id
                    )
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18)
                """,
                frame_id,
                ts_int,
                j1, j2, j3, j4, j5, j6,
                x, y, z, w, p, r,
                recorded_at,
                self.get_time(),
                device_id,
                session_id
                )

    # Batched insertion for IMU
    async def insert_imu_batch(self, batch):
        session_id = await self.get_latest_session()

        if not session_id:
            raise SessionNotStarted("No current active session. Run a GET to start a new session.")

        async with self.pool.acquire() as conn:
            async with conn.transaction():
                records = []
                for d in batch:
                    device_id = await self.get_or_create_device_id(d["device_label"], "imu")

                    # revised
                    records.append((
                        d["frame_id"], 
                        d["capture_time"],
                        d["recorded_at"], 
                        self.get_time(), # <- ingested_at 
                        device_id, 
                        session_id,
                        d["accel_x"], d["accel_y"], d["accel_z"],
                        d["gyro_x"], d["gyro_y"], d["gyro_z"],
                        d["mag_x"], d["mag_y"], d["mag_z"],
                        d["yaw"], d["pitch"], d["roll"],
                    ))
                await conn.executemany("""
                    INSERT INTO imu_measurement (
                        frame_id,
                        capture_time,
                        recorded_at,
                        ingested_at,
                        device_id,
                        session_id,
                        accel_x, accel_y, accel_z,
                        gyro_x, gyro_y, gyro_z,
                        mag_x, mag_y, mag_z,
                        yaw, pitch, roll
                    )
                    VALUES (
                        $1,$2,$3,$4,$5,$6,
                        $7,$8,$9,
                        $10,$11,$12,
                        $13,$14,$15,
                        $16,$17,$18
                    )
                """, records)

    # Single Insertion for IMU
    async def insert_imu_data(self, device_label, recorded_at, accel_x, accel_y, accel_z, gryo_x, gryo_y, gryo_z, mag_x, mag_y, mag_z, yaw, pitch, roll):

        session_id = await self.get_latest_session()

        # If session doesn't exist, throw error
        if not session_id:
            raise SessionNotStarted("No current active session. Run a GET to start a new session.")

        # Get device ID & Session ID
        device_id = await self.get_or_create_device_id(device_label, "imu")

        # Insert into imu table
        async with self.pool.acquire() as conn:

            async with conn.transaction():

                await conn.execute(
                    "INSERT INTO imu_measurement (device_id, session_id, accel_x, accel_y, accel_z, gyro_x, gyro_y, gyro_z, mag_x, mag_y, mag_z, yaw, pitch, roll, recorded_at, ingested_at) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16)",
                    device_id, session_id, accel_x, accel_y, accel_z, gryo_x, gryo_y, gryo_z, mag_x, mag_y, mag_z, yaw, pitch, roll, recorded_at, self.get_time()
                )

    # # Batched insertion for CAMERA
    # async def insert_camera_batch(self, batch):

    #     session_id = await self.get_latest_session()

    #     if not session_id:
    #         raise SessionNotStarted("No current active session. Run a GET to start a new session.")

    #     async with self.pool.acquire() as conn:

    #         async with conn.transaction():

    #             await conn.executemany("""
    #                 INSERT INTO image_detection (
    #                     frame_idx, marker_idx, rvec_x, rvec_y, rvec_z,
    #                     tvec_x, tvec_y, tvec_z, image_path,
    #                     recorded_at, device_id, session_id, ingested_at
    #                 )
    #                 VALUES (
    #                     $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13
    #                 )
    #             """, [
    #                 (
    #                     d["frame_idx"], d["marker_idx"],
    #                     d["rvec_x"], d["rvec_y"], d["rvec_z"],
    #                     d["tvec_x"], d["tvec_y"], d["tvec_z"],
    #                     d["image_path"], d["recorded_at"],
    #                     await self.get_or_create_device_id(d["device_label"], "camera"),
    #                     session_id, self.get_time()
    #                 )
    #                 for d in batch
    #             ])

    # Batched insertion for CAMERA
    async def insert_camera_batch(self, batch):
        session_id = await self.get_latest_session()
        if not session_id:
            raise SessionNotStarted("No current active session. Run a GET to start a new session.")

        records = []
        for i, d in enumerate(batch):
            try:
                device_id = await self.get_or_create_device_id(d["device_label"], "camera")

                # 🔍 DEBUG: print the parsed dict
                print(f"[CAMERA DEBUG] batch_idx={i} parsed_d={d}")

                record = (
                    d["frame_idx"],
                    d["capture_time"],
                    d["recorded_at"],
                    d["marker_idx"],
                    d["rvec_x"], d["rvec_y"], d["rvec_z"],
                    d["tvec_x"], d["tvec_y"], d["tvec_z"],
                    d["image_path"],
                    device_id,
                    session_id,
                    self.get_time(),   # ingested_at
                )

                # 🔍 DEBUG: print the exact tuple being sent to Postgres
                print(f"[CAMERA DEBUG] batch_idx={i} record_tuple={record}")

                records.append(record)

            except Exception as e:
                # If something is wrong before DB insert, you’ll see it here
                print(f"[CAMERA DEBUG ERROR] batch_idx={i} error={e} d={d}")
                raise

        async with self.pool.acquire() as conn:
            async with conn.transaction():
                try:
                    await conn.executemany("""
                        INSERT INTO image_detection (
                            frame_idx,
                            capture_time,
                            recorded_at,
                            marker_idx,
                            rvec_x, rvec_y, rvec_z,
                            tvec_x, tvec_y, tvec_z,
                            image_path,
                            device_id, session_id, ingested_at
                        )
                        VALUES (
                            $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14
                        )
                    """, records)
                except Exception as e:
                    # 🔥 DB-level failure — log the *first* record for clarity
                    print(f"[CAMERA DB ERROR] error={e}")
                    if records:
                        print(f"[CAMERA DB ERROR] first_record={records[0]}")
                    raise

    # Insert into Camera Table in DB
    async def insert_camera_data(
        self,
        device_label,
        frame_idx,
        capture_time,
        recorded_at,
        marker_idx,
        rvec_x, rvec_y, rvec_z,
        tvec_x, tvec_y, tvec_z,
        image_path
    ):
        session_id = await self.get_latest_session()
        if not session_id:
            raise SessionNotStarted("No current active session. Run a GET to start a new session.")

        device_id = await self.get_or_create_device_id(device_label, "camera")

        async with self.pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute("""
                    INSERT INTO image_detection (
                        frame_idx,
                        capture_time,
                        recorded_at,
                        marker_idx,
                        rvec_x, rvec_y, rvec_z,
                        tvec_x, tvec_y, tvec_z,
                        image_path,
                        device_id, session_id, ingested_at
                    )
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)
                """,
                frame_idx,
                capture_time,
                recorded_at,
                marker_idx,
                rvec_x, rvec_y, rvec_z,
                tvec_x, tvec_y, tvec_z,
                image_path,
                device_id,
                session_id,
                self.get_time()
                )

    # Insert into session device
    async def is_in_session_device(self, device_id, session_id):

        # Check cache
        if (device_id, session_id) in self.history:
            return True

        async with self.pool.acquire() as conn:

            return await conn.fetchval(
                "SELECT 1 FROM session_device WHERE device_id=$1 AND session_id=$2",
                device_id, session_id
            ) is not None

    # Insert into session device
    async def insert_session_device(self, device_id): 

        session_id = await self.get_latest_session()

        # Check if already inserted
        if await self.is_in_session_device(device_id, session_id):
            return

        # Insert
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO session_device (device_id, session_id)
                VALUES ($1, $2)
                ON CONFLICT (device_id, session_id) DO NOTHING
                RETURNING device_id
                """,
                device_id, session_id
            )

        # Update cache
        if row is not None:
            self.history.add((device_id, session_id))
        

    # Return the device_id if found or None 
    async def check_device(self, device_label) -> int | None:

        async with self.pool.acquire() as conn:

            device_id = await conn.fetchval(
                "SELECT id FROM device WHERE label = $1",
                device_label
            )

        return device_id

    # Return True if session label already exists
    async def existing_session(self, label):

        async with self.pool.acquire() as conn:

            found = await conn.fetchval(
                "SELECT label FROM session WHERE label = $1",
                label
            )

        return found is not None

    # Call to create a new session in DB & update current session
    async def create_session(self, label, is_test_session=True):

        session_id = await self.get_latest_session()

        # Ensure the session doesn't already exist
        if await self.existing_session(label):
            raise ExistingSessionLabel(f"Session label [{label}] already exist. Please select another one.")

        async with self.pool.acquire() as conn:

            session_id = await conn.fetchval(
                """
                INSERT INTO session (label, started_at, is_test_session) VALUES ($1, $2, $3) RETURNING id
                """,
                label, self.get_time(), is_test_session
            )

        self.current_session_id = session_id

        return session_id

    # Call to end the current active session
    async def end_session(self):

        session_id = await self.get_latest_session()

        # Ensure a session is active
        if not session_id:
            raise SessionNotStarted("No active sesssions. You need to start one first.")
        
        # Update record
        async with self.pool.acquire() as conn:

            await conn.execute(
                """
                UPDATE "session"
                SET ended_at = $1
                WHERE id = $2
                """,
                self.get_time(),
                session_id
            )
        
        self.current_session_id = None

    # Inserts a new device into the DB & Return the id
    async def insert_device(self, label, category, ip_address) -> int:

        async with self.pool.acquire() as conn:

            return await conn.fetchval(
                """
                INSERT INTO device (label, category, ip_address, registered_at)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (label) DO UPDATE SET label = EXCLUDED.label
                RETURNING id
                """,
                label, category, ip_address, self.get_time()
            )
