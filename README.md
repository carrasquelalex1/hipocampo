---
title: Hipocampo MCP
emoji: 🧠
colorFrom: blue
colorTo: purple
sdk: docker
pinned: false
---

# Hipocampo: Dual-Memory System with Sparse Selective Caching

[![Version](https://img.shields.io/badge/version-3.8-blue.svg)](https://github.com/carrasquelalex1/hipocampo)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![MCP Server](https://img.shields.io/badge/MCP-Server-blue)](https://alexbell1-hipocampo-mcp.hf.space/mcp)
[![MCP Registry](https://img.shields.io/badge/MCP%20Registry-active-green)](https://registry.modelcontextprotocol.io/v0.1/servers?search=carrasquelalex1/hipocampo)
[![Glama](https://img.shields.io/badge/Glama-Rating%20A-brightgreen)](https://glama.ai/mcp/servers/carrasquelalex1/hipocampo)
[![hipocampo MCP server](https://glama.ai/mcp/servers/carrasquelalex1/hipocampo/badges/score.svg)](https://glama.ai/mcp/servers/carrasquelalex1/hipocampo)

> **⚠️ Transport Note:** SSE transport is deprecated since MCP spec 2025-03-26.
> Hipocampo now uses **Streamable HTTP** (single endpoint `/mcp`) as the recommended remote transport.
> SSE (`/sse`) remains available for backward compatibility but will be removed in a future release.

## 🌐 MCP Server — Live on Hugging Face

Hipocampo runs as a **free MCP server** on Hugging Face Spaces. Connect from any MCP client:

```
URL: https://alexbell1-hipocampo-mcp.hf.space/mcp
```

**🧪 Interactive Playground:** Try saving and searching memories from your browser at [https://alexbell1-hipocampo-mcp.hf.space/](https://alexbell1-hipocampo-mcp.hf.space/) — no registration or MCP client needed.

> **⚠️ Important:** The Hugging Face free tier is **ephemeral** — data is lost on restart/deploy. This instance is intended for testing only. For persistent storage, run Hipocampo locally (see [Quick Start](#🛠-quick-start)) or connect an external database (Neon, Supabase, etc.).

```json
{
  "mcpServers": {
    "hipocampo": {
      "url": "https://alexbell1-hipocampo-mcp.hf.space/mcp",
      "type": "streamable-http"
    }
  }
}
```

**Embedding model:** `sentence-transformers/all-MiniLM-L6-v2` (384 dims) via **Hugging Face Inference API** (free, no credit card required).

---

**Hipocampo** is an advanced dual-memory persistence architecture designed for autonomous AI agents. By maintaining both technical knowledge and user profiling data across sessions, Hipocampo provides a reliable, stateful context that enables agents to learn, adapt, and scale efficiently. 

Built on top of **PostgreSQL 17** with `pgvector`, it features **BIRE v3.7** — a hybrid retrieval engine combining semantic embeddings (1024d), lexical expansion, and GIN trigram search with dynamic score fusion. Also includes **Sparse Selective Caching (SSC)** as an experimental pipeline.

---

## 🚀 Key Features

* **Dual-Memory Architecture**: Distinct storage layers for technical records (`memoria_vectorial`) and user profile data (`memory_items`), each utilizing 1024-dimensional embeddings.
* **BIRE v3.7 (default)**: Hybrid search engine combining NVIDIA embeddings (1024d), query expansion, GIN trigram, and composite scoring — used by all MCP tools.
* **SSC (experimental)**: Alternative four-phase progressive pipeline: *Tag Router* → *pgvector Top-K* → *GIN Trigram* → *ILIKE Fallback*.
* **Logarithmic Checkpointing**: Intelligently compresses historical memories based on time decay, shrinking 24-hour granular details into unified 90-day checkpoints.
* **Automated Tagging Engine**: A robust, Regex-based rule engine that autonomously categorizes and tags records upon persistence.
* **Cross-System Vector Search**: Unified semantic search across over 1,100 records for deep cross-referencing.
* **Model Context Protocol (MCP)**: Native integration via a FastMCP server, exposing seamless read/write capabilities to modern MCP clients (e.g., Claude Desktop, OpenCode).

---

## 🎯 Use Cases

### Error → Learn → Never Repeat (AI Agent Learning Loop)

Hipocampo enables AI agents to **learn from mistakes across sessions** using a simple cycle:

```
┌─ 1. SEARCH ─────────────────────────────┐
│  Before executing a command, the agent   │
│  searches Hipocampo for similar errors:  │
│  search_hipocampo("error <context>")     │
└───────────────────┬──────────────────────┘
                    │
┌─ 2. EXECUTE ──────▼──────────────────────┐
│  If match found → apply known solution   │
│  If not → attempt new approach           │
└───────────────────┬──────────────────────┘
                    │
┌─ 3. EVALUATE ─────▼──────────────────────┐
│  Did it fail? Capture:                   │
│  - error context & exit code             │
│  - what was attempted                    │
│  - what happened                         │
└───────────────────┬──────────────────────┘
                    │
┌─ 4. PERSIST ──────▼──────────────────────┐
│  save_hipocampo(                          │
│    content="Error X: tried Y, result Z", │
│    memory_type="decision",               │
│    code="error_<hash>",                  │
│    categories=["bugfix", "<tool>"]       │
│  )                                        │
└──────────────────────────────────────────┘
```

**Real example:** An agent tries `flatpak install npm` and fails. It saves the error to Hipocampo: *"npm is a Node.js package manager, not a Flatpak package. Use npm directly."* Next time the same command is attempted, the agent finds this record and knows the solution immediately — without repeating the mistake.

**Over time**, the agent's error knowledge base grows organically. Each failure makes future sessions smarter. This turns Hipocampo from a simple archive into a **continuous learning system** for AI agents.

### ⚙️ How to configure your agent

To enable this behavior, you need to instruct your agent to use the cycle above. This is done by adding instructions to the agent's configuration file, depending on the client:

| Agent | Configuration file | Example |
|---|---|---|
| **OpenCode** | `AGENTS.md` (project root) or `~/.opencode/AGENTS.md` | [See example](#) |
| **Claude Code** | `CLAUDE.md` or `~/.claude/CLAUDE.md` | Similar approach |
| **Cursor** | `.cursorrules` | Add instructions in plain text |
| **Windsurf** | `.windsurfrules` | Same structure |
| **Cline** | `CLINE.md` | Same structure |

**Minimal example** for `AGENTS.md` / `CLAUDE.md`:

```markdown
## Error Learning Cycle

1. Before running any command, search: `search_hipocampo("error <command> <context>")`
2. If a similar error is found, apply the documented solution and skip the failing attempt
3. If the command fails (exit code != 0, timeout, "error"/"failed" in output):
   - Save to Hipocampo: `save_hipocampo(content="Error: {stderr[:500]}. Attempt: {what was tried}. Result: {what happened}.", memory_type="decision", code="error_<hash>", categories=["bugfix", "<language/tool>"])`
```

> 💡 **Tip:** For MCP-native agents (OpenCode, Claude Code), Hipocampo tools are available directly. For others, use the HTTP endpoint or CLI scripts.

### Other use cases
- **Persistent user profile**: Remember preferences, configs, and personal data across sessions
- **Project state tracking**: Keep context on ongoing projects, decisions made, and pending tasks
- **Cross-session knowledge**: Build on previous work without repeating context

---

## 🛠️ Quick Start

### Prerequisites
* **PostgreSQL 17+** (with `pgvector` and `pg_trgm` extensions enabled)
* **Python 3.13+**
* **NVIDIA API Key** (for `nvidia/nv-embedqa-e5-v5` embeddings) — or **Hugging Face API Key** for `sentence-transformers/all-MiniLM-L6-v2` (free via HF Inference API)

### Installation

```bash
# 1. Clone the repository
git clone https://github.com/carrasquelalex1/hipocampo.git
cd hipocampo

# 2. Setup the PostgreSQL Database
createdb hipocampo_db
psql -d hipocampo_db -c "CREATE EXTENSION vector; CREATE EXTENSION pg_trgm;"
psql -d hipocampo_db -f esquema.sql

# 3. Initialize Python Environment
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 4. Environment Configuration
cp .env.example .env
# Edit .env with your DB_HOST, DB_USER, and NVIDIA_API_KEY
```

### Basic Usage

Hipocampo provides specialized scripts to interact with the core engine:

```bash
# Perform a search using BIRE v3.7 (modern, recommended)
python3 scripts/hipocampo_search.py "query term"

# Perform a search using SSC v1.0 (experimental, legacy)
python3 scripts/hipocampo_ssc_search.py "query term"

# Compress older memories using Logarithmic Checkpointing
python3 scripts/hipocampo_checkpoint.py --dry-run
python3 scripts/hipocampo_checkpoint.py --force
```

---

## 🧠 System Architecture

The core of Hipocampo is backed by a relational and vector hybrid design:

```text
hipocampo_db (PostgreSQL 17 + pgvector + pg_trgm)
├── memoria_vectorial (Technical Knowledge)
│   ├── Columns: contenido (text), metadatos (jsonb), embedding (vector 1024d)
│   └── Indexes: HNSW (cosine similarity, 1024d), GIN (trigram)
├── memory_items (User Profile & Events)
│   ├── Columns: memory_type (profile|event|decision), summary, embedding, extra
│   └── Indexes: HNSW (cosine similarity, 1024d), GIN (trigram)
├── memory_categories (Classification Taxonomy)
├── category_items (M:N Mapping)
└── resources (Referenced Assets & URLs)
```

### BIRE v3.7 — Hybrid Search Engine

BIRE (Búsqueda Integrada por Relevancia Expansiva) is the default search engine used by all MCP tools. It combines vector and lexical search with dynamic score fusion:

1. **Query Expansion** — Expands terms using synonyms and stemming before search.
2. **Vector Search** — NVIDIA embeddings (1024d) cosine similarity across both tables.
3. **GIN Trigram** — Lexical expansion when vector confidence is low.
4. **Composite Scoring** — Weighted fusion of vector + lexical scores with adaptive cutoff.

An **SSC (Sparse Selective Caching)** pipeline is also available as an experimental alternative:

1. **Phase 1: Tag Router** – Classifies the query intent (profile vs. technical) and dynamically assigns weights.
2. **Phase 2: PGVector Top-K** – Semantic search across both tables. Execution halts here if confidence ≥ 70%.
3. **Phase 3: GIN Trigram** – Lexical expansion via Trigram indexing if semantic confidence is < 70%.
4. **Phase 4: ILIKE Scan** – Final fallback full-table scan triggered only if confidence falls < 40%.

---

## 🔌 MCP Server Integration

Hipocampo includes a fully functional **FastMCP** server, allowing LLM agents to autonomously read and write memories. 

### Available MCP Tools

**Memory Operations:**
* `search_hipocampo(query, session_id?)`: Unified semantic and lexical search (auto-records metrics). Optionally filter by session.
* `quick_hipocampo_search(query)`: Shorthand alias for rapid queries.
* `save_hipocampo(content, memory_type, code, categories, session_id?)`: Persist data into the technical memory store (`memoria_vectorial`). Supports optional session isolation.
* `profile_hipocampo(summary, extra, categories)`: Store personal or event-driven user data (`memory_items`).

**CRUD Operations:**
* `update_hipocampo(id, content?, memory_type?, code?, categories?)`: Update an existing memory. Regenerates embedding if content changes.
* `delete_hipocampo(id)`: Permanently delete a memory by ID.

**Self-Diagnosis & Auto-Repair (Fase 1):**
* `hipocampo_health()`: Full system health check (PostgreSQL, NVIDIA API, disk, extensions).
* `hipocampo_auto_repair()`: Automatically repairs detected issues (restart PostgreSQL, create missing tables).

**Performance Optimization (Fase 2):**
* `hipocampo_stats()`: Query performance metrics, latency analysis, and optimization recommendations.
* `hipocampo_tune()`: Auto-adjusts BIRE/SSC thresholds and hybrid weights based on real usage data.

**Memory Maintenance (Fase 3):**
* `hipocampo_dedup(merge)`: Detects and merges duplicate memories (exact + semantic via cosine similarity).
* `hipocampo_checkpoint(dry_run)`: Logarithmic checkpointing to compress old memories.
* `hipocampo_maintenance()`: Full maintenance cycle (repair → dedup → checkpoint → tune).

**Time Decay:**
* Scores of memories >7 days old automatically decay ~5% per week (floor at 30%), keeping recent knowledge at the top.

**Webhook Watches:**
* `watch_hipocampo(pattern, webhook_url)`: Register a webhook that fires on save/update/delete events matching a text pattern.
* `unwatch_hipocampo(id)`: Remove a registered webhook.
* `list_watches()`: List all registered webhooks and their targets.

### Starting the Server

```bash
# Standard I/O mode (default for local desktop clients)
python3 scripts/hipocampo_mcp_server.py

# Streamable HTTP mode (recommended for remote clients)
python3 scripts/hipocampo_mcp_server.py --http 8001

# Legacy SSE mode (deprecated, only for backward compatibility)
python3 scripts/hipocampo_mcp_server.py --sse 8001
```

For advanced configuration, please refer to the [MCP Server Guide](docs/mcp-server-guide.md).

---

## ☕ Support / Donaciones

If this project helps you, consider supporting its development:

[![PayPal](https://img.shields.io/badge/Donate-PayPal-00457C?style=for-the-badge&logo=paypal)](https://paypal.me/carrasquealex)
[![GitHub Sponsors](https://img.shields.io/badge/sponsor-30363D?style=for-the-badge&logo=GitHub-Sponsors)](https://github.com/sponsors/carrasquelalex1)

- **PayPal:** [paypal.me/carrasquealex](https://paypal.me/carrasquealex)
- **USDT (TRC-20):** (próximamente)
- Cada grano de arena ayuda a mantener el proyecto vivo 🧠✨

---

## 📄 License

This project is licensed under the **MIT License**.

---

## 🇪🇸 Versión en Español

# Hipocampo: Sistema de Memoria Dual con Caché Selectivo (CS)

[![Glama](https://img.shields.io/badge/Glama-Rating%20A-brightgreen)](https://glama.ai/mcp/servers/carrasquelalex1/hipocampo)
[![hipocampo MCP server](https://glama.ai/mcp/servers/carrasquelalex1/hipocampo/badges/score.svg)](https://glama.ai/mcp/servers/carrasquelalex1/hipocampo)
[![MCP Server](https://img.shields.io/badge/MCP-Server-blue)](https://alexbell1-hipocampo-mcp.hf.space/mcp)

> **⚠️ Nota de Transporte:** SSE está deprecado desde spec MCP 2025-03-26.
> Hipocampo ahora usa **Streamable HTTP** (endpoint único `/mcp`) como transporte remoto recomendado.

## 🌐 Servidor MCP — Live en Hugging Face

Hipocampo corre como **servidor MCP gratuito** en Hugging Face Spaces. Conéctate desde cualquier cliente MCP:

```json
{
  "mcpServers": {
    "hipocampo": {
      "url": "https://alexbell1-hipocampo-mcp.hf.space/mcp",
      "type": "streamable-http"
    }
  }
}
```

**🧪 Playground interactivo:** Prueba guardar y buscar recuerdos desde el navegador en [https://alexbell1-hipocampo-mcp.hf.space/](https://alexbell1-hipocampo-mcp.hf.space/) — sin registro ni cliente MCP.

> **⚠️ Importante:** El tier gratuito de Hugging Face es **efímero** — los datos se pierden al reiniciar/desplegar. Esta instancia es solo para pruebas. Para persistencia real, ejecuta Hipocampo localmente o conecta una base externa.

**Hipocampo** es una arquitectura avanzada de persistencia de memoria dual diseñada para agentes de Inteligencia Artificial. Al mantener tanto el conocimiento técnico como los datos del perfil del usuario entre sesiones, Hipocampo proporciona un contexto con estado confiable que permite a los agentes aprender, adaptarse y escalar eficientemente.

Construido sobre **PostgreSQL 17** y `pgvector`, utiliza **BIRE v3.7** — un motor híbrido que combina embeddings semánticos (1024d), expansión léxica y búsqueda GIN trigram con fusión dinámica de puntuación. Incluye también **Caché Selectivo (CS/SSC)** como pipeline experimental.

---

## 🚀 Características Principales

* **Arquitectura de Memoria Dual**: Capas de almacenamiento separadas para registros técnicos (`memoria_vectorial`) y datos de perfil (`memory_items`), ambas utilizando embeddings de 1024 dimensiones.
* **BIRE v3.7 (por defecto)**: Búsqueda híbrida con embeddings NVIDIA (1024d), expansión de consulta, GIN trigram y puntuación compuesta — usado por todas las tools MCP.
* **Caché Selectivo (CS/SSC, experimental)**: Pipeline alternativo de 4 fases: *Tag Router* → *pgvector Top-K* → *GIN Trigram* → *ILIKE Fallback*.
* **Checkpointing Logarítmico**: Compresión inteligente basada en el decaimiento del tiempo, consolidando detalles granulares en un solo registro tras 90 días.
* **Auto-MeJORA MCP**: Autodiagnóstico (health check + auto-repair), optimización dinámica (stats + tune), y mantenimiento de memoria (dedup + checkpoint) — todo desde herramientas MCP.
* **Motor de Auto-Etiquetado**: Reglas basadas en expresiones regulares que categorizan la información de manera autónoma al momento de la persistencia.
* **Protocolo MCP (Model Context Protocol)**: Integración nativa mediante un servidor FastMCP con 12 herramientas, otorgando capacidades directas de lectura/escritura y mantenimiento a clientes MCP como Claude Desktop y OpenCode.

---

## 🎯 Casos de Uso

### Error → Aprender → No Repetir (Ciclo de Aprendizaje para Agentes IA)

Hipocampo permite que agentes de IA **aprendan de sus errores entre sesiones** con un ciclo simple:

```
┌─ 1. BUSCAR ─────────────────────────────┐
│  Antes de ejecutar, el agente busca     │
│  errores similares en Hipocampo:        │
│  search_hipocampo("error <contexto>")   │
└───────────────────┬──────────────────────┘
                    │
┌─ 2. EJECUTAR ─────▼──────────────────────┐
│  Si hay match → aplicar solución conocida│
│  Si no → intentar nuevo enfoque         │
└───────────────────┬──────────────────────┘
                    │
┌─ 3. EVALUAR ──────▼──────────────────────┐
│  ¿Falló? Capturar:                      │
│  - contexto del error y exit code       │
│  - qué se intentó                       │
│  - qué pasó                             │
└───────────────────┬──────────────────────┘
                    │
┌─ 4. PERSISTIR ────▼──────────────────────┐
│  save_hipocampo(                          │
│    content="Error X: intenté Y, pasó Z",│
│    memory_type="decision",               │
│    code="error_<hash>",                  │
│    categories=["bugfix", "<herramienta>"]│
│  )                                        │
└──────────────────────────────────────────┘
```

**Ejemplo real:** Un agente intenta `flatpak install npm` y falla. Guarda el error en Hipocampo: *"npm es un gestor de paquetes de Node.js, no un paquete Flatpak. Usar npm directamente."* La próxima vez que se intente el mismo comando, el agente encuentra este registro y aplica la solución de inmediato.

**Con el tiempo**, la base de conocimiento de errores crece orgánicamente. Cada fallo hace más inteligentes las sesiones futuras. Esto convierte a Hipocampo de un simple archivo en un **sistema de aprendizaje continuo** para agentes de IA.

### ⚙️ Cómo configurar tu agente

Para activar este comportamiento, hay que instruir al agente. Se hace agregando reglas en su archivo de configuración:

| Agente | Archivo de configuración |
|---|---|
| **OpenCode** | `AGENTS.md` (raíz del proyecto) o `~/.opencode/AGENTS.md` |
| **Claude Code** | `CLAUDE.md` o `~/.claude/CLAUDE.md` |
| **Cursor** | `.cursorrules` |
| **Windsurf** | `.windsurfrules` |
| **Cline** | `CLINE.md` |

**Ejemplo mínimo** para `AGENTS.md` / `CLAUDE.md`:

```markdown
## Ciclo de Aprendizaje de Errores

1. Antes de ejecutar un comando, busca: `search_hipocampo("error <comando> <contexto>")`
2. Si hay error similar, aplica la solución documentada y omite el intento fallido
3. Si el comando falla (exit code != 0, timeout, "error"/"failed" en output):
   - Guarda en Hipocampo: `save_hipocampo(content="Error: {stderr[:500]}. Intento: {qué se probó}. Resultado: {qué pasó}.", memory_type="decision", code="error_<hash>", categories=["bugfix", "<lenguaje/herramienta>"])`
```

> 💡 **Tip:** Para agentes nativos MCP (OpenCode, Claude Code), las tools de Hipocampo están disponibles directamente. Para otros, usa el endpoint HTTP o los scripts CLI.

### Otros casos de uso
- **Perfil de usuario persistente**: Recordar preferencias, configuraciones y datos personales entre sesiones
- **Seguimiento de proyectos**: Mantener contexto de proyectos activos, decisiones tomadas y tareas pendientes
- **Conocimiento entre sesiones**: Continuar trabajos previos sin repetir contexto

---

## 🛠️ Instalación Rápida

```bash
# 1. Clonar y configurar BD
git clone https://github.com/carrasquelalex1/hipocampo.git
cd hipocampo
createdb hipocampo_db
psql -d hipocampo_db -c "CREATE EXTENSION vector; CREATE EXTENSION pg_trgm;"
psql -d hipocampo_db -f esquema.sql

# 2. Entorno Python y dependencias
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# 3. Configurar variables de entorno
cp .env.example .env
# Editar .env con DB_HOST, DB_USER, NVIDIA_API_KEY
```

Para usar la búsqueda directamente desde la terminal:
```bash
python3 scripts/hipocampo_search.py "término de búsqueda"       # BIRE v3.7 (recomendado)
python3 scripts/hipocampo_ssc_search.py "término de búsqueda"   # SSC v1.0 (experimental)
```

Para inicializar el servidor MCP:
```bash
python3 scripts/hipocampo_mcp_server.py
python3 scripts/hipocampo_mcp_server.py --http 8001   # Streamable HTTP (recomendado)
python3 scripts/hipocampo_mcp_server.py --sse 8001    # legacy (deprecado)
```

### Herramientas MCP Disponibles

**Operaciones de Memoria:**
* `search_hipocampo(consulta, session_id?)`: Búsqueda semántica + léxica híbrida (auto-registra métricas). Filtro opcional por sesión.
* `quick_hipocampo_search(consulta)`: Alias rápido para búsquedas.
* `save_hipocampo(contenido, tipo, codigo, categorias, session_id?)`: Guarda datos técnicos en `memoria_vectorial`. Soporta aislamiento por sesión.
* `profile_hipocampo(resumen, extra, categorias)`: Guarda datos de perfil en `memory_items`.

**Operaciones CRUD:**
* `update_hipocampo(id, contenido?, tipo?, codigo?, categorias?)`: Actualiza un recuerdo existente. Regenera embedding si cambia el contenido.
* `delete_hipocampo(id)`: Elimina un recuerdo permanentemente por ID.

**Autodiagnóstico y Reparación (Fase 1):**
* `hipocampo_health()`: Health check completo (PostgreSQL, NVIDIA API, disco, extensiones).
* `hipocampo_auto_repair()`: Repara problemas automáticamente (reinicia PostgreSQL, crea tablas faltantes).

**Optimización de Rendimiento (Fase 2):**
* `hipocampo_stats()`: Métricas de rendimiento, latencia, y recomendaciones de optimización.
* `hipocampo_tune()`: Ajusta thresholds BIRE/SSC y pesos híbridos según uso real.

**Mantenimiento de Memoria (Fase 3):**
* `hipocampo_dedup(fusionar)`: Detecta y fusiona memorias duplicadas (exactas + semánticas).
* `hipocampo_checkpoint(seco)`: Checkpointing logarítmico para comprimir memorias antiguas.
* `hipocampo_maintenance()`: Ciclo completo de mantenimiento (reparar → dedup → checkpoint → tune).

**Decaimiento Temporal:**
* Scores de memorias >7 días decaen ~5% por semana (piso 30%), priorizando conocimiento reciente.

**Webhooks (Watch):**
* `watch_hipocampo(patron, webhook_url)`: Registra un webhook que se dispara en eventos save/update/delete cuando el contenido coincide con un patrón.
* `unwatch_hipocampo(id)`: Elimina un webhook registrado.
* `list_watches()`: Lista todos los webhooks activos.

*Consulte los manuales en la carpeta `docs/` para información arquitectónica y configuraciones avanzadas.*

---

## ☕ Donaciones

Si este proyecto te es útil, considera apoyarlo:

[![PayPal](https://img.shields.io/badge/Donar-PayPal-00457C?style=for-the-badge&logo=paypal)](https://paypal.me/carrasquealex)

- **PayPal:** [paypal.me/carrasquealex](https://paypal.me/carrasquealex)
- **USDT (TRC-20):** (próximamente)
- Cada aporte ayuda a mantener vivo el proyecto 🧠✨

