# Feb 23 12:31
ALTER TABLE IF EXISTS public.imu_measurement
ADD COLUMN frame_id bigint;

ALTER TABLE IF EXISTS public.imu_measurement
ADD COLUMN capture_time double precision;

UPDATE public.imu_measurement
SET frame_id = 0
WHERE frame_id IS NULL;

UPDATE public.imu_measurement
SET "capture_time (device)" = 0
WHERE "capture_time (device)" IS NULL;

<!-- ALTER TABLE IF EXISTS public.imu_measurement
    ALTER COLUMN frame_id SET NOT NULL;

ALTER TABLE IF EXISTS public.imu_measurement
    ALTER COLUMN "capture_time (device)" SET NOT NULL; -->

# Sep 17 2026
-- Controlled, expandable vocabulary of session categories, enforced via FK
-- from session.session_label_id. Add new categories later with a plain
-- INSERT — no further ALTER needed.
CREATE TABLE IF NOT EXISTS public.session_label (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);

INSERT INTO public.session_label (name) VALUES
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
    ('Legacy / Unspecified')
ON CONFLICT (name) DO NOTHING;

ALTER TABLE IF EXISTS public.session
    ADD COLUMN IF NOT EXISTS session_label_id INTEGER REFERENCES public.session_label (id);

-- Backfill sessions that pre-date this migration to a catch-all category
-- before the column can be made NOT NULL.
UPDATE public.session
SET session_label_id = (SELECT id FROM public.session_label WHERE name = 'Legacy / Unspecified')
WHERE session_label_id IS NULL;

ALTER TABLE IF EXISTS public.session
    ALTER COLUMN session_label_id SET NOT NULL;
# Sep 29 2026
-- Group roles for per-person pgAdmin accounts (pgAdmin moved off the NAS into
-- the AMS stack, see pgadmin/provision-users.sh). Login roles are created by the
-- provisioning script's generated SQL with `IN ROLE lab_viewers` or
-- `IN ROLE lab_admins`.
--   lab_viewers: read-only on every table and view in public, including ones
--                created later
--   lab_admins:  full access to the lab database. Inherits DB_USER's rights
--                (read, write, DDL on everything DB_USER owns) but with
--                SET FALSE, so admins can't SET ROLE to DB_USER and become
--                superuser. Can also see and cancel any student's query.
-- Run as DB_USER, which must be a superuser (it is on the NAS) to grant
-- membership in itself. Needs Postgres 16+ for `WITH INHERIT ..., SET ...`.
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

# Sep 29 2026 (b)
-- Session-scoped indexes. Almost every student query filters on session_id,
-- but imu_measurement and image_detection only had (device_id, recorded_at)
-- indexes, so each one was a full sequential scan of the table (788 MB for
-- imu_measurement), which evicted the NAS's small cache and slowed live
-- ingestion. robot already had idx_robot_session_frame on the NAS.
-- CONCURRENTLY keeps inserts running while the index builds; it can't run
-- inside a transaction, so run each statement on its own (pgAdmin's Query Tool
-- autocommits by default).
CREATE INDEX CONCURRENTLY IF NOT EXISTS imu_measurement_session_id_device_id_recorded_at_idx
    ON public.imu_measurement (session_id, device_id, recorded_at);
CREATE INDEX CONCURRENTLY IF NOT EXISTS image_detection_session_id_frame_idx_idx
    ON public.image_detection (session_id, frame_idx);
ANALYZE public.imu_measurement;
ANALYZE public.image_detection;
