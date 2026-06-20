#!/bin/bash
set -e

PG_BIN="/usr/lib/postgresql/${PG_MAJOR:-15}/bin"
PGDATA="${PGDATA:-/var/lib/postgresql/data}"

init_db() {
    if [ ! -s "$PGDATA/PG_VERSION" ]; then
        echo "Initializing PostgreSQL..."
        mkdir -p "$PGDATA"
        chown -R postgres:postgres "$PGDATA"
        su -s /bin/bash postgres -c "${PG_BIN}/initdb -D $PGDATA"

        echo "Configuring PostgreSQL..."
        cat >> "$PGDATA/postgresql.conf" <<EOF
listen_addresses = 'localhost'
port = 5432
wal_level = minimal
fsync = off
full_page_writes = off
EOF

        cat > "$PGDATA/pg_hba.conf" <<EOF
local all all trust
host all all 127.0.0.1/32 md5
host all all ::1/128 md5
EOF
    fi
}

start_db() {
    echo "Starting PostgreSQL..."
    su -s /bin/bash postgres -c "${PG_BIN}/pg_ctl -D $PGDATA -l ${PGDATA}/pg.log start"
    for i in $(seq 1 30); do
        if su -s /bin/bash postgres -c "${PG_BIN}/pg_isready -q" 2>/dev/null; then
            echo "PostgreSQL is ready"
            return 0
        fi
        sleep 1
    done
    echo "PostgreSQL failed to start"
    cat "${PGDATA}/pg.log" 2>/dev/null | tail -20 || true
    exit 1
}

create_db() {
    echo "Creating database and user..."
    su -s /bin/bash postgres -c "${PG_BIN}/psql -c \"CREATE USER ${DB_USER} WITH PASSWORD '${DB_PASSWORD}';\"" 2>&1 || true
    su -s /bin/bash postgres -c "${PG_BIN}/psql -c \"CREATE DATABASE ${DB_NAME} OWNER ${DB_USER};\"" 2>&1 || true
    su -s /bin/bash postgres -c "${PG_BIN}/psql -c \"GRANT ALL PRIVILEGES ON DATABASE ${DB_NAME} TO ${DB_USER};\"" 2>&1 || true
    echo "Installing extensions..."
    su -s /bin/bash postgres -c "${PG_BIN}/psql -d ${DB_NAME} -c 'CREATE EXTENSION IF NOT EXISTS vector;'" 2>&1
    su -s /bin/bash postgres -c "${PG_BIN}/psql -d ${DB_NAME} -c 'CREATE EXTENSION IF NOT EXISTS pg_trgm;'" 2>&1
    echo "Running schema..."
    su -s /bin/bash postgres -c "${PG_BIN}/psql -d ${DB_NAME}" < /app/esquema.sql 2>&1 || true
    echo "Granting permissions..."
    su -s /bin/bash postgres -c "${PG_BIN}/psql -d ${DB_NAME} -c \"GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO ${DB_USER};\"" 2>&1 || true
    su -s /bin/bash postgres -c "${PG_BIN}/psql -d ${DB_NAME} -c \"GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO ${DB_USER};\"" 2>&1 || true
}

init_db
start_db
create_db

echo "Starting MCP server..."
exec "$@"
