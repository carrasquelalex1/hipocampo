#!/bin/bash
set -e

echo "=== Hipocampo Startup ==="

# Detect postgres version and binaries
PG_VERSION=$(ls /usr/lib/postgresql/ | sort -V | tail -1)
PG_BIN="/usr/lib/postgresql/${PG_VERSION}/bin"
PGDATA="/var/lib/postgresql/data"

echo "PG_VERSION=$PG_VERSION"
echo "PG_BIN=$PG_BIN"

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

# Start PostgreSQL as postgres user
echo "Starting PostgreSQL..."
su -s /bin/bash postgres -c "${PG_BIN}/pg_ctl -D $PGDATA -l ${PGDATA}/pg.log start"

echo "Waiting for PostgreSQL..."
READY=0
for i in $(seq 1 30); do
    if su -s /bin/bash postgres -c "${PG_BIN}/pg_isready -q" 2>/dev/null; then
        echo "PostgreSQL is ready!"
        READY=1
        break
    fi
    sleep 1
done

if [ $READY -eq 0 ]; then
    echo "ERROR: PostgreSQL did not start"
    cat "${PGDATA}/pg.log" 2>/dev/null | tail -20 || true
    exit 1
fi

# Create DB + user + extensions
echo "Setting up database..."
su -s /bin/bash postgres -c "${PG_BIN}/psql -c \"CREATE USER ${DB_USER} WITH PASSWORD '${DB_PASSWORD}';\"" 2>&1 || true
su -s /bin/bash postgres -c "${PG_BIN}/psql -c \"CREATE DATABASE ${DB_NAME} OWNER ${DB_USER};\"" 2>&1 || true
su -s /bin/bash postgres -c "${PG_BIN}/psql -c \"GRANT ALL PRIVILEGES ON DATABASE ${DB_NAME} TO ${DB_USER};\"" 2>&1 || true
su -s /bin/bash postgres -c "${PG_BIN}/psql -d ${DB_NAME} -c 'CREATE EXTENSION IF NOT EXISTS vector;'" 2>&1
su -s /bin/bash postgres -c "${PG_BIN}/psql -d ${DB_NAME} -c 'CREATE EXTENSION IF NOT EXISTS pg_trgm;'" 2>&1

echo "Running schema..."
su -s /bin/bash postgres -c "${PG_BIN}/psql -d ${DB_NAME}" < /app/esquema.sql 2>&1 || true

echo "Granting permissions..."
su -s /bin/bash postgres -c "${PG_BIN}/psql -d ${DB_NAME} -c \"GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO ${DB_USER};\"" 2>&1 || true
su -s /bin/bash postgres -c "${PG_BIN}/psql -d ${DB_NAME} -c \"GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO ${DB_USER};\"" 2>&1 || true
su -s /bin/bash postgres -c "${PG_BIN}/psql -d ${DB_NAME} -c \"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO ${DB_USER};\"" 2>&1 || true
su -s /bin/bash postgres -c "${PG_BIN}/psql -d ${DB_NAME} -c \"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO ${DB_USER};\"" 2>&1 || true

echo "=== Starting MCP server ==="
python3 /app/scripts/hipocampo_mcp_server.py --http 7860 --host 0.0.0.0
