-- Canonical schema for the AMS database.
--
-- There is no migration tool for this project (see db/migrations.md) — the
-- real lab database on the NAS was built up by hand over time. This file is
-- the from-scratch equivalent, kept in sync with the live schema as
-- documented in web/docs/data/database-structure.md, so that a bundled/local
-- Postgres (docker-compose.local.yml, or docker-compose.yml's `local-db`
-- profile) can be initialized with a matching schema instead of starting
-- empty.
--
-- Postgres only runs files under /docker-entrypoint-initdb.d on a *first*
-- container start against an empty data volume. If you change table shape,
-- add the change to db/migrations.md (as usual) AND update this file so a
-- fresh local stack still matches production.

CREATE TABLE device (
    id SERIAL PRIMARY KEY,
    label TEXT NOT NULL UNIQUE,
    category TEXT NOT NULL,
    ip_address TEXT NOT NULL,
    registered_at DOUBLE PRECISION NOT NULL
);

-- Controlled, expandable vocabulary of session categories. New categories are
-- added by inserting a row here — no schema change required — while the FK
-- from `session` below enforces that every session picks a registered one.
CREATE TABLE session_label (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);

INSERT INTO session_label (name) VALUES
    ('Full System'),
    ('Robot and IMU'),
    ('Single-Joint'),
    ('Two-Joint'),
    ('Three-Joint'),
    ('Four-Joint'),
    ('Five-Joint'),
    ('Six-Joint'),
    ('Single Component Test'),
    ('Camera Only'),
    ('IMU Only'),
    ('Robot Only'),
    ('Production Run'),
    ('Custom Joint Combination'),
    ('Legacy / Unspecified');

CREATE TABLE session (
    id BIGSERIAL PRIMARY KEY,
    label TEXT NOT NULL UNIQUE,
    started_at DOUBLE PRECISION NOT NULL,
    ended_at DOUBLE PRECISION,
    is_test_session BOOLEAN NOT NULL DEFAULT TRUE,
    session_label_id INTEGER NOT NULL REFERENCES session_label (id)
);

CREATE TABLE session_device (
    device_id INTEGER NOT NULL REFERENCES device (id),
    session_id BIGINT NOT NULL REFERENCES session (id),
    PRIMARY KEY (device_id, session_id)
);

CREATE INDEX session_device_device_id_idx ON session_device (device_id);
CREATE INDEX session_device_session_id_idx ON session_device (session_id);

CREATE TABLE image_detection (
    id BIGSERIAL PRIMARY KEY,
    frame_idx BIGINT NOT NULL,
    marker_idx INTEGER NOT NULL,
    rvec_x DOUBLE PRECISION NOT NULL,
    rvec_y DOUBLE PRECISION NOT NULL,
    rvec_z DOUBLE PRECISION NOT NULL,
    tvec_x DOUBLE PRECISION NOT NULL,
    tvec_y DOUBLE PRECISION NOT NULL,
    tvec_z DOUBLE PRECISION NOT NULL,
    image_path TEXT NOT NULL,
    recorded_at DOUBLE PRECISION NOT NULL,
    ingested_at DOUBLE PRECISION NOT NULL,
    device_id INTEGER NOT NULL REFERENCES device (id),
    session_id BIGINT NOT NULL REFERENCES session (id),
    capture_time DOUBLE PRECISION
);

CREATE INDEX image_detection_device_id_recorded_at_idx
    ON image_detection (device_id, recorded_at DESC);

CREATE TABLE imu_measurement (
    id BIGSERIAL PRIMARY KEY,
    device_id INTEGER NOT NULL REFERENCES device (id),
    session_id BIGINT NOT NULL REFERENCES session (id),
    accel_x DOUBLE PRECISION NOT NULL,
    accel_y DOUBLE PRECISION NOT NULL,
    accel_z DOUBLE PRECISION NOT NULL,
    gyro_x DOUBLE PRECISION NOT NULL,
    gyro_y DOUBLE PRECISION NOT NULL,
    gyro_z DOUBLE PRECISION NOT NULL,
    mag_x DOUBLE PRECISION NOT NULL,
    mag_y DOUBLE PRECISION NOT NULL,
    mag_z DOUBLE PRECISION NOT NULL,
    yaw DOUBLE PRECISION NOT NULL,
    pitch DOUBLE PRECISION NOT NULL,
    roll DOUBLE PRECISION NOT NULL,
    recorded_at DOUBLE PRECISION NOT NULL,
    ingested_at DOUBLE PRECISION NOT NULL,
    frame_id BIGINT,
    capture_time DOUBLE PRECISION
);

CREATE INDEX imu_measurement_device_id_recorded_at_idx
    ON imu_measurement (device_id, recorded_at DESC);

CREATE TABLE robot (
    id BIGSERIAL PRIMARY KEY,
    ts_epoch DOUBLE PRECISION NOT NULL,
    joint_1 DOUBLE PRECISION NOT NULL,
    joint_2 DOUBLE PRECISION NOT NULL,
    joint_3 DOUBLE PRECISION NOT NULL,
    joint_4 DOUBLE PRECISION NOT NULL,
    joint_5 DOUBLE PRECISION NOT NULL,
    joint_6 DOUBLE PRECISION NOT NULL,
    x DOUBLE PRECISION NOT NULL,
    y DOUBLE PRECISION NOT NULL,
    z DOUBLE PRECISION NOT NULL,
    w DOUBLE PRECISION NOT NULL,
    p DOUBLE PRECISION NOT NULL,
    r DOUBLE PRECISION NOT NULL,
    recorded_at DOUBLE PRECISION NOT NULL,
    ingested_at DOUBLE PRECISION NOT NULL,
    device_id INTEGER NOT NULL REFERENCES device (id),
    session_id BIGINT NOT NULL REFERENCES session (id),
    frame_id BIGINT
);

CREATE INDEX robot_device_id_recorded_at_idx ON robot (device_id, recorded_at DESC);

-- Session-scoped indexes for student queries; see the Sep 29 2026 (b) entry in
-- db/migrations.md. idx_robot_session_frame pre-dates that entry on the NAS.
CREATE INDEX imu_measurement_session_id_device_id_recorded_at_idx
    ON imu_measurement (session_id, device_id, recorded_at);
CREATE INDEX image_detection_session_id_frame_idx_idx
    ON image_detection (session_id, frame_idx);
CREATE INDEX idx_robot_session_frame ON robot (session_id, frame_id);

-- Group roles for per-person pgAdmin accounts (lab_viewers: read-only,
-- lab_admins: full access without superuser); see the Sep 29 2026 entry in
-- db/migrations.md and pgadmin/provision-users.sh. Roles are cluster-wide, so
-- this block is written to be safe against a server that already has them.
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'lab_viewers') THEN
        CREATE ROLE lab_viewers NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'lab_admins') THEN
        CREATE ROLE lab_admins NOLOGIN;
    END IF;
    EXECUTE format('GRANT CONNECT ON DATABASE %I TO lab_viewers', current_database());
    EXECUTE format('GRANT ALL ON DATABASE %I TO lab_admins', current_database());
    EXECUTE format('GRANT %I TO lab_admins WITH INHERIT TRUE, SET FALSE', current_user);
END
$$;
GRANT USAGE ON SCHEMA public TO lab_viewers;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO lab_viewers;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO lab_viewers;
GRANT USAGE, CREATE ON SCHEMA public TO lab_admins;
GRANT pg_monitor, pg_signal_backend TO lab_admins;
