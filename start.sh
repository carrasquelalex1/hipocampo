#!/bin/bash
set -e

echo "=== Hipocampo Startup ==="

PG_MAJOR="${PG_MAJOR:-16}"
PG_BIN="/usr/lib/postgresql/${PG_MAJOR}/bin"
PGDATA="${PGDATA:-/var/lib/postgresql/data}"

if [ ! -s "$PGDATA/PG_VERSION" ]; then
    echo "Initializing PostgreSQL..."
    mkdir -p "$PGDATA"
    chown -R postgres:postgres "$PGDATA"
    su - postgres -c "${PG_BIN}/initdb -D $PGDATA"

    echo "listen_addresses = 'localhost'" >> "$PGDATA/postgresql.conf"
    echo "port = 5432" >> "$PGDATA/postgresql.conf"

    echo "local all all trust" > "$PGDATA/pg_hba.conf"
    echo "host all all 127.0.0.1/32 trust" >> "$PGDATA/pg_hba.conf"
    echo "host all all ::1/128 trust" >> "$PGDATA/pg_hba.conf"
fi

echo "Starting PostgreSQL..."
su - postgres -c "${PG_BIN}/pg_ctl -D $PGDATA -l /tmp/pg.log start"

echo "Waiting for PostgreSQL..."
for i in $(seq 1 30); do
    if su - postgres -c "${PG_BIN}/pg_isready -q" 2>/dev/null; then
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
su - postgres -c "${PG_BIN}/psql -c \"CREATE USER ${DB_USER} WITH PASSWORD '${DB_PASSWORD}';\"" 2>&1 || true
su - postgres -c "${PG_BIN}/psql -c \"CREATE DATABASE ${DB_NAME} OWNER ${DB_USER};\"" 2>&1 || true
su - postgres -c "${PG_BIN}/psql -d ${DB_NAME} -c 'CREATE EXTENSION IF NOT EXISTS vector;'" 2>&1
su - postgres -c "${PG_BIN}/psql -d ${DB_NAME} -c 'CREATE EXTENSION IF NOT EXISTS pg_trgm;'" 2>&1

if [ -f /app/esquema.sql ]; then
    echo "Running schema..."
    su - postgres -c "${PG_BIN}/psql -d ${DB_NAME}" < /app/esquema.sql 2>&1 || true
fi

echo "=== Starting MCP server ==="
exec python3 /app/scripts/hipocampo_mcp_server.py --http 7860 --host 0.0.0.0
