#!/bin/bash
set -e

echo "=== Hipocampo Startup ==="

# Find postgres binaries
PG_BIN=$(dirname $(find /usr/lib/postgresql -name "pg_ctl" 2>/dev/null | head -1))
PGDATA="${PGDATA:-/var/lib/postgresql/data}"

echo "PG_BIN=$PG_BIN"
echo "PGDATA=$PGDATA"

# Initialize DB if empty
if [ ! -s "$PGDATA/PG_VERSION" ]; then
    echo "Initializing PostgreSQL..."
    mkdir -p "$PGDATA"
    chown -R postgres:postgres "$PGDATA"
    su - postgres -c "${PG_BIN}/initdb -D $PGDATA"
    
    cat >> "$PGDATA/postgresql.conf" <<EOF
listen_addresses = 'localhost'
port = 5432
EOF
    
    cat > "$PGDATA/pg_hba.conf" <<EOF
local all all trust
host all all 127.0.0.1/32 md5
host all all ::1/128 md5
EOF
fi

# Start PostgreSQL
echo "Starting PostgreSQL..."
su - postgres -c "${PG_BIN}/pg_ctl -D $PGDATA -l ${PGDATA}/pg.log start" || {
    echo "ERROR: Failed to start PostgreSQL"
    cat "${PGDATA}/pg.log" 2>/dev/null || true
    exit 1
}

echo "Waiting for PostgreSQL..."
for i in $(seq 1 20); do
    if su - postgres -c "${PG_BIN}/pg_isready -q" 2>/dev/null; then
        echo "PostgreSQL is ready"
        break
    fi
    if [ $i -eq 20 ]; then
        echo "ERROR: PostgreSQL did not start in time"
        cat "${PGDATA}/pg.log" 2>/dev/null || true
        exit 1
    fi
    sleep 1
done

# Create DB + user + extensions
echo "Setting up database..."
su - postgres -c "${PG_BIN}/psql -c \"CREATE USER ${DB_USER} WITH PASSWORD '${DB_PASSWORD}';\"" 2>&1 || true
su - postgres -c "${PG_BIN}/psql -c \"CREATE DATABASE ${DB_NAME} OWNER ${DB_USER};\"" 2>&1 || true
su - postgres -c "${PG_BIN}/psql -c \"GRANT ALL PRIVILEGES ON DATABASE ${DB_NAME} TO ${DB_USER};\"" 2>&1 || true
su - postgres -c "${PG_BIN}/psql -d ${DB_NAME} -c 'CREATE EXTENSION IF NOT EXISTS vector;'" 2>&1
su - postgres -c "${PG_BIN}/psql -d ${DB_NAME} -c 'CREATE EXTENSION IF NOT EXISTS pg_trgm;'" 2>&1

echo "Running schema..."
su - postgres -c "${PG_BIN}/psql -d ${DB_NAME}" < /app/esquema.sql 2>&1 || true

echo "=== Starting MCP server ==="
python3 /app/scripts/hipocampo_mcp_server.py --http 7860 --host 0.0.0.0
