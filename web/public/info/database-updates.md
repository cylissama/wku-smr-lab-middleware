# On adding a database column, or changing edge node data order


1. add the columns into the database
    - using either pgAdmin webpage (properties -> add column)
    - using direct SQL 
        - ALTER TABLE IF EXISTS public.imu_measurement
            ADD COLUMN frame_id bigint;

            ALTER TABLE IF EXISTS public.imu_measurement
            ADD COLUMN capture_time double precision
    - make sure not to create these new columsn with NOT NULL, this will cause an error with existing data entries, you can back fill later, and then add NOT NULL if neccassary

2. modify the parsing
    - for IMU and CAM parsing is done fast_server/parsing.py
        - the data must be in the same order as received when parsed. this will also need to be same order as the database insertions later. (order of actual table elements in pgAdmin does not matter)
    - for ROBOT parsing is done in tcp_server/tcp_server.py
        - assure that parsing is aligned with order that data is received

3. modify the database insertions
    - in db/database.py modify the respetive methods
        - IMU, ROBOT, CAM all have their own insert_DEVICE_item() AND insert_DEVICE_batch()
        - although we do not often use the _item() and most often use _batch() it is best to update both
    - again, ensure that the order the data is received in the database.py file is the same as the parsing.py file or the tcp_server.py file. 
    - the items in the array must match the items in the executemany() command as shown below
    ```
            records = [
            (
                d["frame_id"], 
                d["ts_epoch"],
               
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
    ```
    - some items here are obtained from the passed parser data, some items such as ingested_at and device_id are obtained elsewhere. It depends on the need and the data type.

4. Restart and rebuild the docker compose. On the Data Broker Mini PC, run a ```docker compose down``` and then a ```docker compose up --build``` command. This will ensure that all changes are commited to the running instance of docker.
