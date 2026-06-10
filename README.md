# Hipocampo — Dual Memory System with SSC (Sparse Selective Caching)

**Author:** Alexander Carrasquel  
**Version:** 3.7  
**License:** MIT

Hipocampo is a **dual-memory system** for AI agents that persists technical knowledge and user profile data across sessions. It uses PostgreSQL 17 with pgvector for semantic search, and implements **Sparse Selective Caching (SSC)**, a progressive 4-phase retrieval algorithm inspired by *"Memory Caching: RNNs with Growing Memory"* (Google, 2025).

---

## Features

- **Dual Memory Architecture:** Separate stores for technical records (`memoria_vectorial`) and user profile (`memory_items`), each with 768d embeddings
- **SSC Search (v3.7):** 4-phase progressive retrieval — Tag Router → pgvector Top-K → GIN Trigram → ILIKE Fallback
- **BIRE Search (v3.6):** Original unified search with lexical expansion, hybrid scoring, and tag expansion
- **Logarithmic Checkpointing:** Compresses old memories by time scale (24h detail → 90d+ single checkpoint)
- **Auto-Tagging:** Regex-based rule engine automatically assigns tags and categories on persist
- **Cross-System Vector Search:** Unified 768d embeddings across 1,137 records (814 MV + 323 MI)
- **Active Agent Re-ranking:** Optional re-ranking by the AI agent context (Claude) without external API calls

---

## Quick Start

### Prerequisites

- PostgreSQL 17+ with `pgvector` and `pg_trgm` extensions
- Python 3.13+
- Google AI API key for embeddings (`gemini-embedding-001`)

### Installation

```bash
git clone https://github.com/carrasquelalex1/hipocampo.git
cd hipocampo

# Database setup
createdb hipocampo_db
psql -d hipocampo_db -c "CREATE EXTENSION vector; CREATE EXTENSION pg_trgm;"
psql -d hipocampo_db -f esquema.sql

# Python environment
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# Configure .env
cp .env.example .env
# Edit .env: set DB_HOST, DB_USER, GOOGLE_API_KEY
```

### Usage

```bash
# Search with SSC (Sparse Selective Caching)
python3 scripts/hipocampo_ssc_search.py "query term"

# Search with BIRE (original)
python3 scripts/hipocampo_search.py "query term"

# Checkpoint old memories
python3 scripts/hipocampo_checkpoint.py --dry-run
python3 scripts/hipocampo_checkpoint.py --force
```

---

## Architecture

```
hipocampo_db (PostgreSQL 17 + pgvector)
├── memoria_vectorial (814 records) ← Technical knowledge
│   ├── contenido (text), metadatos (jsonb), embedding (vector 768d)
│   └── Indexes: HNSW (cosine), GIN trigram
├── memory_items (323 records) ← User profile
│   ├── memory_type → profile | event | decision
│   ├── summary, embedding (768d), extra (jsonb)
│   └── Indexes: HNSW (cosine), GIN trigram
├── memory_categories (10 categories)
├── category_items (M:N relationship)
└── resources (referenced URLs/files)
```

### SSC Pipeline (v3.7)

```
Query → TAG ROUTER (classifies profile/technical/mixed)
         ↓
Phase 2  PGVECTOR top-20 on both tables ← stops here if confidence ≥ 70%
         ↓
Phase 3  GIN TRIGRAM expansion if confidence < 70%
         ↓
Phase 4  ILIKE full scan if confidence < 40%
```

### Logarithmic Checkpointing

| Age | Granularity |
|-----|-------------|
| < 24h | Full detail (no compression) |
| 1-7 days | Top 3 items per project |
| 7-30 days | 200-char summary per project |
| 30-90 days | 100-char summary per week |
| > 90 days | Single checkpoint per project |

---

## Scripts

| Script | Purpose |
|--------|---------|
| `hipocampo_ssc_search.py` | SSC search — 4-phase progressive retrieval |
| `hipocampo_search.py` | BIRE v3.6 — unified search with lexical + vector fusion |
| `hipocampo_autotag.py` | Rule-based auto-tagging (17 tag + 16 category rules) |
| `hipocampo_checkpoint.py` | Logarithmic time-decay checkpoint compression |
| `hipocampo_backfill_vectorial.py` | Backfill missing embeddings |
| `hipocampo_calibrate.py` | Hybrid weight calibration (cross-validation) |
| `mm_brain_tool.py` | Dual persist (PostgreSQL + Freeplane XML) |

---

## MCP Server (v2)

The repo includes a **FastMCP** server with **4 tools** for reading and writing to the dual memory system. Connects via standard MCP protocol (stdio or SSE).

### Tools

| Tool | Args | Description |
|------|------|-------------|
| `search_hipocampo` | `query` | Search both memory stores (semantic + lexical) |
| `quick_hipocampo_search` | `query` | Short alias for `search_hipocampo` |
| `save_hipocampo` | `content`, `memory_type`, `code`, `categories` | Save to technical memory (`memoria_vectorial`) |
| `profile_hipocampo` | `summary`, `extra`, `categories` | Save personal profile data (`memory_items`) |

### Usage

```bash
# Start with stdio (default)
python3 scripts/hipocampo_mcp_server.py

# Start with SSE on port 8001
python3 scripts/hipocampo_mcp_server.py --sse 8001

# systemd service (auto-start)
cp scripts/hipocampo-mcp.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now hipocampo-mcp.service
```

### Integrate with any MCP client

Add to your `opencode.json`, `claude_desktop_config.json`, or equivalent:

```json
{
  "mcpServers": {
    "hipocampo": {
      "command": "python3",
      "args": ["/path/to/hipocampo_mcp_server.py"],
      "timeout": 120000
    }
  }
}
```

**Files:**
| File | Purpose |
|------|---------|
| `scripts/hipocampo_mcp_server.py` | FastMCP server with 4 tools (read + write) |
| `scripts/hipocampo-mcp.service` | systemd user service for auto-start |
| `docs/mcp-server-guide.md` | Full setup and configuration guide |

---

## Related Work

- *Memory Caching: RNNs with Growing Memory* (Google, 2025) — inspiration for SSC
- *Retrieval-Augmented Generation* (Lewis et al., 2020)
- pgvector — [hnsw vector search for PostgreSQL](https://github.com/pgvector/pgvector)
- Gemini Embeddings — [Google AI embeddings](https://ai.google.dev/gemini-api/docs/embeddings)

---

## License

MIT

---

## 🇪🇸 Versión en Español

# Hipocampo — Sistema de Memoria Dual con SSC (Sparse Selective Caching)

**Autor:** Alexander Carrasquel  
**Versión:** 3.7

Hipocampo es un sistema de **memoria dual** para agentes de IA que persiste conocimiento técnico y datos de perfil de usuario a través de sesiones. Usa PostgreSQL 17 con pgvector para búsqueda semántica e implementa **SSC (Sparse Selective Caching)**, un algoritmo progresivo de 4 fases inspirado en el paper *"Memory Caching: RNNs with Growing Memory"* (Google, 2025).

### Características principales

- **Arquitectura de memoria dual:** Separación de registros técnicos (`memoria_vectorial`) y perfil de usuario (`memory_items`), cada uno con embeddings 768d
- **Búsqueda SSC (v3.7):** 4 fases progresivas — Tag Router → pgvector Top-K → GIN Trigram → ILIKE Fallback
- **Checkpointing logarítmico:** Comprime memorias antiguas por escala temporal (detalle 24h → checkpoint único >90d)
- **Auto-Tagging:** Motor de reglas regex que asigna tags y categorías automáticamente
- **1,137 registros** con embeddings 768d unificados (814 MV + 323 MI) para búsqueda cross-sistema

### Inicio Rápido

```bash
git clone https://github.com/carrasquelalex1/hipocampo.git
cd hipocampo

# Buscar con SSC
python3 scripts/hipocampo_ssc_search.py "término de búsqueda"

# Buscar con BIRE
python3 scripts/hipocampo_search.py "término"

# Checkpoint (vista previa y ejecución)
python3 scripts/hipocampo_checkpoint.py --dry-run
python3 scripts/hipocampo_checkpoint.py --force
```

### Scripts

| Script | Propósito |
|--------|-----------|
| `hipocampo_ssc_search.py` | Búsqueda SSC — 4 fases progresivas |
| `hipocampo_search.py` | BIRE v3.6 — búsqueda unificada léxico + vectorial |
| `hipocampo_autotag.py` | Auto-tagging por reglas (17 tags + 16 categorías) |
| `hipocampo_checkpoint.py` | Compresión por decaimiento logarítmico |
| `hipocampo_backfill_vectorial.py` | Backfill de embeddings faltantes |
| `hipocampo_calibrate.py` | Calibración de pesos híbridos (validación cruzada) |
| `mm_brain_tool.py` | Persistencia dual (PostgreSQL + XML Freeplane) |
| `hipocampo_mcp_server.py` | Servidor MCP FastMCP — 4 tools (read + write) |

### Servidor MCP (ES)

El servidor MCP v2 expone 4 herramientas vía protocolo MCP estándar (stdio o SSE):

- **`search_hipocampo(query)`** — búsqueda semántica + léxica en ambas tablas
- **`quick_hipocampo_search(query)`** — alias rápido
- **`save_hipocampo(content, memory_type, code, categories)`** — guarda en `memoria_vectorial` con embedding automático
- **`profile_hipocampo(summary, extra, categories)`** — guarda perfil personal en `memory_items`

```bash
# Iniciar con SSE en puerto 8001
python3 scripts/hipocampo_mcp_server.py --sse 8001

# O como servicio systemd
systemctl --user enable --now hipocampo-mcp.service
```

Ver `docs/mcp-server-guide.md` para la guía de configuración del MCP server.  
Ver `docs/hipocampo_paper.md` para la documentación completa del algoritmo BIRE y la arquitectura.
