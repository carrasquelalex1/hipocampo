#!/bin/bash
set -e

echo "=== Hipocampo Startup ==="

PG_BIN="/usr/lib/postgresql/${PG_MAJOR:-15}/bin"
PGDATA="${PGDATA:-/var/lib/postgresql/data}"

# Initialize DB if needed
if [ ! -s "$PGDATA/PG_VERSION" ]; then
    echo "Initializing PostgreSQL..."
    mkdir -p "$PGDATA"
    chown -R postgres:postgres "$PGDATA"
    gosu postgres "${PG_BIN}/initdb -D $PGDATA"
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

chown -R postgres:postgres "$PGDATA"

# Start postgres in background
echo "Starting PostgreSQL..."
gosu postgres "${PG_BIN}/pg_ctl -D $PGDATA -l ${PGDATA}/pg.log start" &

# Wait for postgres
for i in $(seq 1 30); do
    if gosu postgres "${PG_BIN}/pg_isready -q" 2>/dev/null; then
        echo "PostgreSQL is ready!"
        break
    fi
    [ $i -eq 30 ] && echo "ERROR: PG failed" && exit 1
    sleep 1
done

# Setup DB
echo "Setting up database..."
gosu postgres "${PG_BIN}/psql -c \"CREATE USER ${DB_USER} WITH PASSWORD '${DB_PASSWORD}';\"" 2>&1 || true
gosu postgres "${PG_BIN}/psql -c \"CREATE DATABASE ${DB_NAME} OWNER ${DB_USER};\"" 2>&1 || true
gosu postgres "${PG_BIN}/psql -c \"GRANT ALL PRIVILEGES ON DATABASE ${DB_NAME} TO ${DB_USER};\"" 2>&1 || true
gosu postgres "${PG_BIN}/psql -d ${DB_NAME} -c 'CREATE EXTENSION IF NOT EXISTS vector;'" 2>&1
gosu postgres "${PG_BIN}/psql -d ${DB_NAME} -c 'CREATE EXTENSION IF NOT EXISTS pg_trgm;'" 2>&1
gosu postgres "${PG_BIN}/psql -d ${DB_NAME}" < /app/esquema.sql 2>&1 || true
gosu postgres "${PG_BIN}/psql -d ${DB_NAME} -c \"GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO ${DB_USER};\"" 2>&1 || true
gosu postgres "${PG_BIN}/psql -d ${DB_NAME} -c \"GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO ${DB_USER};\"" 2>&1 || true

echo "=== Starting MCP server ==="
exec python3 /app/scripts/hipocampo_mcp_server.py --http 7860 --host 0.0.0.0
