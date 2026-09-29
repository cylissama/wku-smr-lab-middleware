#!/usr/bin/env bash
# Create per-person pgAdmin accounts on the AMS pgAdmin container, each with a
# pre-registered "ManufactoringDB" server that logs in as that person's own
# Postgres role. Everyone is in one of two groups:
#
#   admin   pgAdmin Administrator; Postgres role in lab_admins (full access to
#           the lab database, can see and cancel anyone's query)
#   viewer  pgAdmin "Viewer" role (Query Tool and browsing only); Postgres role
#           in lab_viewers (read-only, with per-role query limits)
#
# Usage (from the repo root, with the stack up):
#   pgadmin/provision-users.sh [users.csv] [--apply]
#
#   users.csv  defaults to pgadmin/users.csv (gitignored; copy users.example.csv)
#              columns: email,db_role,group   (group = admin|viewer, default viewer)
#   --apply    also run the generated role SQL against DB_HOST as DB_USER
#              (must be a superuser). Without it, run the SQL file yourself in
#              pgAdmin's Query Tool as DB_USER.
#
# Needs the Sep 29 2026 entry in db/migrations.md applied first (it creates the
# lab_admins/lab_viewers group roles). Users that already exist in pgAdmin are
# skipped. For each new user a random password is generated and used for BOTH
# their pgAdmin login and their Postgres role; credentials land in
# pgadmin/generated/ (gitignored, mode 600) for handing out. See
# web/docs/data/accessing-database.md.
set -euo pipefail

cd "$(dirname "$0")/.."

USERS_FILE="pgadmin/users.csv"
APPLY=0
for arg in "$@"; do
    case "$arg" in
        --apply) APPLY=1 ;;
        -h|--help) sed -n '2,26p' "$0"; exit 0 ;;
        *) USERS_FILE="$arg" ;;
    esac
done

[ -f .env ] || { echo "no .env in repo root" >&2; exit 1; }
[ -f "$USERS_FILE" ] || { echo "users file not found: $USERS_FILE (see pgadmin/users.example.csv)" >&2; exit 1; }
set -a; . ./.env; set +a

CONTAINER="${PGADMIN_CONTAINER:-AMS-pgadmin}"
PG_HOST="${DB_HOST:?DB_HOST not set in .env}"
PG_PORT="${PGPORT:-${DB_PORT:-5432}}"
PG_DB="${DB_NAME:?DB_NAME not set in .env}"
SETUP=(docker exec "$CONTAINER" /venv/bin/python3 /pgadmin4/setup.py)

docker inspect "$CONTAINER" >/dev/null 2>&1 || { echo "container $CONTAINER is not running" >&2; exit 1; }

# pgAdmin's built-in "User" role can register servers, run pg_dump/pg_restore,
# open a psql shell and so on. Viewers get their own role with just browsing,
# the Query Tool (which can still download results as CSV) and ERD. setup.py
# has no command for roles, so this uses pgAdmin's models directly; it's
# idempotent and also resets the permission list if someone edited it in the UI.
docker exec -i -w /pgadmin4 "$CONTAINER" /venv/bin/python3 - >/dev/null 2>&1 <<'PY' \
    || { echo "could not create the pgAdmin Viewer role" >&2; exit 1; }
import sys
sys.path.insert(0, '/pgadmin4')
import config
from pgadmin import create_app
from pgadmin.model import db, Role

PERMISSIONS = ['tools_query_tool', 'tools_erd_tool', 'tools_search_objects',
               'storage_add_folder', 'change_password']

app = create_app(config.APP_NAME + '-cli')
with app.test_request_context():
    role = Role.query.filter_by(name='Viewer').first()
    if role is None:
        role = Role(name='Viewer', description='Lab viewer: read-only querying')
        db.session.add(role)
    role.permissions = PERMISSIONS
    db.session.commit()
PY

umask 077
mkdir -p pgadmin/generated
stamp="$(date +%Y%m%d-%H%M%S)"
SQL_FILE="pgadmin/generated/lab-roles-$stamp.sql"
CREDS_FILE="pgadmin/generated/credentials-$stamp.csv"
echo "email,db_role,group,password" > "$CREDS_FILE"
: > "$SQL_FILE"

created=0
# Drop the (empty) output files if nothing was created, including on an error exit
trap '[ "$created" -eq 0 ] && rm -f "$SQL_FILE" "$CREDS_FILE"' EXIT

existing="$("${SETUP[@]}" get-users --json 2>/dev/null)"

while IFS=, read -r email db_role group || [ -n "$email" ]; do
    email="$(echo "$email" | tr -d '[:space:]')"
    db_role="$(echo "$db_role" | tr -d '[:space:]')"
    group="$(echo "${group:-viewer}" | tr -d '[:space:]' | tr '[:upper:]' '[:lower:]')"
    [ -z "$group" ] && group=viewer
    [ -z "$email" ] && continue
    case "$email" in \#*|email) continue ;; esac

    if ! [[ "$email" =~ ^[^@[:space:]]+@[^@[:space:]]+\.[^@[:space:]]+$ ]]; then
        echo "skip: invalid email '$email'" >&2; continue
    fi
    # Restrict role names so they can go into SQL unquoted-safe
    if ! [[ "$db_role" =~ ^[a-z_][a-z0-9_]{0,62}$ ]]; then
        echo "skip $email: db_role '$db_role' must match [a-z_][a-z0-9_]*" >&2; continue
    fi
    case "$group" in
        admin) role_flag=(--admin) ;;
        viewer) role_flag=(--role Viewer) ;;
        *) echo "skip $email: group '$group' must be admin or viewer" >&2; continue ;;
    esac
    if grep -qi "\"email\": \"$email\"" <<<"$existing"; then
        echo "skip $email: already a pgAdmin user"; continue
    fi

    password="$(openssl rand -base64 24 | tr -d '/+=' | cut -c1-16)"

    "${SETUP[@]}" add-user "${role_flag[@]}" "$email" "$password" >/dev/null 2>&1 \
        || { echo "failed to add pgAdmin user $email" >&2; continue; }
    created=$((created + 1))

    # Role-level settings are not inherited from the group role, so every
    # limit is set on the login role itself. The GRANT after the DO block
    # covers a role that already existed from an earlier run.
    cat >> "$SQL_FILE" <<SQL
DO \$\$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '$db_role') THEN
        CREATE ROLE $db_role LOGIN;
    END IF;
END
\$\$;
GRANT lab_${group}s TO $db_role;
ALTER ROLE $db_role PASSWORD '$password';
SQL
    if [ "$group" = admin ]; then
        cat >> "$SQL_FILE" <<SQL
ALTER ROLE $db_role CONNECTION LIMIT 10;
ALTER ROLE $db_role SET idle_in_transaction_session_timeout = '30min';
-- Tables an admin creates are owned by their own login role, so viewers need
-- a default grant per admin to see them
ALTER DEFAULT PRIVILEGES FOR ROLE $db_role IN SCHEMA public GRANT SELECT ON TABLES TO lab_viewers;

SQL
    else
        cat >> "$SQL_FILE" <<SQL
ALTER ROLE $db_role CONNECTION LIMIT 5;
ALTER ROLE $db_role SET default_transaction_read_only = on;
ALTER ROLE $db_role SET statement_timeout = '2min';
ALTER ROLE $db_role SET idle_in_transaction_session_timeout = '5min';
ALTER ROLE $db_role SET work_mem = '16MB';
ALTER ROLE $db_role SET temp_file_limit = '1GB';

SQL
    fi
    echo "$email,$db_role,$group,$password" >> "$CREDS_FILE"

    # Piped through `docker exec -i` rather than `docker cp` so the file is
    # owned by the container's pgadmin user, which setup.py runs as
    docker exec -i "$CONTAINER" sh -c "cat > /tmp/servers-$db_role.json" <<JSON
{
  "Servers": {
    "1": {
      "Name": "ManufactoringDB",
      "Group": "smr-db",
      "Host": "$PG_HOST",
      "Port": $PG_PORT,
      "MaintenanceDB": "$PG_DB",
      "Username": "$db_role",
      "SSLMode": "prefer"
    }
  }
}
JSON
    "${SETUP[@]}" load-servers "/tmp/servers-$db_role.json" --user "$email" >/dev/null 2>&1 \
        || echo "warning: could not register server for $email" >&2
    docker exec "$CONTAINER" rm -f "/tmp/servers-$db_role.json"

    echo "added $email ($group, db role: $db_role)"
done < "$USERS_FILE"

if [ "$created" -eq 0 ]; then
    echo "no new users"
    exit 0
fi

if [ "$APPLY" -eq 1 ]; then
    psql_bin="$(docker exec "$CONTAINER" sh -c 'ls -d /usr/local/pgsql-* | sort -V | tail -1')/psql"
    # The pgAdmin accounts already exist at this point and a re-run would skip
    # them, so on failure keep the SQL/credentials and say how to finish
    if ! docker exec -i -e PGPASSWORD="${DB_PASSWORD:?DB_PASSWORD not set in .env}" "$CONTAINER" \
        "$psql_bin" -v ON_ERROR_STOP=1 -q -h "$PG_HOST" -p "$PG_PORT" -U "${DB_USER:?}" -d "$PG_DB" \
        < "$SQL_FILE"; then
        echo "error: pgAdmin accounts were created but the Postgres roles were not." >&2
        echo "Fix the error above (is the Sep 29 2026 migration applied?), then run $SQL_FILE as $DB_USER." >&2
        echo "credentials for $created new user(s): $CREDS_FILE" >&2
        exit 1
    fi
    echo "applied $SQL_FILE"
else
    echo "run $SQL_FILE as $DB_USER (pgAdmin Query Tool) to create the Postgres roles"
fi
echo "credentials for $created new user(s): $CREDS_FILE"
