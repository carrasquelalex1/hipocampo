#!/bin/bash
set -e

PG_BIN="/usr/lib/postgresql/${PG_MAJOR:-15}/bin"
PGDATA="${PGDATA:-/var/lib/postgresql/data}"

# Initialize if needed
if [ ! -s "$PGDATA/PG_VERSION" ]; then
    echo "Init PG..."
    mkdir -p "$PGDATA"
    chown -R postgres:postgres "$PGDATA"
    gosu postgres "${PG_BIN}/initdb -D $PGDATA"
    echo "listen_addresses='localhost'" >> "$PGDATA/postgresql.conf"
    echo "port=5432" >> "$PGDATA/postgresql.conf"
    echo "local all all trust" > "$PGDATA/pg_hba.conf"
    echo "host all all 127.0.0.1/32 md5" >> "$PGDATA/pg_hba.conf"
    echo "host all all ::1/128 md5" >> "$PGDATA/pg_hba.conf"
fi

chown -R postgres:postgres "$PGDATA"

# Start PG
gosu postgres "${PG_BIN}/pg_ctl -D $PGDATA -l /tmp/pg.log start"

for i in $(seq 1 30); do
    gosu postgres "${PG_BIN}/pg_isready -q" 2>/dev/null && break
    [ $i -eq 30 ] && exit 1
    sleep 1
done

echo "PG ready"

# Setup
gosu postgres "${PG_BIN}/psql -tc \"SELECT 1 FROM pg_roles WHERE rolname='${DB_USER}'\" | grep -q 1" || \
    gosu postgres "${PG_BIN}/psql -c \"CREATE USER ${DB_USER} WITH PASSWORD '${DB_PASSWORD}';\""
gosu postgres "${PG_BIN}/psql -tc \"SELECT 1 FROM pg_database WHERE datname='${DB_NAME}'\" | grep -q 1" || \
    gosu postgres "${PG_BIN}/psql -c \"CREATE DATABASE ${DB_NAME} OWNER ${DB_USER};\""
gosu postgres "${PG_BIN}/psql -c \"GRANT ALL PRIVILEGES ON DATABASE ${DB_NAME} TO ${DB_USER};\""
gosu postgres "${PG_BIN}/psql -d ${DB_NAME} -c 'CREATE EXTENSION IF NOT EXISTS vector;'"
gosu postgres "${PG_BIN}/psql -d ${DB_NAME} -c 'CREATE EXTENSION IF NOT EXISTS pg_trgm;'"
gosu postgres "${PG_BIN}/psql -d ${DB_NAME}" < /app/esquema.sql 2>/dev/null || true
gosu postgres "${PG_BIN}/psql -d ${DB_NAME} -c \"GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO ${DB_USER};\""
gosu postgres "${PG_BIN}/psql -d ${DB_NAME} -c \"GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO ${DB_USER};\""

echo "DB ready"
exec python3 /app/scripts/hipocampo_mcp_server.py --http 7860 --host 0.0.0.0
