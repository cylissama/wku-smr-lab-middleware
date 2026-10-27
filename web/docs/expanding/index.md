# Expanding the system

Where to start for each kind of addition.

| I want to add… | How | Page |
| --- | --- | --- |
| An IMU or camera Pi | Set up the Pi, join the Swarm, add a service block and its variables to `deploy/` | [Bringing a node online](/expanding/swarm-nodes) |
| A per-run setting on the dashboard | Use it in the stack file, give it a default in `deploy/.env`, allow it in `stacks.yml`, define it in `fast_server/run_params.py` | [Run parameters](/operations/run-parameters#adding-a-parameter) |
| A session type (dropdown entry) | `INSERT INTO session_label (name) VALUES (…)`, no code change | [Updating the schema](/data/schema-changes#pattern-2-adding-a-new-linked-table) |
| A column or table | Hand-run SQL logged in `db/migrations.md`, then parsing and inserts | [Updating the schema](/data/schema-changes) |
| A database user | `pgadmin/provision-users.sh` | [Accessing the database](/data/accessing-database#managing-accounts-admins) |
| A whole new Swarm stack | An entry in `stack_controller/stacks.yml` and its name in `MANAGED_STACKS` on `fastapi-app` | [Stack controller](/docker/stack-controller#adding-or-changing-a-device) |
| A container on the AMS host | A service in `docker-compose.yml` (and `docker-compose.local.yml`), with a health check and the `smr.monitor` label | below |
| A document in the dashboard's Info library | Drop the file in `web/public/info/` and rebuild `web` | [Automations](/docker/automations#dashboard-document-library-generation) |

## Adding a container to the AMS stack

Follow the pattern of the existing services in `docker-compose.yml`:

- `restart: unless-stopped`, `logging: *default-logging`, and a `healthcheck` using `<<: *healthcheck-timing`.
- Label it `smr.monitor: "true"` so it shows in Container Health and Logs. Add `smr.autoheal: "true"` if restarting it when unhealthy is safe.
- Don't use `depends_on` to wait for the database or NAS. Services should start on their own and retry ([Health & logs](/docker/health-and-logs#starting-without-dependencies)).
- Write logs to stdout as JSON records (`common/log_schema.py`) if it's Python; otherwise add a pattern to `stack_controller/log_normalize.py`.
- Add the same service to `docker-compose.local.yml`, which is kept in sync by hand.
- Document it in [Compose](/docker/compose#services).
