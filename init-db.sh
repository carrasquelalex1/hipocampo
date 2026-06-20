#!/bin/bash
set -e

PG_BIN="/usr/lib/postgresql/15/bin"
PGDATA="/var/lib/postgresql/data"

# Initialize DB if empty
if [ ! -s "$PGDATA/PG_VERSION" ]; then
    echo "Initializing PostgreSQL..."
    mkdir -p "$PGDATA"
    chown -R postgres:postgres "$PGDATA"
    su -s /bin/bash postgres -c "${PG_BIN}/initdb -D $PGDATA"
    
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

echo "Database initialization complete. Starting supervisord..."
exec supervisord -c /app/supervisord.conf
