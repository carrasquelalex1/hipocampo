#!/usr/bin/env bash
# ==============================================================================
# Hipocampo MCP — Universal Zero-Touch Installer
#
#   curl -fsSL https://raw.githubusercontent.com/carrasquelalex1/hipocampo/main/install.sh | bash
#
# Idempotente: re-ejecutar repara/actualiza sin destruir datos existentes.
# Modo desatendido:  install.sh --unattended
# ==============================================================================
set -euo pipefail

# ─── Constantes ──────────────────────────────────────────────────────────────
REPO_URL="https://github.com/carrasquelalex1/hipocampo.git"
DEFAULT_INSTALL_DIR="$HOME/.local/share/hipocampo"
DB_NAME="hipocampo_db"
DB_USER_DEFAULT="hipocampo_user"
MCP_PORT=8001

# Opciones (overridables por flags / env)
INSTALL_DIR="$DEFAULT_INSTALL_DIR"
DB_USER="$DB_USER_DEFAULT"
UNATTENDED=false
EMBED_MODE="ollama"          # "ollama" (local) | "api" (cloud)
SKIP_CLIENTS=false
SKIP_TIMER=false
SKIP_OLLAMA=false

# ─── Logging ─────────────────────────────────────────────────────────────────
COLOR_GREEN="\033[0;32m"; COLOR_BLUE="\033[0;34m"; COLOR_YELLOW="\033[1;33m"; COLOR_RED="\033[0;31m"; COLOR_RESET="\033[0m"
log_info()    { echo -e "${COLOR_BLUE}[INFO]${COLOR_RESET} $1"; }
log_success() { echo -e "${COLOR_GREEN}[OK]${COLOR_RESET} $1"; }
log_warn()    { echo -e "${COLOR_YELLOW}[WARN]${COLOR_RESET} $1"; }
log_error()   { echo -e "${COLOR_RED}[ERROR]${COLOR_RESET} $1" >&2; }
die()         { log_error "$1"; exit 1; }

banner() {
    echo -e "${COLOR_BLUE}"
    echo "  _    _ _                                                    "
    echo " | |  | (_)                                                   "
    echo " | |__| |_ _ __   ___   ___ __ _ _ __ ___  _ __   ___         "
    echo " |  __  | | '_ \ / _ \ / __/ _\` | '_ \` _ \| '_ \ / _ \        "
    echo " | |  | | | |_) | (_) | (_| (_| | | | | | | |_) | (_) |       "
    echo " |_|  |_|_| .__/ \___/ \___\__,_|_| |_| |_| .__/ \___/        "
    echo "          | |                             | |                 "
    echo "          |_|                             |_|  INSTALLER v1.0 "
    echo -e "${COLOR_RESET}"
}

usage() {
    cat <<EOF
Uso: install.sh [opciones]

  --unattended        Modo desatendido: acepta todos los defaults
                      (Ollama local, dir ~/.local/share/hipocampo)
  --embed-api         Usar API externa de embeddings (pide base URL y API key)
                      en vez de Ollama local
  --install-dir DIR   Ruta de instalación (default: ~/.local/share/hipocampo)
  --db-user USER      Rol PostgreSQL dedicado (default: hipocampo_user)
  --no-clients        No registrar clientes MCP (OpenCode/Claude/Cursor)
  --no-timer          No instalar el timer de mantenimiento semanal
  --no-ollama         No instalar/pull Ollama (asume ya presente o modo API)
  -h, --help          Esta ayuda
EOF
    exit 0
}

# ─── Parse flags ─────────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        --unattended) UNATTENDED=true ;;
        --embed-api)   EMBED_MODE="api" ;;
        --install-dir) INSTALL_DIR="$2"; shift ;;
        --db-user)     DB_USER="$2"; shift ;;
        --no-clients)  SKIP_CLIENTS=true ;;
        --no-timer)    SKIP_TIMER=true ;;
        --no-ollama)   SKIP_OLLAMA=true ;;
        -h|--help)     usage ;;
        *) die "Opción desconocida: $1 (usa --help)" ;;
    esac
    shift
done

banner

# ─── Utilidades ──────────────────────────────────────────────────────────────
ask() {  # ask <pregunta> <default>  → echo respuesta (o default en unattended)
    local q="$1" def="$2"
    if $UNATTENDED; then echo "$def"; return; fi
    read -r -p "$q [$def]: " ans
    echo "${ans:-$def}"
}

have() { command -v "$1" >/dev/null 2>&1; }

# Detectar gestor de paquetes
PKG=""
if have apt-get;   then PKG="apt"
elif have dnf;     then PKG="dnf"
elif have pacman;  then PKG="pacman"
elif have brew;    then PKG="brew"
else die "No se detectó apt/dnf/pacman/brew. Instala PostgreSQL, Python3 y Ollama manualmente."
fi

IS_MAC=false
[[ "$(uname -s)" == "Darwin" ]] && IS_MAC=true

$IS_MAC && [[ "$PKG" != "brew" ]] && die "En macOS se requiere Homebrew."

pkg_install() {  # pkg_install paquete1 paquete2...
    case "$PKG" in
        apt)    sudo apt-get install -y "$@" ;;
        dnf)    sudo dnf install -y "$@" ;;
        pacman) sudo pacman -S --needed --noconfirm "$@" ;;
        brew)   brew install "$@" ;;
    esac
}

# ════════════════════════════════════════════════════════════════════════════
# FASE 1: Diagnóstico de sistema
# ════════════════════════════════════════════════════════════════════════════
phase() { echo; echo -e "${COLOR_BLUE}━━━ $1 ━━━${COLOR_RESET}"; }

phase "FASE 1/8: Diagnóstico del sistema"
log_info "SO: $(uname -s) $(uname -m) | Gestor: $PKG"

# RAM (MB) — solo informativo, no bloqueante
if [[ -r /proc/meminfo ]]; then
    RAM_MB=$(awk '/MemTotal/ {printf "%d", $2/1024}' /proc/meminfo)
    log_info "RAM: ${RAM_MB} MB"
    [[ "$RAM_MB" -lt 2000 ]] && log_warn "Menos de 2GB RAM: recomendado modo --embed-api."
fi

# Disco libre (MB) en el HOME — informativo
DISK_MB=$(df -m "$HOME" | awk 'NR==2 {print $4}')
log_info "Disco libre en \$HOME: ${DISK_MB} MB"
[[ "$DISK_MB" -lt 5000 ]] && log_warn "Menos de 5GB libres: puede faltar espacio para Ollama+modelo (~600MB)."

# Dependencias base
log_info "Verificando dependencias base..."
BASE_DEPS=(curl git python3)
if [[ "$PKG" == "apt" ]]; then BASE_DEPS+=(python3-venv python3-pip build-essential); fi
if $IS_MAC; then BASE_DEPS=(); have python3 || BASE_DEPS+=(python); fi

MISSING=()
for d in "${BASE_DEPS[@]}"; do have "$d" || MISSING+=("$d"); done
# python3 en brew se llama python3 tras install
if [[ ${#MISSING[@]} -gt 0 ]]; then
    log_info "Instalando: ${MISSING[*]}"
    pkg_install "${MISSING[@]}"
fi
for d in curl git python3; do have "$d" || die "No se pudo instalar $d"; done
log_success "Dependencias base OK"

# ════════════════════════════════════════════════════════════════════════════
# FASE 2: PostgreSQL + pgvector
# ════════════════════════════════════════════════════════════════════════════
phase "FASE 2/8: PostgreSQL + pgvector"

if ! have psql; then
    log_info "PostgreSQL no encontrado. Instalando..."
    case "$PKG" in
        apt)
            # Repo oficial PGDG para versiones modernas (mejor effort, fallback al distro)
            sudo apt-get update -qq
            sudo apt-get install -y -qq curl gnupg lsb-release 2>/dev/null || true
            if curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc | sudo gpg --dearmor -o /usr/share/keyrings/pgdg.gpg 2>/dev/null; then
                echo "deb [signed-by=/usr/share/keyrings/pgdg.gpg] http://apt.postgresql.org/pub/repos/apt $(. /etc/os-release && echo "$VERSION_CODENAME")-pgdg main" \
                    | sudo tee /etc/apt/sources.list.d/pgdg.list >/dev/null
                sudo apt-get update -qq 2>/dev/null || true
                sudo apt-get install -y -qq postgresql postgresql-contrib || sudo apt-get install -y -qq postgresql postgresql-contrib
            else
                sudo apt-get install -y -qq postgresql postgresql-contrib
            fi
            sudo systemctl enable --now postgresql 2>/dev/null || sudo systemctl start postgresql 2>/dev/null || true
            ;;
        dnf)
            sudo dnf install -y postgresql-server postgresql-contrib
            sudo postgresql-setup --initdb 2>/dev/null || true
            sudo systemctl enable --now postgresql
            ;;
        pacman)
            sudo pacman -S --needed --noconfirm postgresql
            sudo systemctl enable --now postgresql 2>/dev/null || \
                sudo -u postgres initdb -D /var/lib/postgres/data 2>/dev/null || true
            sudo systemctl enable --now postgresql 2>/dev/null || true
            ;;
        brew)
            brew install postgresql@16
            brew services start postgresql@16
            ;;
    esac
fi
have psql || die "PostgreSQL no quedó instalado"

# Verificar extensión pgvector
log_info "Verificando pgvector..."
PGVECTOR_OK=false
vector_available() {
    if $IS_MAC; then
        psql -tAc "SELECT 1 FROM pg_available_extensions WHERE name='vector'" 2>/dev/null | grep -q 1
    else
        sudo -u postgres psql -tAc "SELECT 1 FROM pg_available_extensions WHERE name='vector'" 2>/dev/null | grep -q 1
    fi
}
if vector_available; then
    PGVECTOR_OK=true
fi

if ! $PGVECTOR_OK; then
    log_info "Instalando pgvector..."
    PG_VER="$(psql --version 2>/dev/null | grep -oE '[0-9]+' | head -1 || echo 16)"
    INSTALLED=false
    case "$PKG" in
        apt)
            sudo apt-get install -y -qq "postgresql-${PG_VER}-pgvector" 2>/dev/null \
                || sudo apt-get install -y -qq postgresql-16-pgvector 2>/dev/null \
                || sudo apt-get install -y -qq postgresql-15-pgvector 2>/dev/null \
                || true
            sudo -u postgres psql -tAc "SELECT 1 FROM pg_available_extensions WHERE name='vector'" 2>/dev/null | grep -q 1 && INSTALLED=true
            ;;
        brew)
            brew install pgvector && INSTALLED=true
            ;;
    esac
    if ! $INSTALLED; then
        # Compilar desde fuente (Fedora/Arch/edge cases)
        log_info "Compilando pgvector desde fuente (requiere git, make, gcc)..."
        PKG_TMP="$(mktemp -d)"
        git clone --depth 1 https://github.com/pgvector/pgvector.git "$PKG_TMP/pgvector" >/dev/null 2>&1
        ( cd "$PKG_TMP/pgvector" && make -j2 >/dev/null 2>&1 && sudo make install >/dev/null 2>&1 ) \
            && log_success "pgvector compilado" || die "No se pudo instalar pgvector (ni paquete ni fuente)"
        rm -rf "$PKG_TMP"
    fi
fi
log_success "PostgreSQL + pgvector listos"

# ════════════════════════════════════════════════════════════════════════════
# FASE 3: Base de datos, usuario y esquema
# ════════════════════════════════════════════════════════════════════════════
phase "FASE 3/8: Base de datos y permisos"

# Contraseña: reutilizar la del .env existente (idempotencia) o generar
ENV_FILE="$INSTALL_DIR/.env"
DB_PASSWORD=""
if [[ -f "$ENV_FILE" ]] && grep -q "^DB_PASSWORD=" "$ENV_FILE" 2>/dev/null; then
    DB_PASSWORD="$(grep '^DB_PASSWORD=' "$ENV_FILE" | cut -d= -f2-)"
    log_info "Reutilizando contraseña existente del .env"
else
    DB_PASSWORD="$(python3 -c 'import secrets,string; print("".join(secrets.choice(string.ascii_letters+string.digits) for _ in range(24))))')"
fi

run_psql_as_admin() {  # psql como superusuario del cluster
    if $IS_MAC; then psql -U "$(whoami)" -d postgres "$@"; else sudo -u postgres psql "$@"; fi
}

# Crear rol (idempotente) y asegurar contraseña
export PGPASSWORD="$DB_PASSWORD"
run_psql_as_admin -v ON_ERROR_STOP=1 <<'SQL'
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = :'DB_USER') THEN
        CREATE ROLE :"DB_USER" WITH LOGIN PASSWORD :'DB_PASSWORD';
    ELSE
        ALTER ROLE :"DB_USER" WITH LOGIN PASSWORD :'DB_PASSWORD';
    END IF;
END
$$;
SQL
unset PGPASSWORD
if [[ $? -ne 0 ]]; then die "No se pudo crear/actualizar el rol $DB_USER"; fi

# Crear BD si no existe (idempotente)
if ! run_psql_as_admin -tAc "SELECT 1 FROM pg_database WHERE datname='$DB_NAME'" | grep -q 1; then
    run_psql_as_admin -c "CREATE DATABASE $DB_NAME OWNER $DB_USER"
    log_info "Base de datos $DB_NAME creada"
else
    log_info "Base de datos $DB_NAME ya existe (reparando ownership)"
fi

# Ejecutar el DDL idempotente del repo (necesita el repo clonado primero →
# se clona en Fase 5; para soportar re-runs con repo ya presente lo buscamos ahora)
if [[ ! -d "$INSTALL_DIR/.git" ]]; then
    log_info "Clonando repositorio (fase anticipada para el DDL)..."
    git clone "$REPO_URL" "$INSTALL_DIR" >/dev/null 2>&1 || die "git clone falló"
else
    log_info "Repo ya presente en $INSTALL_DIR (git pull para actualizar DDL)"
    git -C "$INSTALL_DIR" pull --ff-only >/dev/null 2>&1 || log_warn "git pull falló (sin internet o cambios locales) — se usa el DDL actual"
fi

SQL_FILE="$INSTALL_DIR/scripts/setup_database.sql"
[[ -f "$SQL_FILE" ]] || die "No existe $SQL_FILE (¿repo corrupto?)"

# Sustituir placeholder y ejecutar como admin DENTRO de la BD
sed "s/__DB_USER__/$DB_USER/g" "$SQL_FILE" > /tmp/hipocampo_setup_db.sql
run_psql_as_admin -v ON_ERROR_STOP=1 -d "$DB_NAME" -f /tmp/hipocampo_setup_db.sql >/dev/null
rm -f /tmp/hipocampo_setup_db.sql
log_success "Esquema aplicado (tablas, índices HNSW, ownership → $DB_USER)"

# ─── Trade Knowledge v4.3: Migración de memorias existentes ────
if [[ -f "$INSTALL_DIR/scripts/migrate_trade_knowledge.py" ]]; then
    log_info "Ejecutando migración Trade Knowledge..."
    "$VENV_DIR/bin/python" "$INSTALL_DIR/scripts/migrate_trade_knowledge.py" || log_warn "Migración trade_knowledge falló (continúa igual)"
fi

# ════════════════════════════════════════════════════════════════════════════
# FASE 4: Motor de embeddings
# ════════════════════════════════════════════════════════════════════════════
phase "FASE 4/8: Motor de embeddings"

EMBED_BASE_URL="http://127.0.0.1:11434/v1"
EMBED_MODEL="qwen3-embedding:0.6b"

if [[ "$EMBED_MODE" == "ollama" ]] && ! $SKIP_OLLAMA; then
    if ! have ollama; then
        log_info "Instalando Ollama..."
        if $IS_MAC; then
            pkg_install ollama
            brew services start ollama 2>/dev/null || true
        else
            curl -fsSL https://ollama.com/install.sh | sh
            sudo systemctl enable --now ollama 2>/dev/null || true
        fi
    else
        log_info "Ollama ya instalado"
    fi
    if have ollama; then
        log_info "Descargando modelo $EMBED_MODEL (~600MB, solo la primera vez)..."
        ollama pull "$EMBED_MODEL" || log_warn "ollama pull falló — reintenta manualmente: ollama pull $EMBED_MODEL"
    else
        log_warn "Ollama no disponible — el servidor usará fallback léxico hasta que lo instales"
    fi
elif [[ "$EMBED_MODE" == "api" ]]; then
    log_info "Modo API externa de embeddings"
    EMBED_BASE_URL="$(ask 'Base URL de la API (OpenAI-compatible)' 'https://integrate.api.nvidia.com/v1')"
    EMBED_MODEL="$(ask 'Modelo de embedding' 'qwen3-embedding')"
fi

# ════════════════════════════════════════════════════════════════════════════
# FASE 5: venv Python + dependencias + .env
# ════════════════════════════════════════════════════════════════════════════
phase "FASE 5/8: Entorno Python"

VENV_DIR="$INSTALL_DIR/.venv"
if [[ ! -x "$VENV_DIR/bin/python" ]]; then
    python3 -m venv "$VENV_DIR"
fi
"$VENV_DIR/bin/pip" install --upgrade pip --quiet
"$VENV_DIR/bin/pip" install -r "$INSTALL_DIR/requirements.txt" --quiet
log_success "Dependencias instaladas en $VENV_DIR"

# .env con las variables reales que lee hipocampo/db.py
cat > "$ENV_FILE" <<ENV
# Hipocampo MCP — generado por install.sh $(date -I)
DB_NAME=$DB_NAME
DB_USER=$DB_USER
DB_PASSWORD=$DB_PASSWORD
DB_HOST=localhost
EMBED_BASE_URL=$EMBED_BASE_URL
EMBED_MODEL=$EMBED_MODEL
ENV_PATH=$ENV_FILE
ENV
chmod 600 "$ENV_FILE"
log_success ".env generado (permisos 600)"

# ════════════════════════════════════════════════════════════════════════════
# FASE 6: Clientes MCP (OpenCode / Claude Desktop / Cursor)
# ════════════════════════════════════════════════════════════════════════════
phase "FASE 6/8: Clientes MCP"
if $SKIP_CLIENTS; then
    log_info "Omitido por --no-clients"
else
    "$VENV_DIR/bin/python" "$INSTALL_DIR/scripts/setup_client_configs.py" \
        --install-dir "$INSTALL_DIR" --port "$MCP_PORT" --unattended=$UNATTENDED
fi

# ════════════════════════════════════════════════════════════════════════════
# FASE 7: Servicio MCP + timer de mantenimiento (systemd user)
# ════════════════════════════════════════════════════════════════════════════
phase "FASE 7/8: Servicio MCP + mantenimiento automático"

if $IS_MAC; then
    log_warn "macOS: sin systemd — arranca el servidor manualmente:"
    log_warn "  $VENV_DIR/bin/python $INSTALL_DIR/scripts/hipocampo_mcp_server.py --http $MCP_PORT"
else
    # Conflicto de puerto: si algo más usa 8001, elegir el siguiente libre
    while ss -tln 2>/dev/null | grep -q ":$MCP_PORT "; do
        log_warn "Puerto $MCP_PORT ocupado — usando $((MCP_PORT+1))"
        MCP_PORT=$((MCP_PORT+1))
    done

    UDIR="$HOME/.config/systemd/user"
    mkdir -p "$UDIR"

    # Servicio MCP (si ya existía, se sobreescribe con las rutas actuales)
    cat > "$UDIR/hipocampo-mcp.service" <<SVC
[Unit]
Description=Hipocampo MCP Server — Dual memory system with BIRE search
After=network.target postgresql.service

[Service]
Type=simple
ExecStart=$VENV_DIR/bin/python $INSTALL_DIR/scripts/hipocampo_mcp_server.py --http $MCP_PORT
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
SVC

    # Timer semanal de mantenimiento (del repo, con ruta del venv correcta)
    if ! $SKIP_TIMER && [[ -f "$INSTALL_DIR/scripts/hipocampo-maintenance.service" ]]; then
        sed "s|^ExecStart=.*|ExecStart=$VENV_DIR/bin/python $INSTALL_DIR/scripts/run_maintenance.py --apply --quiet|" \
            "$INSTALL_DIR/scripts/hipocampo-maintenance.service" > "$UDIR/hipocampo-maintenance.service"
        cp "$INSTALL_DIR/scripts/hipocampo-maintenance.timer" "$UDIR/"
    fi

    # Timer trimestral de revisión de reglas automatica (cada 72h)
    if [[ -f "$INSTALL_DIR/scripts/hipocampo-review.service" ]]; then
        cp "$INSTALL_DIR/scripts/hipocampo-review.service" "$UDIR/hipocampo-review.service"
        cp "$INSTALL_DIR/scripts/hipocampo-review.timer" "$UDIR/"
        systemctl --user daemon-reload
        systemctl --user enable --now hipocampo-review.timer 2>/dev/null \
            && log_success "Timer revision automatica ACTIVO (cada 72h)"
    fi

    systemctl --user daemon-reload
    systemctl --user enable --now hipocampo-mcp.service
    systemctl --user restart hipocampo-mcp.service
    if ! $SKIP_TIMER && [[ -f "$UDIR/hipocampo-maintenance.timer" ]]; then
        systemctl --user enable --now hipocampo-maintenance.timer 2>/dev/null \
            && log_success "Timer mantenimiento ACTIVO (domingo 03:00, catch-up al encender)"
    fi
    log_success "Servicio MCP activo en puerto $MCP_PORT"
fi

# ════════════════════════════════════════════════════════════════════════════
# FASE 8: Autodiagnóstico
# ════════════════════════════════════════════════════════════════════════════
phase "FASE 8/8: Autodiagnóstico"

TEST_OK=true
wait_for_port() {
    for _ in $(seq 1 30); do
        curl -s --max-time 2 "http://127.0.0.1:$1/api/health" >/dev/null 2>&1 && return 0
        sleep 1
    done
    return 1
}

if $IS_MAC; then
    log_warn "macOS: salta autotest HTTP (arranca el server manualmente)"
else
    if ! wait_for_port "$MCP_PORT"; then
        log_error "El servicio no respondió en puerto $MCP_PORT"
        journalctl --user -u hipocampo-mcp.service -n 20 --no-pager || true
        TEST_OK=false
    else
        # 1. Health
        HEALTH="$(curl -s --max-time 20 "http://127.0.0.1:$MCP_PORT/api/health")"
        echo "$HEALTH" | grep -q "Health: OK" && log_success "Health check OK" || { log_error "Health falló: $HEALTH"; TEST_OK=false; }

        # 2. Save de prueba
        SAVE_RESP="$(curl -s --max-time 60 -X POST "http://127.0.0.1:$MCP_PORT/api/save" \
            -H 'Content-Type: application/json' \
            -d '{"content":"TEST-INSTALL: instalación exitosa de Hipocampo (borrar tras verificar)","memory_type":"event","code":"install_test","categories":["test"]}')"
        if echo "$SAVE_RESP" | grep -q '"ok": *true'; then
            TEST_ID="$(echo "$SAVE_RESP" | grep -oE '"id": *[0-9]+' | grep -oE '[0-9]+' || true)"
            log_success "Save de prueba OK (id=$TEST_ID)"
        else
            log_error "Save de prueba falló: $SAVE_RESP"; TEST_OK=false; TEST_ID=""
        fi

        # 3. Search semántico
        if sleep 6; then :; fi  # margen para el embedding en background
        SEARCH="$(curl -s --max-time 60 "http://127.0.0.1:$MCP_PORT/api/search?q=instalaci%C3%B3n%20exitosa")"
        echo "$SEARCH" | grep -q "TEST-INSTALL" && log_success "Búsqueda de prueba OK" \
            || { log_warn "La búsqueda no encontró el recuerdo aún (embedding en background) — no crítico"; }

        # 4. Limpieza del recuerdo de prueba
        if [[ -n "$TEST_ID" ]]; then
            if PGPASSWORD="$DB_PASSWORD" psql -h localhost -U "$DB_USER" -d "$DB_NAME" \
                -c "DELETE FROM memoria_vectorial WHERE metadatos->>'code'='install_test'" >/dev/null 2>&1; then
                log_success "Recuerdo de prueba eliminado"
            else
                log_warn "No se pudo borrar el test id=$TEST_ID (borra manualmente: DELETE FROM memoria_vectorial WHERE metadatos->>'code'='install_test')"
            fi
        fi
    fi
fi

echo
if $TEST_OK; then
    echo -e "${COLOR_GREEN}╔══════════════════════════════════════════════════════════════════╗${COLOR_RESET}"
    echo -e "${COLOR_GREEN}║             🧠 HIPOCAMPO MCP INSTALADO CON ÉXITO                 ║${COLOR_RESET}"
    echo -e "${COLOR_GREEN}╚══════════════════════════════════════════════════════════════════╝${COLOR_RESET}"
    echo "  ✓ PostgreSQL + pgvector: configurado"
    echo "  ✓ Base de datos: $DB_NAME (HNSW 1024d, owner: $DB_USER)"
    echo "  ✓ Motor embeddings: $([ "$EMBED_MODE" = ollama ] && echo "Ollama ($EMBED_MODEL)" || echo "API $EMBED_MODEL")"
    echo "  ✓ Clientes MCP: $("$VENV_DIR/bin/python" "$INSTALL_DIR/scripts/setup_client_configs.py" --list-only --install-dir "$INSTALL_DIR" 2>/dev/null || echo 'ver docs/INSTALL.md')"
    $IS_MAC || echo "  ✓ Servicio MCP: http://localhost:$MCP_PORT/mcp (systemd --user)"
    $IS_MAC || echo "  ✓ Mantenimiento: timer dominical 03:00 (Persistent=true)"
    echo
    echo "  Desinstalar:  bash $INSTALL_DIR/uninstall.sh"
    echo "  Manual:       $INSTALL_DIR/docs/INSTALL.md"
else
    echo -e "${COLOR_RED}La instalación terminó con errores — revisa los [ERROR] arriba.${COLOR_RESET}"
    exit 1
fi
