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