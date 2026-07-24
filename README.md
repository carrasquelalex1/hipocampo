---
title: Hipocampo MCP
emoji: 🧠
colorFrom: blue
colorTo: purple
sdk: docker
pinned: false
---

<p align="center">
  <img src="assets/logo.png" alt="Hipocampo" width="180"/>
</p>

<h1 align="center">Hipocampo</h1>
<h3 align="center">Dual-Memory System with Sparse Selective Caching</h3>

<p align="center">
  Persistent memory for autonomous AI agents · PostgreSQL 17 + pgvector · Hybrid Search · MCP Server
</p>

[![Version](https://img.shields.io/badge/version-4.2-blue.svg)](https://github.com/carrasquelalex1/hipocampo)
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

## 💡 Why Prompt Compression?

Hipocampo already reduces context through SSC (selective retrieval). But even the top-5 most relevant memories can consume 500-2000+ tokens when concatenated — a significant portion of any LLM's context window.

**Hybrid compression** adds a second reduction layer:
- **Extractive phase**: Removes redundant sentences (filtering by keyword relevance to your query). Reduces generic text by 30-50% instantly, with no API calls.
- **LLM phase**: Summarizes technical/code content using the same NVIDIA NIM endpoint already used for embeddings. Preserves all code, variable names, and syntax while dropping explanatory verbosity.
- **Combined**: 20-50% token reduction with near-zero quality loss. A 1500-token memory block becomes 750-1200 tokens — that's real savings on every LLM call.

**Real impact**: If you call `compress_hipocampo` before every `search_hipocampo` → LLM round-trip, you save 200-800 tokens per interaction. At scale (hundreds of queries), this translates to meaningful cost reduction and faster responses.

## 🚀 Key Features

* **Dual-Memory Architecture**: Distinct storage layers for technical records (`memoria_vectorial`) and user profile data (`memory_items`), each utilizing 1024-dimensional embeddings.
* **BIRE v3.7 (default)**: Hybrid search engine combining NVIDIA embeddings (1024d), query expansion, GIN trigram, and composite scoring — used by all MCP tools.
* **SSC (experimental)**: Alternative four-phase progressive pipeline: *Tag Router* → *pgvector Top-K* → *GIN Trigram* → *ILIKE Fallback*.
* **Logarithmic Checkpointing**: Intelligently compresses historical memories based on time decay, shrinking 24-hour granular details into unified 90-day checkpoints.
* **Automated Tagging Engine**: A robust, Regex-based rule engine that autonomously categorizes and tags records upon persistence.
* **Cross-System Vector Search**: Unified semantic search across over 1,100 records for deep cross-referencing.
* **Hybrid Prompt Compression** (v4.0): Two-phase compression pipeline — extractive (sentence-level) for generic text and LLM summarization (via NVIDIA NIM) for technical/code content. Reduces prompt tokens by 20-50% while preserving critical information. Available as `compress_hipocampo` MCP tool.
* **Memory Graph** (v4.0): Directed graph of semantic relationships between memories. Link related records, navigate with BFS tree, find shortest paths. Available as `link_hipocampo`, `graph_hipocampo`, `path_hipocampo` MCP tools.
* **Memory Hierarchy with Trigger-Based Prevention** (v4.1): 🧠🧠 Three-level memory (episodic → semantic → automatic) inspired by human mnemonic consolidation. **NEW:** Tag memories with contextual triggers (`trigger:php`, `trigger:chartjs`, `trigger:tomcat`) — when the agent starts working in that context, it searches for matching `automatica` rules and reactivates past errors *before* making the same mistake. This mirrors the biological hippocampus: a partial cue (project + language) triggers full memory retrieval of the error and its solution. Automatic rules are permanent — never compressed, never deleted. `set_nivel_hipocampo(id, nivel)` + `consolidate_hipocampo` tools included.
* **Code Immune System — Regression Protection** (v4.2): 🛡️ Prevents agents from breaking code that was working. **3-step cycle:** (1) Snapshot functional state before editing, (2) Verify after editing, (3) If something broke → create a permanent `automatica` rule capturing the exact cause, symptom, and fix. Uses immune economy: pre-change snapshots are cheap `episodica` (auto-compressed if no damage), post-break rules are permanent `automatica`. Pre-loaded with fragile file catalog — header.php, conexion.php, utils.php, auth.php, etc. Agents search `trigger:regression trigger:<file>` before every edit to learn what other agents broke before.
* **Code RAG** (v4.0): Index project source code (PHP, JS, TS, Python, SQL) as semantic embeddings. Search with `search_code(query, language)` — returns real code snippets with file paths and line numbers, not just summaries.
* **Exponential Time Decay** (v4.0): `final_score = relevance × exp(-λ × days)` with λ=0.05 configurable and 20% floor. Recent knowledge naturally outranks old memories.
* **Session Memory & Auto-Summarization**: Session-isolated save/search. After 20+ saves, Hipocampo auto-generates a consolidated session summary in the background.
* **Proactive Context Preloading**: `preload_context(project_path)` extracts meaningful keywords from the project path, searches relevant memories, and returns a compressed summary — ideal for session start.
* **Context Budget Awareness**: `compress_hipocampo` auto-estimates token budget and adjusts k dynamically. `budget_ratio` parameter gives fine-grained control over output size.
* **Auto-Linking**: `save_hipocampo(..., auto_link=True)` auto-discovers semantically similar memories (>0.75 cosine) and creates `similar` edges in the memory graph.
* **HNSW Auto-Recovery**: `hipocampo_health()` checks the HNSW index on startup and auto-creates it if missing — no more manual `CREATE INDEX` commands.
* **Model Context Protocol (MCP)**: Native integration via a FastMCP server with 22+ tools, exposing seamless read/write capabilities to modern MCP clients (e.g., Claude Desktop, OpenCode).

---

## ⚡ Why PostgreSQL + pgvector (Not SQLite)?

You might wonder why Hipocampo uses PostgreSQL 17 with pgvector instead of a lighter stack like SQLite. The answer: **hybrid search requires more than vector similarity alone.**

Hipocampo's retrieval pipeline combines **pgvector (HNSW)** for semantic search, **pg_trgm (GIN)** for lexical expansion, and **ILIKE** for fallback — fused into a single weighted score. SQLite extensions like `sqlite-vec` offer vector search, but lack:
- **GIN trigram indexes** for fuzzy/partial matching
- **Full-text + vector hybrid fusion** in a single query
- **Production-grade HNSW indexing** with concurrent writes
- **pg_trgm-based query expansion** when embeddings alone are insufficient

With ~1,100+ records across two memory tables and growing, Hipocampo needs a database that scales without sacrificing retrieval quality. PostgreSQL + pgvector isn't "heavy" for the sake of it — it's the minimum viable stack to deliver the hybrid accuracy that BIRE and SSC require.

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

### 🧠 Context-Aware Error Prevention (NEW v4.1) — Proactive, not Reactive

Going beyond reactive learning, Hipocampo v4.1 introduces **trigger-based automatic rules** that fire *before* the agent writes a single line of code:

```
┌─ 1. DETECT CONTEXT ───────────────────────────────┐
│  Agent is about to edit a PHP file in SGV.pro:     │
│  File: analisis_visual.php                         │
│  Library: Chart.js                                 │
│  Language: PHP                                     │
└────────────────────┬───────────────────────────────┘
                     │
┌─ 2. SEARCH TRIGGERS ───▼───────────────────────────┐
│  search_hipocampo("trigger:sgv trigger:chartjs     │
│                     trigger:php trigger:json_encode")│
└────────────────────┬───────────────────────────────┘
                     │
┌─ 3. REACTIVATE RULES ─▼────────────────────────────┐
│  REGLA AUTOMÁTICA FOUND (score 31.0):              │
│  "NUNCA usar variables JS (C.red, C.primary)       │
│   dentro de <?= json_encode() ?> en PHP.            │
│   PHP las evalúa como constantes → Fatal Error."   │
│  Solución: usar literales #ef4444 / #408AEC        │
└────────────────────┬───────────────────────────────┘
                     │
┌─ 4. ACT WITH CONSTRAINT ─▼─────────────────────────┐
│  Agent generates code using color literals instead │
│  of JS variables. Error avoided BEFORE it happens. │
└────────────────────────────────────────────────────┘
```

**How to implement:**

```python
# 1. When saving an error, tag it with contextual triggers and elevate to automatica
save_hipocampo(
    content="NUNCA usar variables JS en json_encode() PHP. Usar literales de color.",
    memory_type="decision",
    categories=["trigger:sgv", "trigger:chartjs", "trigger:php", "trigger:json_encode"],
    nivel="automatica"
)

# 2. Before editing code in any project, search matching triggers
search_hipocampo("trigger:<project> trigger:<language> trigger:<tech>")

# 3. Automatic rules surface → agent applies them preventively
```

This mirrors the biological hippocampus: **a partial cue triggers full memory retrieval** — the brain doesn't wait for the error to happen before remembering it hurts.

### 🛡️ Regression Protection — Code Immune System (NEW v4.2)

Sometimes the agent breaks code that was working fine — not repeating an old error, but creating a new one. Hipocampo v4.2 implements a **3-step immune cycle** that mirrors how the body generates antibodies:

```
┌─ 1. SNAPSHOT ──────────────────────────────────┐
│  Before editing header.php, save what works:    │
│  "header.php depends on session_start().         │
│   Verify: open dashboard.php, must load OK."    │
│  Cost: episodica (cheap, auto-compressed)       │
└───────────────────┬─────────────────────────────┘
                    │
┌─ 2. VERIFY ───────▼─────────────────────────────┐
│  After editing, run the snapshot verification:  │
│  - Dashboard loads OK → no cost, snapshot fades │
│  - HTTP 500 on all pages → immune response!     │
└───────────────────┬─────────────────────────────┘
                    │
┌─ 3. IMMUNIZE ─────▼─────────────────────────────┐
│  Save permanent automatica rule:                │
│  "Editing header.php: removed session_start(),  │
│   broke 40+ pages. Fix: restore session_start() │
│   at top of file. NEVER touch this line."       │
│  Cost: automatica (permanent, never compressed) │
└─────────────────────────────────────────────────┘
```

**Fragile file catalog (pre-loaded):** header.php, conexion.php, utils.php, auth.php, db_connection.php — these files have cascading dependencies. One wrong edit breaks dozens of pages. Hipocampo ships with fragile file rules so agents know what to handle with care.

**Before every edit:** `search_hipocampo("trigger:regression trigger:<file> trigger:<project>")` — learn what other agents broke on this file before you touch it.

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

# Hybrid prompt compression (extractive + LLM)
python3 scripts/hipocampo_compress.py "your query" --k 5 --method hybrid
python3 scripts/hipocampo_compress.py "your query" --method extractive  # fastest, no API cost
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

### Available MCP Tools (22+ tools)

**Memory Operations:**
* `search_hipocampo(query, session_id?)`: Unified semantic and lexical search (auto-records metrics). Optionally filter by session.
* `quick_hipocampo_search(query)`: Shorthand alias for rapid queries.
* `preload_context(project_path, k=8)`: Extract keywords from project path, search relevant memories, return compressed summary. Ideal for session initialization.
* `compress_hipocampo(query, k=5, method="hybrid", budget_ratio=1.0, include_metadata=False)`: Search + hybrid compression with context budget awareness. Auto-estimates tokens and adjusts k dynamically. Three methods: `"hybrid"` (recommended), `"extractive"` (fastest, no API cost), `"llm"` (highest quality).
* `save_hipocampo(content, memory_type, code, categories, session_id?, force?, auto_link=False, nivel="episodica")`: Persist data into `memoria_vectorial`. Supports session isolation, auto-dedup, auto-linking, and hierarchical memory levels.
* `profile_hipocampo(summary, extra, categories)`: Store personal or event-driven user data (`memory_items`).

**Memory Graph (v4.0):**
* `link_hipocampo(source_id, target_id, relation_type, weight)`: Create a directed edge between two memories. Relation types: `related`, `follow_up`, `part_of`, `references`, `similar`, `chain`.
* `unlink_hipocampo(id / source+target+type)`: Remove edge(s) from the memory graph.
* `graph_hipocampo(node_id, depth=2)`: BFS tree traversal from a root node. Use `node_id=0` for an overview of all connected nodes and edge counts.
* `path_hipocampo(from_id, to_id, max_depth=5)`: Find the shortest BFS path between two memories.

**Code RAG (v4.0):**
* `index_project(project_path, force=False)`: Scan and index source code files as semantic embeddings. Incremental — only re-indexes changed files (by mtime). Supports PHP, JS, TS, Python, SQL, HTML, CSS, JSON, YAML.
* `search_code(query, k=5, language="")`: Vector search specifically in indexed code snippets. Returns real code with file paths, language, and line numbers.

**CRUD Operations:**
* `update_hipocampo(id, content?, memory_type?, code?, categories?)`: Update an existing memory. Regenerates embedding if content changes.
* `delete_hipocampo(id)`: Permanently delete a memory by ID.
* `set_nivel_hipocampo(id, nivel)`: Promote/demote a memory between hierarchical levels (`episodica`, `semantica`, `automatica`).
* `consolidate_hipocampo(min_age_days=7, dry_run=True)`: Migrate old episodic memories to semantic level with optional content compression.

**Self-Diagnosis & Auto-Repair:**
* `hipocampo_health()`: Full system health check (PostgreSQL, NVIDIA API, disk, extensions, HNSW index).
* `hipocampo_auto_repair()`: Automatically repairs detected issues (restart PostgreSQL, create missing tables, create HNSW index).

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

### Modular Architecture

DB connection, config loading, and embedding generation are centralized in the `hipocampo` package:

```
hipocampo/
├── __init__.py       # Package init (version 3.8)
└── db.py             # get_conn(), get_embedding(), load_config()
```

All scripts in `scripts/` import from `hipocampo.db` instead of duplicating the boilerplate. The MCP server also imports search/health/stats/dedup/checkpoint functions directly — no subprocess calls.

**Before:** Each MCP search spawned `subprocess.run()` → fork Python interpreter → re-import everything → connect DB → generate embedding → run query → parse stdout. That's ~200–500ms of process + serialization overhead alone.

**After:** Direct function call within the same process. The DB connection pool, OpenAI client, and modules are already cached. Overhead drops to microseconds.

For individual searches the difference is marginal (~200ms), but for `hipocampo_maintenance()` it previously ran **4 serial subprocess forks** — now it's one direct call per phase, saving ~1–2 seconds.

### Async & Connection Pool (v3.8)

The MCP server now runs all 16 tools as **async Python coroutines** in HTTP mode, and uses a **PostgreSQL connection pool** instead of creating a new connection per call:

**Before:**
- Each MCP tool opened a new TCP + SSL connection to PostgreSQL → `connect()` latency on every call
- Sync tools blocked uvicorn's event loop → one slow `search` froze the server for all concurrent clients
- In HTTP mode with concurrent requests: risk of `too many connections` on the database

**After:**
- `init_pool(minconn=1, maxconn=10)` creates a `ThreadedConnectionPool` at server startup — connections are reused across calls, handshake happens once
- All 16 tools are `async def` — blocking I/O (DB queries, NVIDIA API) runs in `asyncio.to_thread()`, freeing the event loop for other requests
- A thin `_PooledConnection` proxy transparently returns connections to the pool when `.close()` is called — zero caller-side changes

**Impact:** Concurrent requests no longer block each other; PostgreSQL connection overhead drops from ~10–50ms per call to near zero.

**Integration Tests:**
- 6 schema tests verify tool registration, annotations, parameters, and async signature — no database required, run in CI
- 3 live integration tests (marked `@pytest.mark.integration`) start the server in stdio mode and verify tools/list, resources/list, and a real search call
- 102 total tests, all passing

### Config Validation, Rate Limiting & Granular Errors (v3.8)

**Before:**
- Missing `NVIDIA_API_KEY` or `DB_HOST` → server started without errors, failed with cryptic `fe_sendauth` / `401` on the first query
- Any client could hammer the NVIDIA API (`$` per embedding) and the free-tier PostgreSQL — no limits at all
- Every error caught with `except Exception: logger.error("msg: %s", e)` — no traceback, impossible to tell if it was a DB, network, or validation failure

**After:**
- `validate_config()` runs at startup and logs clear warnings for each missing variable. `init_pool()` and `get_conn()` reject early with messages like *"PostgreSQL connection incomplete: DB_HOST, DB_USER not configured in .env"*
- Three sliding-window rate limiters protect the system: `embedding_limiter` (30/min — shields NVIDIA API cost), `tool_limiter` (60/min — shields PostgreSQL), `watch_limiter` (20/min). Clients get *"⏳ Too many requests. Limit: 30 per 60s. Wait 12s."*
- `_tool_err()` helper differentiates by exception type: `psycopg2.Error` → `logger.exception()` with full traceback, `ValueError` / `TypeError` → `logger.warning()` (client error), others → `logger.exception()`. `_fire_webhooks` catches `urllib.error.URLError` separately

**Impact:** Failures are caught before they reach the database, costs are capped, and logs are actionable — you know instantly if it's a misconfiguration, a network blip, or a code bug.

### Retry with Backoff, Consistent CLI & Pre-commit Hooks (v3.8)

**Before:**
- `get_embedding()` failed on the first NVIDIA API timeout or rate limit — no retry at all
- All 12 scripts used manual `sys.argv` parsing — no `--help`, no type validation, inconsistent interfaces
- No pre-commit hooks — easy to push code with lint errors or broken tests

**After:**
- `get_embedding()` uses `tenacity` with `wait_exponential(mult=1, min=1, max=30)`, 5 attempts, retrying only on `RateLimitError`/`APITimeoutError`/`APIConnectionError`/`InternalServerError`. No retry on `AuthenticationError` or `BadRequestError`. Each retry is logged at `warning` level
- All 12 scripts have `argparse` with `--help`, typed arguments, and consistent names: `hipocampo_mcp_server.py --http 8001`
- `.pre-commit-config.yaml` with ruff lint+format (pre-commit) and pytest (pre-push). `pyproject.toml` configures ruff with line-length 120

**Impact:** The server tolerates transient API failures without the client seeing errors. CLI is self-documenting. Every commit is verified before reaching GitHub — no more broken tests on `main`.

---

### Local Fixes, `compress_hipocampo` Tool, and symlink-based Structure (v3.9)

**Before:**
- Scripts in `scripts/` were independent copies of the repo — each `git pull` required manual sync, and new files like `hipocampo_compress.py` were missing
- Local scripts (user-owned) lived in the same `scripts/` directory — no separation from repo files
- The `hipocampo/` Python package was also a copy: `load_config()` looked for `.env` in `project_root/.env` instead of `~/.hipocampo/.env`, loading incorrect credentials (alex/hipocampo123)
- If NVIDIA NIM API returned transient HTTP errors (403, 429, timeout), `compress` operations failed with a generic exception
- The `query_stats` table existed in `esquema.sql` but was never auto-created — `hipocampo_health` reported `DEGRADED`
- 4 scripts called `register_vector(conn)` on the `_PooledConnection` from `get_conn()` — psycopg2 rejected it with `TypeError`, breaking all vector operations
- Integration tests sent raw JSON-RPC to FastMCP v1.27+ — missing the `initialize` handshake, failing with `Invalid request parameters`

**Now:**
- `~/.hipocampo/` is the canonical home: `repo/` (git clone), `~/.hipocampo/scripts/` → `repo/scripts/` (symlink), `~/.hipocampo/hipocampo/` → `repo/hipocampo/` (symlink). Local user scripts moved to `~/.hipocampo/local_scripts/`. `git pull` on `repo/` auto-updates everything
- `_find_env()` in `db.py` loads `.env` in deterministic order: `ENV_PATH` env var → `~/.hipocampo/.env` (explicit user config) → `project_root/.env` (Docker/Fly). No more wrong credentials
- `ensure_stats_table()` runs at module import time in the MCP server — `query_stats` table auto-created on start
- `hipocampo_compress.py` with explicit exception handling: `RateLimitError`, `APITimeoutError`, `APIConnectionError`, `APIStatusError` → immediate fallback to extractive compression. All other errors → fallback with distinct warning level
- `register_vector(conn)` removed from `hipocampo_search.py`, `hipocampo_checkpoint.py`, `hipocampo_calibrate.py`, `mm_brain_tool.py` — `get_conn()` already registers the vector adapter on the real connection
- Integration tests rewritten with `mcp[client]` SDK (`stdio_client` + `ClientSession` + `initialize()`) — proper MCP 2025-03-26 handshake
- 105 tests total, all passing

**Impact:** Zero-touch maintenance after `git pull`. Transient NVIDIA API errors degrade gracefully. Config loading is deterministic and secure. Vector operations work reliably. Tests follow the official MCP protocol.

---

## ☕ Support / Donaciones

If this project helps you, consider supporting its development:

[![PayPal](https://img.shields.io/badge/Donate-PayPal-00457C?style=for-the-badge&logo=paypal)](https://paypal.me/carrasquealex)
[![GitHub Sponsors](https://img.shields.io/badge/sponsor-30363D?style=for-the-badge&logo=GitHub-Sponsors)](https://github.com/sponsors/carrasquelalex1)

- **PayPal:** [paypal.me/carrasquealex](https://paypal.me/carrasquealex)
- **USDT (TRC-20):** (próximamente)
- Cada grano de arena ayuda a mantener el proyecto vivo 🧠✨

---

## ⚡ Performance Optimizations (v3.9)

Optimizations applied in July 2026 to address latency and threshold drift:

### Embedding Cache

`get_embedding()` now uses an **LRU cache (128 entries)** — repeated queries for identical text skip the NVIDIA API call entirely, saving ~450ms each. The OpenAI client is also reused across calls instead of being recreated.

### SSC Search Acceleration

- **`SSC_TOP_K`** reduced from 20 → 15: fewer vector results per table means faster vector search
- **`hnsw.ef_search = 20`**: lower HNSW breadth-of-search for approximate (faster) nearest neighbors (default was 40)
- **`CONFIANZA_ALTA`** lowered from 70 → 60: early exit from the SSC pipeline sooner when vector results are already good
- **Early exit**: if ≥3 results already exceed the minimum threshold, trigram and ILIKE phases are skipped entirely
- **`register_vector`** cached per connection to avoid redundant SQL introspection

### Threshold Reset & Sane Auto-Tune

- **`alpha`** reset from 0.6 → **0.5** (balanced 50% vector + 50% lexical), **`vectorial_confidence_min`** from 0.75 → **0.70**
- Auto-tune (`hipocampo_tune()`) now **capped**: alpha stays within 0.4–0.6, confidence within 0.5–0.75
- Auto-tune can now **decrease** alpha too (if scores are high enough, reduces vector bias)

### Health Check Improvements

- Reports **PostgreSQL version** and **pgvector version** for compatibility diagnostics
- Verifies `register_vector()` and detects the **pgvector/PG17 `indam` incompatibility** with a clear upgrade message

---

## 🧪 Testing

Hipocampo includes **105+ unit tests** covering all core logic and MCP integration:

| Test file | What it covers |
|-----------|---------------|
| `tests/test_search.py` | Query expansion (stem map + synonyms), score fusion with dynamic alpha, temporal decay (5%/week), result formatting |
| `tests/test_autotag.py` | All 17 tag rules, 16 category rules, memory_type auto-detection |
| `tests/test_dedup.py` | Cosine similarity (including 1024-dim vectors), exact and semantic duplicate detection logic |
| `tests/test_checkpoint.py` | Age scale classification, project grouping, summary generation |
| `tests/test_mcp_integration.py` | 6 schema tests (tool registration, annotations, params, async signature) + 3 live integration tests (stdio server, mcp[client] SDK) |
| `tests/test_rate_limit.py` | Sliding-window rate limiter: acquire/release, prune, stats, default limiters |
| `tests/test_db.py` | Config validation: missing DB_HOST, NVIDIA_API_KEY, comprehensive coverage |

```bash
# Run all tests
python3 -m pytest tests/ -v

# Run with coverage
python3 -m pytest tests/ --cov=scripts --cov-report=term-missing
```

Tests run automatically on every push via [GitHub Actions](.github/workflows/test.yml) on Python 3.11–3.13.

## 📄 License

This project is licensed under the **MIT License**.

---

## 🇪🇸 Versión en Español

<p align="center">
  <img src="assets/logo.png" alt="Hipocampo" width="160"/>
</p>

<h1 align="center">Hipocampo</h1>
<h3 align="center">Sistema de Memoria Dual con Caché Selectivo (CS)</h3>

<p align="center">
  Memoria persistente para agentes de IA autónomos · PostgreSQL 17 + pgvector · Búsqueda Híbrida · Servidor MCP
</p>

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

## 💡 ¿Por qué Compresión de Prompts?

Hipocampo ya reduce el contexto mediante SSC (búsqueda selectiva). Pero incluso las 5 memorias más relevantes pueden consumir 500-2000+ tokens al concatenarse — una porción significativa de la ventana de contexto del LLM.

**La compresión híbrida** añade una segunda capa de reducción:
- **Fase extractiva**: Elimina oraciones redundantes (filtrando por relevancia de keywords a la consulta). Reduce texto genérico entre 30-50% al instante, sin llamadas API.
- **Fase LLM**: Resume contenido técnico/código usando el mismo endpoint NVIDIA NIM ya configurado para embeddings. Preserva todo el código, nombres de variables y sintaxis, eliminando verbosidad explicativa.
- **Combinado**: 20-50% de reducción de tokens con pérdida de calidad casi nula. Un bloque de memoria de 1500 tokens se convierte en 750-1200 tokens — ahorro real en cada llamada al LLM.

**Impacto real**: Si usas `compress_hipocampo` antes de cada `search_hipocampo` → LLM, ahorras 200-800 tokens por interacción. A escala (cientos de consultas), esto se traduce en reducción significativa de costos y respuestas más rápidas.

## 🚀 Características Principales

* **Arquitectura de Memoria Dual**: Capas de almacenamiento separadas para registros técnicos (`memoria_vectorial`) y datos de perfil (`memory_items`), ambas utilizando embeddings de 1024 dimensiones.
* **BIRE v3.7 (por defecto)**: Búsqueda híbrida con embeddings NVIDIA (1024d), expansión de consulta, GIN trigram y puntuación compuesta — usado por todas las tools MCP.
* **Caché Selectivo (CS/SSC, experimental)**: Pipeline alternativo de 4 fases: *Tag Router* → *pgvector Top-K* → *GIN Trigram* → *ILIKE Fallback*.
* **Checkpointing Logarítmico**: Compresión inteligente basada en el decaimiento del tiempo, consolidando detalles granulares en un solo registro tras 90 días.
* **Auto-MeJORA MCP**: Autodiagnóstico (health check + auto-repair), optimización dinámica (stats + tune), y mantenimiento de memoria (dedup + checkpoint) — todo desde herramientas MCP.
* **Compresión Híbrida de Prompts** (v4.0): Pipeline de dos fases — compresión extractiva (nivel de oraciones) para texto genérico y resumen LLM (vía NVIDIA NIM) para contenido técnico/código. Reduce tokens del prompt entre 20-50% preservando información crítica. Disponible como herramienta MCP `compress_hipocampo`.
* **Grafo de Memoria** (v4.0): Grafo dirigido de relaciones semánticas entre recuerdos. Enlaza registros relacionados, navega con árbol BFS, encuentra caminos más cortos. Tools: `link_hipocampo`, `graph_hipocampo`, `path_hipocampo`.
* **Jerarquía de Memoria con Prevención por Disparadores** (v4.1): 🧠🧠 Tres niveles (episódica → semántica → automática) inspirado en consolidación mnémica humana. **NOVEDAD:** Etiqueta recuerdos con disparadores contextuales (`trigger:php`, `trigger:chartjs`, `trigger:tomcat`) — cuando el agente comienza a trabajar en ese contexto, busca reglas `automatica` coincidentes y reactiva errores pasados *antes* de cometer el mismo error. Esto replica el hipocampo biológico: una pista parcial (proyecto + lenguaje) dispara la recuperación completa del error y su solución. Las reglas automáticas son permanentes — nunca se comprimen, nunca se eliminan. Tools: `set_nivel_hipocampo(id, nivel)` + `consolidate_hipocampo`.
* **Sistema Inmunológico de Código — Protección contra Regresiones** (v4.2): 🛡️ Evita que los agentes rompan código que funcionaba. **Ciclo de 3 pasos:** (1) Snapshot del estado funcional antes de editar, (2) Verificar después de editar, (3) Si algo se rompió → crear regla `automatica` permanente que capture la causa exacta, el síntoma y la solución. Usa economía inmune: los snapshots pre-cambio son `episodica` baratos (se autocomprimen si no hubo daño), las reglas post-rotura son `automatica` permanentes. Precargado con catálogo de archivos frágiles — header.php, conexion.php, utils.php, auth.php, etc. El agente busca `trigger:regresion trigger:<archivo>` antes de cada edición para aprender lo que otros agentes rompieron antes.
* **RAG de Código** (v4.0): Indexa código fuente de proyectos (PHP, JS, TS, Python, SQL) como embeddings semánticos. Busca con `search_code(consulta, lenguaje)` — devuelve código real con ruta de archivo y números de línea.
* **Decaimiento Temporal Exponencial** (v4.0): `score_final = relevancia × exp(-λ × días)` con λ=0.05 configurable y piso 20%. El conocimiento reciente pesa naturalmente más.
* **Memoria por Sesión y Auto-resumen**: Búsqueda/guardado aislado por sesión. Cada 20 guardados, Hipocampo genera un resumen consolidado de fondo.
* **Precarga Proactiva de Contexto**: `preload_context(ruta_proyecto)` extrae keywords del proyecto, busca memorias relevantes y devuelve resumen comprimido. Ideal al inicio de sesión.
* **Presupuesto de Contexto Inteligente**: `compress_hipocampo` auto-estima tokens y ajusta k dinámicamente. `budget_ratio` da control fino sobre el tamaño de salida.
* **Auto-Enlace**: `save_hipocampo(..., auto_link=True)` descubre recuerdos semánticamente similares (>0.75 cosine) y crea aristas `similar` en el grafo.
* **Recuperación Automática de HNSW**: `hipocampo_health()` verifica el índice HNSW al arrancar y lo crea si falta — sin comandos `CREATE INDEX` manuales.
* **Protocolo MCP (Model Context Protocol)**: Integración nativa mediante servidor FastMCP con 22+ herramientas, otorgando capacidades directas de lectura/escritura y mantenimiento a clientes MCP como Claude Desktop y OpenCode.

---

## ⚡ ¿Por qué PostgreSQL + pgvector (y no SQLite)?

Quizás te preguntes por qué Hipocampo usa PostgreSQL 17 con pgvector en lugar de algo más ligero como SQLite. La respuesta: **la búsqueda híbrida necesita más que solo similitud vectorial.**

El pipeline de recuperación combina **pgvector (HNSW)** para búsqueda semántica, **pg_trgm (GIN)** para expansión léxica e **ILIKE** como fallback — todo fusionado en un solo score ponderado. Extensiones de SQLite como `sqlite-vec` ofrecen búsqueda vectorial, pero carecen de:
- **Índices GIN trigram** para coincidencias difusas/parciales
- **Fusión híbrida texto + vector** en una sola consulta
- **Indexación HNSW de nivel productivo** con escrituras concurrentes
- **Expansión por pg_trgm** cuando los embeddings no bastan

Con más de 1,100 registros en dos tablas de memoria y creciendo, Hipocampo necesita una base de datos que escale sin sacrificar calidad de recuperación. PostgreSQL + pgvector no es "pesado" por capricho — es el stack mínimo viable para la precisión híbrida que BIRE y SSC exigen.

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

### 🧠 Prevención de Errores por Disparadores Contextuales (NUEVO v4.1) — Proactivo, no Reactivo

Más allá del aprendizaje reactivo, Hipocampo v4.1 introduce **reglas automáticas con disparadores** que se activan *antes* de que el agente escriba una sola línea de código:

```
┌─ 1. DETECTAR CONTEXTO ───────────────────────────┐
│  El agente va a editar un archivo PHP en SGV.pro: │
│  Archivo: analisis_visual.php                     │
│  Librería: Chart.js                               │
│  Lenguaje: PHP                                    │
└───────────────────┬───────────────────────────────┘
                    │
┌─ 2. BUSCAR DISPARADORES ──▼───────────────────────┐
│  search_hipocampo("trigger:sgv trigger:chartjs    │
│                    trigger:php trigger:json_encode")│
└───────────────────┬───────────────────────────────┘
                    │
┌─ 3. REACTIVAR REGLAS ─▼───────────────────────────┐
│  REGLA AUTOMÁTICA ENCONTRADA (score 31.0):        │
│  "NUNCA usar variables JS (C.red, C.primary)      │
│   dentro de <?= json_encode() ?> en PHP.           │
│   PHP las evalúa como constantes → Fatal Error."  │
│  Solución: usar literales #ef4444 / #408AEC       │
└───────────────────┬───────────────────────────────┘
                    │
┌─ 4. ACTUAR CON RESTRICCIÓN ─▼─────────────────────┐
│  El agente genera código usando literales de      │
│  color. Error EVITADO antes de que ocurra.        │
└───────────────────────────────────────────────────┘
```

**Cómo implementarlo:**

```python
# 1. Al guardar un error, etiquetarlo con triggers contextuales y elevar a automatica
save_hipocampo(
    content="NUNCA usar variables JS en json_encode() PHP. Usar literales de color.",
    memory_type="decision",
    categories=["trigger:sgv", "trigger:chartjs", "trigger:php", "trigger:json_encode"],
    nivel="automatica"
)

# 2. Antes de editar código en cualquier proyecto, buscar disparadores coincidentes
search_hipocampo("trigger:<proyecto> trigger:<lenguaje> trigger:<tecnologia>")

# 3. Las reglas automáticas aparecen → el agente las aplica preventivamente
```

Esto replica el hipocampo biológico: **una pista parcial dispara la recuperación completa de la memoria** — el cerebro no espera a que ocurra el error para recordar que duele.

### 🛡️ Protección contra Regresiones — Sistema Inmunológico (NUEVO v4.2)

A veces el agente rompe código que funcionaba bien — no repite un error viejo, crea uno nuevo. Hipocampo v4.2 implementa un **ciclo inmune de 3 pasos** que replica cómo el cuerpo genera anticuerpos:

```
┌─ 1. SNAPSHOT ──────────────────────────────────┐
│  Antes de editar header.php, guardar qué sirve: │
│  "header.php depende de session_start().         │
│   Verificar: abrir dashboard.php, debe cargar." │
│  Costo: episodica (barato, se autocomprime)     │
└───────────────────┬─────────────────────────────┘
                    │
┌─ 2. VERIFICAR ────▼─────────────────────────────┐
│  Después de editar, verificar el snapshot:      │
│  - Dashboard carga OK → sin costo, se desvanece │
│  - HTTP 500 en todas las páginas → ¡respuesta!  │
└───────────────────┬─────────────────────────────┘
                    │
┌─ 3. INMUNIZAR ────▼─────────────────────────────┐
│  Guardar regla automatica permanente:           │
│  "Editar header.php: quité session_start(),     │
│   rompió 40+ páginas. Solución: restaurar        │
│   session_start() al inicio. NUNCA tocar esto." │
│  Costo: automatica (permanente, inmutable)      │
└─────────────────────────────────────────────────┘
```

**Catálogo de archivos frágiles (precargado):** header.php, conexion.php, utils.php, auth.php, db_connection.php — estos archivos tienen dependencias en cascada. Una sola edición incorrecta rompe decenas de páginas. Hipocampo incluye reglas de fragilidad para que los agentes sepan qué manejar con cuidado.

**Antes de cada edición:** `search_hipocampo("trigger:regresion trigger:<archivo> trigger:<proyecto>")` — aprende lo que otros agentes rompieron en este archivo antes de tocarlo.

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
python3 scripts/hipocampo_compress.py "término" --k 5           # Búsqueda + compresión híbrida
```

Para inicializar el servidor MCP:
```bash
python3 scripts/hipocampo_mcp_server.py
python3 scripts/hipocampo_mcp_server.py --http 8001   # Streamable HTTP (recomendado)
python3 scripts/hipocampo_mcp_server.py --sse 8001    # legacy (deprecado)
```

### Herramientas MCP Disponibles (22+ herramientas)

**Operaciones de Memoria:**
* `search_hipocampo(consulta, session_id?)`: Búsqueda semántica + léxica híbrida (auto-registra métricas). Filtro opcional por sesión.
* `quick_hipocampo_search(consulta)`: Alias rápido para búsquedas.
* `preload_context(ruta_proyecto, k=8)`: Extrae keywords del proyecto, busca memorias relevantes y devuelve resumen comprimido. Ideal para inicio de sesión.
* `compress_hipocampo(consulta, k=5, method="hybrid", budget_ratio=1.0, include_metadata=False)`: Búsqueda + compresión híbrida con presupuesto de contexto. Auto-estima tokens y ajusta k dinámicamente. Tres métodos: `"hybrid"` (recomendado), `"extractive"` (más rápido, sin costo API), `"llm"` (máxima calidad).
* `save_hipocampo(contenido, tipo, codigo, categorias, session_id?, force?, auto_link=False, nivel="episodica")`: Guarda datos técnicos en `memoria_vectorial`. Soporta auto-dedup, auto-enlace y niveles jerárquicos.
* `profile_hipocampo(resumen, extra, categorias)`: Guarda datos de perfil en `memory_items`.

**Grafo de Memoria (v4.0):**
* `link_hipocampo(origen, destino, tipo_relacion, peso)`: Crea enlace dirigido entre recuerdos. Tipos: `related`, `follow_up`, `part_of`, `references`, `similar`, `chain`.
* `unlink_hipocampo(id / origen+destino+tipo)`: Elimina enlaces del grafo.
* `graph_hipocampo(nodo_id, profundidad=2)`: Árbol BFS desde un nodo raíz. `nodo_id=0` muestra vista general.
* `path_hipocampo(origen, destino, max_depth=5)`: Camino más corto BFS entre dos recuerdos.

**RAG de Código (v4.0):**
* `index_project(ruta_proyecto, force=False)`: Indexa archivos de código como embeddings semánticos. Incremental — solo re-indexa archivos modificados. Soporta PHP, JS, TS, Python, SQL, HTML, CSS, JSON, YAML.
* `search_code(consulta, k=5, lenguaje="")`: Búsqueda vectorial en código indexado. Devuelve código real con ruta, lenguaje y líneas.

**Operaciones CRUD:**
* `update_hipocampo(id, contenido?, tipo?, codigo?, categorias?)`: Actualiza un recuerdo existente. Regenera embedding si cambia el contenido.
* `delete_hipocampo(id)`: Elimina un recuerdo permanentemente por ID.
* `set_nivel_hipocampo(id, nivel)`: Promueve/degrada un recuerdo entre niveles jerárquicos (`episodica`, `semantica`, `automatica`).
* `consolidate_hipocampo(dias_min=7, seco=True)`: Migra recuerdos episódicos antiguos a nivel semántico con compresión opcional.

**Autodiagnóstico y Reparación:**
* `hipocampo_health()`: Health check completo (PostgreSQL, API NVIDIA, disco, extensiones, índice HNSW).
* `hipocampo_auto_repair()`: Repara problemas automáticamente (crea tablas, índice HNSW, reinicia PostgreSQL).

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

### Arquitectura Modular

La conexión a BD, configuración y generación de embeddings están centralizadas en el paquete `hipocampo`:

```
hipocampo/
├── __init__.py       # Inicialización del paquete (v3.8)
└── db.py             # get_conn(), get_embedding(), load_config()
```

Todos los scripts en `scripts/` importan de `hipocampo.db` en lugar de duplicar el boilerplate. El servidor MCP importa las funciones de búsqueda/salud/estadísticas/dedup/checkpoint directamente — sin llamadas subprocess.

**Antes:** Cada búsqueda MCP ejecutaba `subprocess.run()` → fork del intérprete Python → re-importar todo → conectar DB → generar embedding → ejecutar query → parsear stdout. ~200–500ms solo de overhead de proceso y serialización.

**Ahora:** Llamada directa a función en el mismo proceso. La DB connection pool, OpenAI client y módulos ya están cacheados. El overhead se reduce a microsegundos.

Para búsquedas individuales la diferencia es marginal (~200ms), pero para `hipocampo_maintenance()` antes ejecutaba **4 forks subprocess en serie** — ahora es una llamada directa por fase, ahorrando ~1–2 segundos.

### Async & Connection Pool (v3.8)

El servidor MCP ahora ejecuta las 16 herramientas como **corutinas async** en modo HTTP, y usa un **pool de conexiones PostgreSQL** en lugar de crear una conexión nueva por cada llamada:

**Antes:**
- Cada herramienta abría una conexión TCP + SSL nueva a PostgreSQL → latencia de `connect()` en cada llamada
- Tools sincrónicas bloqueaban el event loop de uvicorn → una `search` lenta congelaba el servidor para todos los clientes concurrentes
- En modo HTTP con requests concurrentes: riesgo de `too many connections` en la BD

**Ahora:**
- `init_pool(minconn=1, maxconn=10)` crea un `ThreadedConnectionPool` al arrancar — las conexiones se reúsan, el handshake ocurre una sola vez
- Las 16 herramientas son `async def` — I/O bloqueante (queries BD, API NVIDIA) corre en `asyncio.to_thread()`, liberando el event loop para otras requests
- Un proxy `_PooledConnection` devuelve las conexiones al pool automáticamente al llamar `.close()` — sin cambios en el caller

**Impacto:** Requests concurrentes ya no se bloquean entre sí; el overhead de conexión PostgreSQL baja de ~10–50ms por llamada a casi cero.

**Tests de Integración:**
- 6 tests de schema verifican registro de herramientas, anotaciones, parámetros y firma async — sin BD, corren en CI
- 3 tests de integración en vivo (marcados `@pytest.mark.integration`) arrancan el servidor en modo stdio y verifican tools/list, resources/list y una búsqueda real
- 105 tests totales, todos pasando

### Validación de Config, Rate Limiting y Errores Granulares (v3.8)

**Antes:**
- `NVIDIA_API_KEY` o `DB_HOST` faltantes → el server arrancaba sin errores y fallaba con un críptico `fe_sendauth` / `401` recién en el primer query
- Cualquier cliente podía saturar la API de NVIDIA (`$` por embedding) y el PostgreSQL gratuito — sin ningún límite
- Todos los errores se capturaban con `except Exception: logger.error("msg: %s", e)` — sin traceback, imposible saber si era error de BD, red o validación

**Ahora:**
- `validate_config()` se ejecuta al arranque y logea warnings claros para cada variable faltante. `init_pool()` y `get_conn()` rechazan temprano con mensajes como *"PostgreSQL connection incomplete: DB_HOST, DB_USER no configurados en .env"*
- Tres rate limiters sliding-window protegen el sistema: `embedding_limiter` (30/min — protege el costo de la API NVIDIA), `tool_limiter` (60/min — protege PostgreSQL), `watch_limiter` (20/min). Los clientes reciben *"⏳ Demasiadas solicitudes. Límite: 30 por 60s. Espera 12s."*
- `_tool_err()` diferencia por tipo de excepción: `psycopg2.Error` → `logger.exception()` con traceback completo, `ValueError` / `TypeError` → `logger.warning()` (error del cliente), otros → `logger.exception()`. `_fire_webhooks` captura `urllib.error.URLError` por separado

**Impacto:** Los errores se detectan antes de llegar a la BD, los costos están limitados, y los logs son accionables — sabés al instante si es una mala configuración, un problema de red o un bug de código.

*Consulte los manuales en la carpeta `docs/` para información arquitectónica y configuraciones avanzadas.*

### Retry con Backoff, CLI Consistente y Pre-commit Hooks (v3.8)

**Antes:**
- `get_embedding()` fallaba al primer timeout o rate limit de la API de NVIDIA — sin reintentos
- Los 12 scripts usaban `sys.argv` manual — sin `--help`, sin validación de tipos, interfaces inconsistentes
- No había hooks de pre-commit — fácil pushear código con lint sucio o tests rotos

**Ahora:**
- `get_embedding()` usa `tenacity` con `wait_exponential(mult=1, min=1, max=30)`, 5 intentos, reintenta solo en `RateLimitError`/`APITimeoutError`/`APIConnectionError`/`InternalServerError`. No reintenta en `AuthenticationError` o `BadRequestError`. Cada reintento se loguea en nivel `warning`
- Los 12 scripts tienen `argparse` con `--help`, argumentos tipados y nombres consistentes: `hipocampo_mcp_server.py --http 8001`
- `.pre-commit-config.yaml` con ruff lint+format (pre-commit) y pytest (pre-push). `pyproject.toml` configura ruff con line-length 120

**Impacto:** El server tolera fallos transitorios de la API sin que el cliente vea errores. El CLI es autodocumentado. Cada commit se verifica antes de llegar a GitHub — no más tests rotos en `main`.

---

### Correcciones Locales, Tool `compress_hipocampo` y Estructura basada en Symlinks (v3.9)

**Antes:**
- Los scripts en `scripts/` eran copias independientes del repo — cada `git pull` requería sincronización manual, y archivos nuevos como `hipocampo_compress.py` no se propagaban
- Scripts locales (del usuario) convivían en el mismo `scripts/` — sin separación de archivos del repo
- El paquete `hipocampo/` era también copia: `load_config()` buscaba `.env` en `project_root/.env` en vez de `~/.hipocampo/.env`, cargando credenciales incorrectas (alex/hipocampo123)
- Si la API de NVIDIA NIM devolvía errores HTTP transitorios (403, 429, timeout), la compresión fallaba con excepción genérica
- La tabla `query_stats` existía en `esquema.sql` pero nunca se creaba automáticamente — `hipocampo_health` reportaba `DEGRADED`
- 4 scripts llamaban `register_vector(conn)` sobre el `_PooledConnection` devuelto por `get_conn()` — psycopg2 lo rechazaba con `TypeError`, rompiendo todas las operaciones vectoriales
- Los tests de integración enviaban JSON-RPC raw a FastMCP v1.27+ — sin el handshake `initialize`, fallaban con `Invalid request parameters`

**Ahora:**
- `~/.hipocampo/` es el directorio canónico: `repo/` (clon git), `~/.hipocampo/scripts/` → `repo/scripts/` (symlink), `~/.hipocampo/hipocampo/` → `repo/hipocampo/` (symlink). Scripts locales del usuario movidos a `~/.hipocampo/local_scripts/`. `git pull` en `repo/` actualiza todo automáticamente
- `_find_env()` en `db.py` carga `.env` en orden determinista: `ENV_PATH` → `~/.hipocampo/.env` (config explícita del usuario) → `project_root/.env` (Docker/Fly). Sin más credenciales incorrectas
- `ensure_stats_table()` se ejecuta al importar el módulo del MCP server — la tabla `query_stats` se crea automáticamente al iniciar
- `hipocampo_compress.py` con manejo explícito de excepciones: `RateLimitError`, `APITimeoutError`, `APIConnectionError`, `APIStatusError` → fallback inmediato a compresión extractiva. Otros errores → fallback con log de advertencia diferenciado
- `register_vector(conn)` eliminado de `hipocampo_search.py`, `hipocampo_checkpoint.py`, `hipocampo_calibrate.py`, `mm_brain_tool.py` — `get_conn()` ya registra el adaptador vectorial sobre la conexión real
- Tests de integración reescritos con el SDK `mcp[client]` (`stdio_client` + `ClientSession` + `initialize()`) — handshake MCP 2025-03-26 correcto
- 105 tests totales, todos pasando

**Impacto:** Mantenimiento cero tras `git pull`. Errores transitorios de NVIDIA API degradan gracefulmente. Carga de configuración determinista y segura. Operaciones vectoriales confiables. Tests siguen el protocolo MCP oficial.

---

## ⚡ Optimizaciones de Rendimiento (v3.9)

Optimizaciones aplicadas en Julio 2026 para reducir latencia y estabilizar thresholds:

### Caché de Embeddings

`get_embedding()` ahora usa un **caché LRU (128 entradas)** — consultas repetidas con el mismo texto saltan la llamada a la API de NVIDIA, ahorrando ~450ms cada una. El cliente de OpenAI también se reutiliza entre llamadas.

### Aceleración de Búsqueda SSC

- **`SSC_TOP_K`** reducido de 20 → 15: menos resultados vectoriales por tabla = búsqueda más rápida
- **`hnsw.ef_search = 20`**: menor amplitud de búsqueda HNSW para vecinos aproximados más rápidos (default era 40)
- **`CONFIANZA_ALTA`** bajada de 70 → 60: salida temprana del pipeline SSC cuando los resultados vectoriales ya son buenos
- **Early exit**: si ya hay ≥3 resultados sobre el umbral mínimo, se saltan las fases trigram e ILIKE
- **`register_vector`** cacheado por conexión para evitar introspección SQL redundante

### Reset de Thresholds y Auto-Tune Controlado

- **`alpha`** reseteado de 0.6 → **0.5** (balanceado 50% vectorial + 50% léxico), **`vectorial_confidence_min`** de 0.75 → **0.70**
- Auto-tune (`hipocampo_tune()`) ahora **limitado**: alpha se mantiene entre 0.4–0.6, confidence entre 0.5–0.75
- Auto-tune ahora también puede **disminuir** alpha (si los scores son altos, reduce el sesgo vectorial)

### Mejoras en Health Check

- Reporta **versión de PostgreSQL** y **versión de pgvector** para diagnóstico de compatibilidad
- Verifica `register_vector()` y detecta la **incompatibilidad pgvector/PG17 (`indam`)** con un mensaje claro de actualización

---

## 🧪 Tests

Hipocampo incluye **105+ tests unitarios** cubriendo toda la lógica central e integración MCP:

| Archivo | Qué cubre |
|---------|-----------|
| `tests/test_search.py` | Expansión de consulta (stem map + sinónimos), fusión de scores con alpha dinámico, decaimiento temporal (5%/semana), formateo de resultados |
| `tests/test_autotag.py` | Las 17 reglas de tags, 16 reglas de categoría, detección automática de memory_type |
| `tests/test_dedup.py` | Similitud coseno (vectores de 1024 dim), lógica de detección de duplicados exactos y semánticos |
| `tests/test_checkpoint.py` | Clasificación por escalas de edad, agrupación por proyecto, generación de resúmenes |
| `tests/test_mcp_integration.py` | 6 tests de schema (registro de tools, anotaciones, parámetros, firma async) + 3 tests de integración en vivo (servidor stdio, mcp[client] SDK) |
| `tests/test_rate_limit.py` | Rate limiter sliding-window: acquire/release, prune, stats, limiters por defecto |
| `tests/test_db.py` | Validación de config: DB_HOST faltante, NVIDIA_API_KEY faltante, cobertura completa |

```bash
# Ejecutar todos los tests
python3 -m pytest tests/ -v

# Con cobertura
python3 -m pytest tests/ --cov=scripts --cov-report=term-missing
```

Los tests se ejecutan automáticamente en cada push vía [GitHub Actions](.github/workflows/test.yml) en Python 3.11–3.13.

---

## ☕ Donaciones

Si este proyecto te es útil, considera apoyarlo:

[![PayPal](https://img.shields.io/badge/Donar-PayPal-00457C?style=for-the-badge&logo=paypal)](https://paypal.me/carrasquealex)

- **PayPal:** [paypal.me/carrasquealex](https://paypal.me/carrasquealex)
- **USDT (TRC-20):** (próximamente)
- Cada aporte ayuda a mantener vivo el proyecto 🧠✨
