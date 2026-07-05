#!/bin/bash
set -e

echo "=== Hipocampo Startup ==="
echo "User: $(whoami) (UID: $(id -u))"

PG_MAJOR="${PG_MAJOR:-16}"
PG_BIN="/usr/lib/postgresql/${PG_MAJOR}/bin"
PGDATA="${PGDATA:-/var/lib/postgresql/data}"

if [ "$(id -u)" = "0" ]; then
    echo "Running as root — using postgres user for PG"
    RUN() { su - postgres -c "$*"; }
    RUN_PSQL() { su - postgres -c "${PG_BIN}/psql -d ${DB_NAME} $*"; }
    export PGUSER=postgres
else
    echo "Running as $(whoami) — using current user for PG"
    export PGUSER=$(whoami)
    export PGDATABASE="${DB_NAME}"
    export PGHOST=localhost
    RUN() { eval "$*"; }
    RUN_PSQL() { psql -d "${DB_NAME}" "$@"; }
fi

mkdir -p "$PGDATA"
[ "$(id -u)" = "0" ] && chown -R postgres:postgres "$PGDATA" || true

if [ ! -s "$PGDATA/PG_VERSION" ]; then
    echo "Initializing PostgreSQL (PG $PG_MAJOR)..."
    RUN "${PG_BIN}/initdb -D $PGDATA" 2>&1 || {
        echo "initdb failed, cleaning up and retrying..."
        rm -rf "$PGDATA"/* 2>/dev/null || true
        RUN "${PG_BIN}/initdb -D $PGDATA" 2>&1
    }

    echo "listen_addresses = 'localhost'" >> "$PGDATA/postgresql.conf"
    echo "port = 5432" >> "$PGDATA/postgresql.conf"

    echo "local all all trust" > "$PGDATA/pg_hba.conf"
    echo "host all all 127.0.0.1/32 trust" >> "$PGDATA/pg_hba.conf"
    echo "host all all ::1/128 trust" >> "$PGDATA/pg_hba.conf"
fi

echo "Starting PostgreSQL..."
RUN "${PG_BIN}/pg_ctl -D $PGDATA -l /tmp/pg.log start" 2>&1

echo "Waiting for PostgreSQL..."
for i in $(seq 1 30); do
    if RUN "${PG_BIN}/pg_isready -q" 2>/dev/null; then
        echo "PostgreSQL is ready"
        break
    fi
    if [ "$i" -eq 30 ]; then
        echo "PostgreSQL failed to start. Log:"
        cat /tmp/pg.log 2>/dev/null || true
        exit 1
    fi
    sleep 1
done

echo "Setting up database..."
if [ "$(id -u)" = "0" ]; then
    su - postgres -c "${PG_BIN}/createdb ${DB_NAME}" 2>/dev/null || true
    su - postgres -c "${PG_BIN}/createuser ${DB_USER}" 2>/dev/null || true
    su - postgres -c "${PG_BIN}/psql -c \"ALTER USER ${DB_USER} WITH PASSWORD '${DB_PASSWORD}';\"" 2>&1 || true
    su - postgres -c "${PG_BIN}/psql -c \"GRANT ${DB_USER} TO postgres;\"" 2>&1 || true
    su - postgres -c "${PG_BIN}/psql -d ${DB_NAME} -c 'CREATE EXTENSION IF NOT EXISTS vector;'" 2>&1
    su - postgres -c "${PG_BIN}/psql -d ${DB_NAME} -c 'CREATE EXTENSION IF NOT EXISTS pg_trgm;'" 2>&1
    if [ -f /app/esquema.sql ]; then
        echo "Running schema..."
        su - postgres -c "${PG_BIN}/psql -d ${DB_NAME}" < /app/esquema.sql 2>&1 || true
    fi
    su - postgres -c "${PG_BIN}/psql -d ${DB_NAME} -c 'GRANT ALL ON ALL TABLES IN SCHEMA public TO ${DB_USER};'" 2>&1
    su - postgres -c "${PG_BIN}/psql -d ${DB_NAME} -c 'GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO ${DB_USER};'" 2>&1
    su - postgres -c "${PG_BIN}/psql -d ${DB_NAME} -c 'ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO ${DB_USER};'" 2>&1
    su - postgres -c "${PG_BIN}/psql -d ${DB_NAME} -c 'GRANT CREATE ON SCHEMA public TO ${DB_USER};'" 2>&1
else
    createdb "${DB_NAME}" 2>/dev/null || true
    psql -d "${DB_NAME}" -c 'CREATE EXTENSION IF NOT EXISTS vector;' 2>&1
    psql -d "${DB_NAME}" -c 'CREATE EXTENSION IF NOT EXISTS pg_trgm;' 2>&1
    if [ -f /app/esquema.sql ]; then
        echo "Running schema..."
        psql -d "${DB_NAME}" < /app/esquema.sql 2>&1 || true
    fi
    psql -d "${DB_NAME}" -c 'GRANT CREATE ON SCHEMA public TO '"${DB_USER}"';' 2>&1 || true
fi

echo "=== Starting MCP server ==="
export UVICORN_PROXY_HEADERS=1
exec python3 /app/scripts/hipocampo_mcp_server.py --http 7860 --host 0.0.0.0
