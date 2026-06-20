#!/bin/bash
set -e

PG_BIN="/usr/lib/postgresql/${PG_MAJOR:-15}/bin"

echo "Waiting for PostgreSQL to be ready..."
for i in $(seq 1 30); do
    if su -s /bin/bash postgres -c "${PG_BIN}/pg_isready -q" 2>/dev/null; then
        echo "PostgreSQL is ready!"
        break
    fi
    if [ $i -eq 30 ]; then
        echo "ERROR: PostgreSQL did not start"
        exit 1
    fi
    sleep 1
done

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

echo "=== Starting MCP server ==="
exec python3 /app/scripts/hipocampo_mcp_server.py --http 7860 --host 0.0.0.0
