#!/bin/sh
# Lanzador del ciclo glinfático: elige un intérprete que tenga dotenv + psycopg2.
# Orden: venv propio de Hipocampo → venv del MCP → python del sistema.
# Necesario porque el python del sistema no siempre trae las dependencias
# (el venv es un symlink a /usr/bin/python3 pero aporta su site-packages).
set -eu

# Config canónica: ~/.hipocampo/.env (credenciales correctas por máquina).
# Sin esto, un script lanzado desde repo/ cargaría repo/.env (p. ej. DB_USER=alex
# en producción, sin permiso sobre memory_access).
: "${ENV_PATH:=$HOME/.hipocampo/.env}"
export ENV_PATH

for PY in "$HOME/.hipocampo/venv/bin/python3" "$HOME/.gemini/mcp_venv/bin/python3" /usr/bin/python3; do
    if [ -x "$PY" ] && "$PY" -c "import dotenv, psycopg2" >/dev/null 2>&1; then
        exec "$PY" "$HOME/.hipocampo/scripts/hipocampo_glymphatic.py" "$@"
    fi
done

echo "❌ Ciclo glinfático: ningún intérprete tiene dotenv + psycopg2" >&2
exit 1
