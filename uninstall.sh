#!/usr/bin/env bash
# ==============================================================================
# Hipocampo MCP — Desinstalador limpio
#
#   bash uninstall.sh [--keep-db] [--purge-db] [-y]
#
# Por defecto (sin flags): pregunta antes de borrar la BD.
#   --keep-db   → NO toca la base de datos (solo servicios, venv, repo, configs)
#   --purge-db  → borra la BD SIN preguntar (hace dump de respaldo antes)
#   -y          → asume "sí" a todo
# ==============================================================================
set -euo pipefail

COLOR_GREEN="\033[0;32m"; COLOR_YELLOW="\033[1;33m"; COLOR_RED="\033[0;31m"; COLOR_RESET="\033[0m"
log_info()    { echo -e "[INFO] $1"; }
log_success() { echo -e "${COLOR_GREEN}[OK]${COLOR_RESET} $1"; }
log_warn()    { echo -e "${COLOR_YELLOW}[WARN]${COLOR_RESET} $1"; }
die()         { echo -e "${COLOR_RED}[ERROR]${COLOR_RESET} $1" >&2; exit 1; }

KEEP_DB=false
PURGE_DB=false
ASSUME_YES=false
for arg in "$@"; do
    case "$arg" in
        --keep-db)  KEEP_DB=true ;;
        --purge-db) PURGE_DB=true ;;
        -y)         ASSUME_YES=true ;;
        *) die "Opción desconocida: $arg (usa --keep-db, --purge-db, -y)" ;;
    esac
done

INSTALL_DIR="${1:-}"
# Detectar install dir: argumento posicional heredado o heurística
if [[ -z "$INSTALL_DIR" ]]; then
    for cand in "$HOME/.local/share/hipocampo" "$HOME/hipocampo" "$HOME/.hipocampo/repo"; do
        [[ -f "$cand/uninstall.sh" || -f "$cand/install.sh" ]] && INSTALL_DIR="$cand" && break
    done
fi
[[ -n "$INSTALL_DIR" && -d "$INSTALL_DIR" ]] || INSTALL_DIR="$HOME/.local/share/hipocampo"
[[ -d "$INSTALL_DIR" ]] || die "No se encontró instalación de Hipocampo (probé \$INSTALL_DIR, ~/.local/share/hipocampo, ~/hipocampo)"

confirm() {  # confirm <pregunta>
    $ASSUME_YES && return 0
    read -r -p "$1 [y/N]: " ans
    [[ "$ans" == "y" || "$ans" == "Y" || "$ans" == "sí" ]]
}

DB_NAME="hipocampo_db"
DB_USER="hipocampo_user"
ENV_FILE="$INSTALL_DIR/.env"
if [[ -f "$ENV_FILE" ]]; then
    grep -q "^DB_NAME="   "$ENV_FILE" && DB_NAME="$(grep '^DB_NAME='   "$ENV_FILE" | cut -d= -f2-)"
    grep -q "^DB_USER="   "$ENV_FILE" && DB_USER="$(grep '^DB_USER='   "$ENV_FILE" | cut -d= -f2-)"
    DB_PASSWORD="$(grep '^DB_PASSWORD=' "$ENV_FILE" | cut -d= -f2- || true)"
fi

echo "🧠 Desinstalando Hipocampo ($INSTALL_DIR)"

# ─── 1. Servicios systemd ─────────────────────────────────────────────────────
for unit in hipocampo-mcp.service hipocampo-maintenance.timer hipocampo-maintenance.service; do
    if systemctl --user list-unit-files "$unit" &>/dev/null && systemctl --user is-enabled "$unit" &>/dev/null; then
        systemctl --user disable --now "$unit" 2>/dev/null || true
        log_success "Servicio $unit detenido y deshabilitado"
    fi
    rm -f "$HOME/.config/systemd/user/$unit"
done
systemctl --user daemon-reload 2>/dev/null || true

# ─── 2. Clientes MCP: quitar entrada "hipocampo" ──────────────────────────────
remove_from_json() {  # remove_from_json <archivo>
    local f="$1"
    [[ -f "$f" ]] || return 0
    python3 - "$f" <<PY
import json, sys, shutil
p = sys.argv[1]
try:
    d = json.load(open(p))
except Exception:
    sys.exit(0)
changed = False
for key in ("mcp", "mcpServers", "servers"):
    if isinstance(d.get(key), dict) and "hipocampo" in d[key]:
        del d[key]["hipocampo"]
        changed = True
if changed:
    shutil.copy2(p, p + ".bak_hipocampo_uninstall")
    open(p, "w").write(json.dumps(d, indent=2, ensure_ascii=False) + "\n")
    print(f"[OK] entrada 'hipocampo' eliminada de {p}")
PY
}
remove_from_json "$HOME/.config/opencode/opencode.json"
remove_from_json "$HOME/.config/opencode/opencode.jsonc"
remove_from_json "$HOME/.config/Claude/claude_desktop_config.json"
remove_from_json "$HOME/.gemini/settings.json"
remove_from_json "$HOME/.cursor/mcp.json"
remove_from_json "$HOME/.vscode/mcp.json"
remove_from_json "$HOME/.codeium/windsurf/mcp_config.json"

# ─── 3. Base de datos ─────────────────────────────────────────────────────────
run_psql_as_admin() {
    if [[ "$(uname -s)" == "Darwin" ]]; then psql -U "$(whoami)" "$@"; else sudo -u postgres psql "$@"; fi
}

if $PURGE_DB || ! $KEEP_DB; then
    if $PURGE_DB || confirm "¿Borrar la base de datos '$DB_NAME' y el rol '$DB_USER'? (se hará un dump de respaldo antes)"; then
        # Dump de respaldo ANTES de borrar (si la BD existe)
        if run_psql_as_admin -tAc "SELECT 1 FROM pg_database WHERE datname='$DB_NAME'" 2>/dev/null | grep -q 1; then
            DUMP_FILE="$HOME/hipocampo_backup_$(date +%Y%m%d_%H%M%S).dump"
            if run_psql_as_admin -c "ALTER DATABASE $DB_NAME OWNER TO postgres" >/dev/null 2>&1; then :; fi
            if pg_dump -Fc -h localhost -U postgres "$DB_NAME" > "$DUMP_FILE" 2>/dev/null \
               || sudo -u postgres pg_dump -Fc "$DB_NAME" > "$DUMP_FILE" 2>/dev/null; then
                log_success "Respaldo de la BD en $DUMP_FILE"
            else
                log_warn "pg_dump falló — intento con credenciales del .env"
                PGPASSWORD="$DB_PASSWORD" pg_dump -Fc -h localhost -U "$DB_USER" "$DB_NAME" > "$DUMP_FILE" 2>/dev/null \
                    && log_success "Respaldo en $DUMP_FILE" \
                    || { log_warn "No se pudo respaldar — NO se borrará la BD"; DUMP_FAILED=true; }
            fi
            if [[ "${DUMP_FAILED:-}" != "true" ]]; then
                run_psql_as_admin -c "DROP DATABASE IF EXISTS $DB_NAME" >/dev/null 2>&1 && log_success "BD $DB_NAME eliminada"
                run_psql_as_admin -c "DROP ROLE IF EXISTS $DB_USER"    >/dev/null 2>&1 && log_success "Rol $DB_USER eliminado"
            fi
        else
            log_info "La BD $DB_NAME no existe (nada que borrar)"
        fi
    else
        log_info "BD conservada (--keep-db implícito por respuesta)"
    fi
fi

# ─── 4. Archivos del proyecto ─────────────────────────────────────────────────
if confirm "¿Borrar $INSTALL_DIR (repo + venv + .env)?"; then
    rm -rf "$INSTALL_DIR"
    log_success "Directorio de instalación eliminado"
else
    log_info "Directorio conservado"
fi

log_success "Desinstalación completa."
echo "Nota: Ollama y PostgreSQL quedan intactos (podrían usarse para otros proyectos)."
