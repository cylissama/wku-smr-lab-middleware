# On accessing the database

As stated the [PostgresSQL](https://www.postgresql.org) database is located on the Synology NAS. [pgAdmin](https://www.pgadmin.org) no longer runs on the NAS: it now runs as the `pgadmin` container in the AMS stack on the Data Broker Mini PC, at `http://192.168.2.100:5050`.

pgAdmin is used to view the database and make queries on the data. You can also download data from the database using pgAdmin.

There is link to the pgAdmin server on the Data Dashboard. You can also find the exact location of the pgAdmin server on the [ip-addresses](/network/ip-addresses.md) table located on the shared onedrive or on the documentation page here.

## Your account

Everyone has their own pgAdmin account. Ask a lab admin for one; there are no shared logins. [New student access](/data/new-student-access.md) walks through getting one. Every account is in one of two groups:

| Group | In pgAdmin | In the database |
| --- | --- | --- |
| **Viewer** (students) | Browse objects, Query Tool, ERD, search. No backup/restore, psql shell or registering servers. | Read-only (`lab_viewers`), with the limits below |
| **Admin** | pgAdmin administrator (manages users) | Full access to the lab database (`lab_admins`): read, write, change tables, see and cancel anyone's query. Not superuser. |

You get:

- **A pgAdmin login** (your email plus a generated password). Your saved servers, query history and open connections are private to you.
- **Your own Postgres role**, already set up as the `ManufactoringDB` server under the `smr-db` group. The first time you connect, it asks for the database password. This is the same generated password you were given. pgAdmin asks you to set a master password if you choose to save it. Changing your pgAdmin password does not change your database password.

Viewer roles have these limits:

| Limit | Value | Why |
| --- | --- | --- |
| `statement_timeout` | 2 min | A runaway query is cancelled instead of loading the NAS while a test is recording |
| `idle_in_transaction_session_timeout` | 5 min | An abandoned Query Tool tab can't hold locks indefinitely |
| `CONNECTION LIMIT` | 5 | One person can't use up the server's connections. Each open Query Tool tab uses one, so close tabs you're done with. |
| `work_mem` | 16 MB | Large sorts spill to disk instead of using up the NAS's memory |
| `temp_file_limit` | 1 GB | A query can't fill the NAS disk with temporary files |

The timeout and `work_mem` are defaults, so you could `SET` them higher yourself. Please don't. Admins can see every running query and will cancel ones that slow down a recording.

### Writing queries that don't slow down the lab

The IMU and camera tables hold millions of rows. They are indexed by session, so **always filter on `session_id`**:

- `imu_measurement`: filter on `session_id`, optionally `device_id`, then `recorded_at`
- `image_detection`: filter on `session_id`, optionally `frame_idx`
- `robot`: filter on `session_id`, optionally `frame_id`

Look up the session id first (`SELECT id, label, started_at FROM session ORDER BY id DESC LIMIT 20;`). Use `LIMIT` while you work out a query, and only drop it for the final export. To save results, run the query and use the Query Tool's download-as-CSV button.

# Once logged into pgAdmin

Initially when you land on the pgAdmin webpage, you might only see the "Servers(1)" listing on the left hand navigation panel.

To view the schema drill down into:

Servers -> ManufactoringDB -> Databases -> manufacturing_db -> Schemas -> public -> Tables

This will diplay what tables are present and once drilled into, what attributes the tables have

For example the device table has columns of 
- id, label, category, ip_address, registered

This database uses typical SQL, so any SQL query can run here. Some usefull examples are:

To grab some camera edge node data based on session
```
SELECT *
FROM image_detection
WHERE session_id = <xxx>
```

To grab some imu edge node data based on session
```
SELECT *
FROM imu_measurement
WHERE session_id = <xxx>
```

## Managing accounts (admins)

Accounts are created with `pgadmin/provision-users.sh` from the repo root on the Data Broker Mini PC, with the stack running.

**One-time setup.** Run the two Sep 29 2026 entries in `db/migrations.md` as `DB_USER`:

- the first creates the `lab_viewers` and `lab_admins` group roles
- the second (b) adds the `session_id` indexes the query tips above rely on

**Adding people:**

1. Copy `pgadmin/users.example.csv` to `pgadmin/users.csv` (gitignored) and list one person per line: `email,db_role,group`. `db_role` is their Postgres username and must be lowercase letters, digits and underscores. `group` is `admin` or `viewer` (blank means viewer).
2. Run `pgadmin/provision-users.sh --apply`. For each new email it:
   - creates the pgAdmin account with a random password, as an Administrator (admins) or with the restricted `Viewer` pgAdmin role (viewers). The script creates the `Viewer` role if it's missing.
   - registers the `ManufactoringDB` server for that account under their own role
   - creates the Postgres role in `lab_admins` or `lab_viewers` with that group's limits. `--apply` runs the SQL as `DB_USER`, which must be a superuser. Without `--apply`, run the generated `pgadmin/generated/lab-roles-*.sql` yourself in the Query Tool.
3. Give each person their line from `pgadmin/generated/credentials-*.csv`, then delete the file.

People who already have a pgAdmin account are skipped, so you can re-run the script after adding new rows. To reset a password, use pgAdmin's **User Management** screen for the pgAdmin login and run `ALTER ROLE <db_role> PASSWORD '...'` for the database role. To remove someone, delete them in User Management and run `DROP OWNED BY <db_role>; DROP ROLE <db_role>;`. To move someone between groups, change their role in User Management and run `REVOKE lab_viewers FROM <db_role>; GRANT lab_admins TO <db_role>;` (or the reverse), plus the matching limits from the script.

The bootstrap account from `PGADMIN_EMAIL`/`PGADMIN_PASSWORD` in `.env` has no database role of its own. Keep it as a break-glass login with a strong password, and use your own provisioned admin account day to day.

### Watching and cancelling queries

Admins can see everyone's activity. To find slow queries:

```sql
SELECT pid, usename, state, now() - query_start AS running_for, left(query, 80) AS query
FROM pg_stat_activity
WHERE backend_type = 'client backend' AND state <> 'idle'
ORDER BY running_for DESC;
```

To stop one, run `SELECT pg_cancel_backend(<pid>);`, or `pg_terminate_backend(<pid>)` to drop the connection. Admins can't cancel `DB_USER`'s own backends (FastAPI/TCP ingestion); only a superuser can.
