#!/bin/sh
# Lanzador del ciclo glinfático: elige un intérprete que tenga dotenv + psycopg2.
# Orden: venv propio de Hipocampo → venv del MCP → python del sistema.
# Necesario porque el python del sistema no siempre trae las dependencias
# (el venv es un symlink a /usr/bin/python3 pero aporta su site-packages).
set -eu

for PY in "$HOME/.hipocampo/venv/bin/python3" "$HOME/.gemini/mcp_venv/bin/python3" /usr/bin/python3; do
    if [ -x "$PY" ] && "$PY" -c "import dotenv, psycopg2" >/dev/null 2>&1; then
        exec "$PY" "$HOME/.hipocampo/scripts/hipocampo_glymphatic.py" "$@"
    fi
done

echo "❌ Ciclo glinfático: ningún intérprete tiene dotenv + psycopg2" >&2
exit 1
