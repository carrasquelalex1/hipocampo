# 📦 Instalación de Hipocampo MCP

## Instalación rápida (una línea)

```bash
curl -fsSL https://raw.githubusercontent.com/carrasquelalex1/hipocampo/main/install.sh | bash
```

Para máquinas sin interacción (VPS, contenedores):

```bash
curl -fsSL https://raw.githubusercontent.com/carrasquelalex1/hipocampo/main/install.sh | bash -s -- --unattended
```

> 💡 Revisar el script antes de ejecutarlo es buena práctica:
> `curl -fsSL <url> | less` — o clona el repo y corre `bash install.sh`.

El instalador es **idempotente**: ejecutarlo de nuevo repara ownership,
actualiza el repo y regenera configs sin borrar tus recuerdos.

## Requisitos

| | Mínimo | Recomendado |
|---|---|---|
| CPU | 2 núcleos (x86_64 / ARM64) | 4+ núcleos |
| RAM | 2 GB (embeddings por API) | 4–8 GB (Ollama local) |
| Disco | 5 GB libres | 8 GB |
| SO | Ubuntu 22.04+ / Debian 12+ / Fedora 39+ / Arch / macOS (Homebrew) / Windows vía WSL2 | Ubuntu LTS |

Se necesita `sudo` para instalar PostgreSQL y pgvector.

## Qué hace el instalador (8 fases)

1. **Diagnóstico** — detecta distro, gestor de paquetes (apt/dnf/pacman/brew), RAM y disco; instala `curl`, `git`, `python3`, `python3-venv`.
2. **PostgreSQL + pgvector** — instala el repo oficial PGDG si hace falta, o compila pgvector desde fuente como fallback.
3. **Base de datos** — crea rol `hipocampo_user` con contraseña aleatoria (o reutiliza la del `.env` si ya existe), BD `hipocampo_db`, y aplica `scripts/setup_database.sql`: todas las tablas con `IF NOT EXISTS`, índices HNSW/GIN, y **ownership completo al usuario del MCP** (evita el bug histórico de `query_stats`).
4. **Embeddings** — Modo A (default): instala Ollama y descarga `qwen3-embedding:0.6b` (1024d, ~600 MB, 100% local). Modo B (`--embed-api`): cualquier endpoint OpenAI-compatible (NVIDIA NIM, OpenAI...).
5. **Python** — clona el repo a `~/.local/share/hipocampo`, crea `.venv` aislado e instala `requirements.txt`.
6. **Clientes MCP** — registra Hipocampo automáticamente en los clientes detectados: **OpenCode** (remote HTTP), **Claude Desktop**, **Gemini CLI/Antigravity**, **Cursor**, **VS Code**, **Windsurf**. Con `--no-clients` se omite.
7. **Servicio + mantenimiento** — crea `hipocampo-mcp.service` (systemd user, puerto 8001 o el siguiente libre) y el **timer semanal** `hipocampo-maintenance.timer` (domingo 03:00, `Persistent=true` = catch-up si la PC estaba apagada).
8. **Autodiagnóstico** — health check HTTP, save de prueba, búsqueda semántica de prueba y limpieza del registro de prueba. Muestra el resumen final.

## Opciones

```text
--unattended      Sin preguntas (defaults: Ollama, ~/.local/share/hipocampo)
--embed-api       Embeddings por API externa en vez de Ollama local
--install-dir DIR Ruta de instalación (default ~/.local/share/hipocampo)
--db-user USER    Rol PostgreSQL (default hipocampo_user)
--no-clients      No registrar clientes MCP
--no-timer        No instalar el timer de mantenimiento
--no-ollama       No instalar Ollama (útil si ya está o se usa --embed-api)
```

## Verificación manual post-install

```bash
systemctl --user status hipocampo-mcp.service      # servicio activo
curl -s http://localhost:8001/api/health           # health OK
systemctl --user list-timers hipocampo-maintenance.timer  # próxima ejecución
```

Prueba de búsqueda semántica:

```bash
curl -s "http://localhost:8001/api/search?q=prueba"
```

## Instalación manual (sin install.sh)

1. **Dependencias**: PostgreSQL 15+, pgvector, Python 3.10+.
2. **BD**:
   ```bash
   sudo -u postgres createuser hipocampo_user
   sudo -u postgres createdb hipocampo_db -O hipocampo_user
   sudo -u postgres psql -c "ALTER USER hipocampo_user PASSWORD 'TU_PASSWORD';"
   sudo -u postgres psql -d hipocampo_db -f scripts/setup_database.sql   # tras reemplazar __DB_USER__
   ```
3. **Repo + venv**:
   ```bash
   git clone https://github.com/carrasquelalex1/hipocampo.git ~/.local/share/hipocampo
   cd ~/.local/share/hipocampo && python3 -m venv .venv
   .venv/bin/pip install -r requirements.txt
   ```
4. **`.env`** (en la raíz del repo):
   ```ini
   DB_NAME=hipocampo_db
   DB_USER=hipocampo_user
   DB_PASSWORD=TU_PASSWORD
   DB_HOST=localhost
   EMBED_BASE_URL=http://127.0.0.1:11434/v1
   EMBED_MODEL=qwen3-embedding:0.6b
   ```
5. **Servidor**:
   ```bash
   .venv/bin/python scripts/hipocampo_mcp_server.py --http 8001
   ```
6. **Cliente MCP** — el instalador registra Hipocampo automáticamente en los clientes detectados:
   - **OpenCode** (`~/.config/opencode/opencode.json[c]`) — modo REMOTE HTTP
   - **Claude Desktop** (`~/.config/Claude/claude_desktop_config.json`) — stdio
   - **Gemini CLI / Antigravity CLI** (`~/.gemini/settings.json`) — stdio
   - **Cursor** (`~/.cursor/mcp.json`) — stdio
   - **VS Code** (`~/.vscode/mcp.json`) — stdio (formato `"servers"`)
   - **Windsurf** (`~/.codeium/windsurf/mcp_config.json`) — stdio

   Con `--no-clients` se omite el registro automático.

## Desinstalación

```bash
bash ~/.local/share/hipocampo/uninstall.sh            # pregunta antes de borrar la BD
bash ~/.local/share/hipocampo/uninstall.sh --keep-db  # conserva la BD
bash ~/.local/share/hipocampo/uninstall.sh --purge-db -y  # borra todo (hace dump antes)
```

Ollama y PostgreSQL no se desinstalan (pueden servir a otros proyectos).

## Solución de problemas

| Síntoma | Causa probable | Fix |
|---|---|---|
| `psql: connection refused` | PostgreSQL no inició | `sudo systemctl enable --now postgresql` |
| `extension vector not available` | pgvector no instalado | instalar paquete `postgresql-<ver>-pgvector` o compilar de fuente |
| Health `DEGRADED` embeddings | Ollama caído o modelo sin descargar | `ollama pull qwen3-embedding:0.6b` |
| Puerto 8001 ocupado | Otro servicio | el instalador auto-elige el siguiente libre; revisa `systemctl --user status hipocampo-mcp` |
| Cliente no ve las tools | Config cargada antes del cambio | reiniciar OpenCode/Claude/Cursor |
