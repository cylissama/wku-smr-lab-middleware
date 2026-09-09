-- Minimal schema inferred from database.py's queries.
-- This is a best-effort reconstruction for TESTING ONLY --
-- compare against the real schema before trusting this long-term.

CREATE TABLE session (
    id              SERIAL PRIMARY KEY,
    label           TEXT UNIQUE NOT NULL,
    started_at      DOUBLE PRECISION NOT NULL,
    ended_at        DOUBLE PRECISION,
    is_test_session BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE device (
    id              SERIAL PRIMARY KEY,
    label           TEXT UNIQUE NOT NULL,
    category        TEXT NOT NULL,
    ip_address      TEXT,
    registered_at   DOUBLE PRECISION NOT NULL
);

CREATE TABLE session_device (
    device_id       INTEGER NOT NULL REFERENCES device(id),
    session_id      INTEGER NOT NULL REFERENCES session(id),
    PRIMARY KEY (device_id, session_id)
);

CREATE TABLE imu_measurement (
    id              SERIAL PRIMARY KEY,
    frame_id        INTEGER,
    capture_time    DOUBLE PRECISION,
    recorded_at     DOUBLE PRECISION,
    ingested_at     DOUBLE PRECISION,
    device_id       INTEGER NOT NULL REFERENCES device(id),
    session_id      INTEGER NOT NULL REFERENCES session(id),
    accel_x         DOUBLE PRECISION,
    accel_y         DOUBLE PRECISION,
    accel_z         DOUBLE PRECISION,
    gyro_x          DOUBLE PRECISION,
    gyro_y          DOUBLE PRECISION,
    gyro_z          DOUBLE PRECISION,
    mag_x           DOUBLE PRECISION,
    mag_y           DOUBLE PRECISION,
    mag_z           DOUBLE PRECISION,
    yaw             DOUBLE PRECISION,
    pitch           DOUBLE PRECISION,
    roll            DOUBLE PRECISION
);
