# Updating the production database schema

There is no migration tool for this project — schema changes are hand-run SQL against the NAS-hosted Postgres instance, logged chronologically in [`db/migrations.md`](https://github.com/cylissama/wku-smr-lab-middleware/blob/main/project/db/migrations.md). `db/schema.sql` is a from-scratch equivalent of the same schema, kept in sync so a fresh local/portable stack (see [Compose](/docker/compose)) matches production without needing the NAS.

Two patterns cover almost every change made so far: adding a column to an existing table, and adding a whole new table linked to an existing one by foreign key.

## General principles

- **Back up first.** Trigger a backup from the dashboard's Backup card, or `GET /backup` on `fastapi-app`, before running any schema change against production.
- **Never add a `NOT NULL` column directly to a populated table.** Add it nullable, backfill existing rows, then `ALTER COLUMN ... SET NOT NULL` in a separate step.
- **Apply the database change before deploying app code that depends on it.** If new code expects a column or table that doesn't exist yet, every request touching it fails until the schema catches up. DB first, code second — always.
- **Log every change in `db/migrations.md`, and mirror it in `db/schema.sql`** so the two stay describing the same schema.

## Pattern 1: Adding a column

Used for things like adding a new sensor field to `imu_measurement`, `image_detection`, or `robot`.

1. **Add the column(s)** — either through pgAdmin (table properties → Add column) or direct SQL:

   ```sql
   ALTER TABLE IF EXISTS public.imu_measurement
       ADD COLUMN frame_id bigint;

   ALTER TABLE IF EXISTS public.imu_measurement
       ADD COLUMN capture_time double precision;
   ```

   Leave new columns nullable at first — adding `NOT NULL` immediately errors out against existing rows. Backfill later if needed, then tighten the constraint in a follow-up `ALTER COLUMN ... SET NOT NULL`.

2. **Update parsing** — IMU/camera parsing lives in `fast_server/parsing.py`; robot parsing lives in `tcp_server/tcp_server.py`. The parsed field order must match both the order data arrives in and the order used in the database insert.

3. **Update the database insert** — in `db/database.py`, each device type has its own `insert_<device>_item()` and `insert_<device>_batch()`. Update both, even though `_batch()` is what's used in practice. The tuple built for `executemany()` must line up positionally with the `INSERT ... VALUES ($1, $2, ...)` column list:

   ```python
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
                   frame_id, ts_epoch,
                   joint_1, joint_2, joint_3, joint_4, joint_5, joint_6,
                   x, y, z, w, p, r,
                   recorded_at, ingested_at, device_id, session_id
               )
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18)
           """, records)
   ```

   Some fields come straight from the parser's dict; others (`ingested_at`, `device_id`, `session_id`) are resolved elsewhere in `database.py`.

4. **Rebuild and restart.** On the Data Broker Mini PC:

   ```bash
   cd project
   docker compose down
   docker compose up --build -d
   ```

## Pattern 2: Adding a new linked table

Used when a change needs a controlled, expandable set of values rather than a single new column — for example, the session-label feature added Sep 17 2026: a `session_label` lookup table, foreign-keyed from `session`, so every session must pick a category from an expandable, enforced list.

This pattern needs one more step than a plain column addition: **the new table has to exist before the foreign-key column can reference it**, and any pre-existing rows in the linked table need a valid value backfilled before the column can be made `NOT NULL`.

### Example: `session_label`

```sql
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
```

Run this in pgAdmin's Query Tool (see [Accessing the database](/data/accessing-database)) against the NAS Postgres, **before** deploying the app code that requires it — `create_session()` in `db/database.py` needs both the table and the column to exist.

New categories can be added later with a plain `INSERT INTO session_label (name) VALUES (...)` — no further schema change needed. That's the "expandable but enforced" shape: expandable because adding a category is just a row insert, enforced because the `NOT NULL` foreign key means every session must reference one that already exists.

### Verifying it landed

```sql
-- Row count matches the seed list
SELECT * FROM session_label ORDER BY id;

-- Every session has a category
SELECT count(*) FROM session WHERE session_label_id IS NULL; -- expect 0

-- Spot-check recent sessions
SELECT s.id, s.label, sl.name AS session_label
FROM session s
JOIN session_label sl ON sl.id = s.session_label_id
ORDER BY s.id DESC
LIMIT 5;
```

### Rolling back

Because this pattern is additive, rolling back the **app code** is normally enough — every existing column is untouched. Dropping the new table/column is destructive to any rows created after the migration, so only do it if the data genuinely needs to go:

```sql
ALTER TABLE public.session DROP COLUMN IF EXISTS session_label_id;
DROP TABLE IF EXISTS public.session_label;
```
