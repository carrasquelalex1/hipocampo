#!/bin/bash
set -e

echo "=== Hipocampo Startup ==="

export PGDATA="${PGDATA:-/var/lib/postgresql/data}"
export PG_MAJOR="${PG_MAJOR:-15}"
PG_BIN="/usr/lib/postgresql/${PG_MAJOR}/bin"

# Start postgres directly (not via entrypoint)
su - postgres -c "${PG_BIN}/pg_ctl -D $PGDATA -l ${PGDATA}/pg.log start"

echo "Waiting for PostgreSQL..."
for i in $(seq 1 20); do
    if su - postgres -c "${PG_BIN}/pg_isready -q" 2>/dev/null; then
        echo "PostgreSQL is ready"
        break
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
