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

> **⚠️ Transport Note:** SSE transport is deprecated since MCP spec 2025-03-26.
> Hipocampo now uses **Streamable HTTP** (single endpoint `/mcp`) as the recommended remote transport.
> SSE (`/sse`) remains available for backward compatibility but will be removed in a future release.

## 🌐 MCP Server — Live on Hugging Face

Hipocampo runs as a **free MCP server** on Hugging Face Spaces. Connect from any MCP client:

```
URL: https://alexbell1-hipocampo-mcp.hf.space/mcp
```

```json
{
  "mcpServers": {
    "hipocampo": {
      "url": "https://alexbell1-hipocampo-mcp.hf.space/mcp"
    }
  }
}
```

**Embedding model:** `sentence-transformers/all-MiniLM-L6-v2` (384 dims) via **Hugging Face Inference API** (free, no credit card required).

---

**Hipocampo** is an advanced dual-memory persistence architecture designed for autonomous AI agents. By maintaining both technical knowledge and user profiling data across sessions, Hipocampo provides a reliable, stateful context that enables agents to learn, adapt, and scale efficiently. 

Built on top of **PostgreSQL 17** with `pgvector`, it introduces **Sparse Selective Caching (SSC)**—a progressive four-phase retrieval algorithm inspired by *"Memory Caching: RNNs with Growing Memory"* (Google, 2025).

---

## 🚀 Key Features

* **Dual-Memory Architecture**: Distinct storage layers for technical records (`memoria_vectorial`) and user profile data (`memory_items`), each utilizing 1024-dimensional embeddings.
* **Sparse Selective Caching (SSC)**: A state-of-the-art four-phase progressive retrieval pipeline that scales seamlessly: *Tag Router* → *pgvector Top-K* → *GIN Trigram* → *ILIKE Fallback*.
* **Logarithmic Checkpointing**: Intelligently compresses historical memories based on time decay, shrinking 24-hour granular details into unified 90-day checkpoints.
* **Automated Tagging Engine**: A robust, Regex-based rule engine that autonomously categorizes and tags records upon persistence.
* **Cross-System Vector Search**: Unified semantic search across over 1,100 records for deep cross-referencing.
* **Model Context Protocol (MCP)**: Native integration via a FastMCP server, exposing seamless read/write capabilities to modern MCP clients (e.g., Claude Desktop, OpenCode).

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
# Perform a search using the new SSC progressive retrieval algorithm
python3 scripts/hipocampo_ssc_search.py "query term"

# Perform a search using the legacy BIRE unified search
python3 scripts/hipocampo_search.py "query term"

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

### The SSC Pipeline (v3.7)

Sparse Selective Caching operates as a multi-tier fallback system to optimize both speed and accuracy:

1. **Phase 1: Tag Router** – Classifies the query intent (profile vs. technical) and dynamically assigns weights.
2. **Phase 2: PGVector Top-K** – Semantic search across both tables. Execution halts here if confidence ≥ 70%.
3. **Phase 3: GIN Trigram** – Lexical expansion via Trigram indexing if semantic confidence is < 70%.
4. **Phase 4: ILIKE Scan** – Final fallback full-table scan triggered only if confidence falls < 40%.

---

## 🔌 MCP Server Integration

Hipocampo includes a fully functional **FastMCP** server, allowing LLM agents to autonomously read and write memories. 

### Available MCP Tools

**Memory Operations:**
* `search_hipocampo(query)`: Unified semantic and lexical search (auto-records metrics).
* `quick_hipocampo_search(query)`: Shorthand alias for rapid queries.
* `save_hipocampo(content, memory_type, code, categories)`: Persist data into the technical memory store (`memoria_vectorial`).
* `profile_hipocampo(summary, extra, categories)`: Store personal or event-driven user data (`memory_items`).

**Self-Diagnosis & Auto-Repair (Fase 1):**
* `hipocampo_health()`: Full system health check (PostgreSQL, NVIDIA API, disk, extensions).
* `hipocampo_auto_repair()`: Automatically repairs detected issues (restart PostgreSQL, create missing tables).

**Performance Optimization (Fase 2):**
* `hipocampo_stats()`: Query performance metrics, latency analysis, and optimization recommendations.
* `hipocampo_tune()`: Auto-adjusts SSC thresholds and hybrid weights based on real usage data.

**Memory Maintenance (Fase 3):**
* `hipocampo_dedup(merge)`: Detects and merges duplicate memories (exact + semantic via cosine similarity).
* `hipocampo_checkpoint(dry_run)`: Logarithmic checkpointing to compress old memories.
* `hipocampo_maintenance()`: Full maintenance cycle (repair → dedup → checkpoint → tune).

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

# Hipocampo: Sistema de Memoria Dual con Caché Selectivo (SSC)

**Hipocampo** es una arquitectura avanzada de persistencia de memoria dual diseñada para agentes de Inteligencia Artificial. Al mantener tanto el conocimiento técnico como los datos del perfil del usuario entre sesiones, Hipocampo proporciona un contexto con estado confiable que permite a los agentes aprender, adaptarse y escalar eficientemente.

Construido sobre **PostgreSQL 17** y `pgvector`, introduce **Sparse Selective Caching (SSC)**: un algoritmo de recuperación progresiva de cuatro fases inspirado en *"Memory Caching: RNNs with Growing Memory"* (Google, 2025).

---

## 🚀 Características Principales

* **Arquitectura de Memoria Dual**: Capas de almacenamiento separadas para registros técnicos (`memoria_vectorial`) y datos de perfil (`memory_items`), ambas utilizando embeddings de 1024 dimensiones.
* **Sparse Selective Caching (SSC)**: Algoritmo progresivo que escala según la necesidad: *Enrutador de Tags* → *pgvector Top-K* → *Trigramas GIN* → *Escaneo ILIKE*.
* **Checkpointing Logarítmico**: Compresión inteligente basada en el decaimiento del tiempo, consolidando detalles granulares en un solo registro tras 90 días.
* **Auto-MeJORA MCP**: Autodiagnóstico (health check + auto-repair), optimización dinámica (stats + tune), y mantenimiento de memoria (dedup + checkpoint) — todo desde herramientas MCP.
* **Motor de Auto-Etiquetado**: Reglas basadas en expresiones regulares que categorizan la información de manera autónoma al momento de la persistencia.
* **Protocolo MCP (Model Context Protocol)**: Integración nativa mediante un servidor FastMCP con 11 herramientas, otorgando capacidades directas de lectura/escritura y mantenimiento a clientes MCP como Claude Desktop y OpenCode.

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
python3 scripts/hipocampo_ssc_search.py "término de búsqueda"
```

Para inicializar el servidor MCP:
```bash
python3 scripts/hipocampo_mcp_server.py
python3 scripts/hipocampo_mcp_server.py --http 8001   # Streamable HTTP (recomendado)
python3 scripts/hipocampo_mcp_server.py --sse 8001    # legacy (deprecado)
```

### Herramientas MCP Disponibles

**Operaciones de Memoria:**
* `search_hipocampo(consulta)`: Búsqueda semántica + léxica híbrida (auto-registra métricas).
* `quick_hipocampo_search(consulta)`: Alias rápido para búsquedas.
* `save_hipocampo(contenido, tipo, codigo, categorias)`: Guarda datos técnicos en `memoria_vectorial`.
* `profile_hipocampo(resumen, extra, categorias)`: Guarda datos de perfil en `memory_items`.

**Autodiagnóstico y Reparación (Fase 1):**
* `hipocampo_health()`: Health check completo (PostgreSQL, NVIDIA API, disco, extensiones).
* `hipocampo_auto_repair()`: Repara problemas automáticamente (reinicia PostgreSQL, crea tablas faltantes).

**Optimización de Rendimiento (Fase 2):**
* `hipocampo_stats()`: Métricas de rendimiento, latencia, y recomendaciones de optimización.
* `hipocampo_tune()`: Ajusta thresholds SSC y pesos híbridos según uso real.

**Mantenimiento de Memoria (Fase 3):**
* `hipocampo_dedup(fusionar)`: Detecta y fusiona memorias duplicadas (exactas + semánticas).
* `hipocampo_checkpoint(seco)`: Checkpointing logarítmico para comprimir memorias antiguas.
* `hipocampo_maintenance()`: Ciclo completo de mantenimiento (reparar → dedup → checkpoint → tune).

*Consulte los manuales en la carpeta `docs/` para información arquitectónica y configuraciones avanzadas.*

---

## ☕ Donaciones

Si este proyecto te es útil, considera apoyarlo:

[![PayPal](https://img.shields.io/badge/Donar-PayPal-00457C?style=for-the-badge&logo=paypal)](https://paypal.me/carrasquealex)

- **PayPal:** [paypal.me/carrasquealex](https://paypal.me/carrasquealex)
- **USDT (TRC-20):** (próximamente)
- Cada aporte ayuda a mantener vivo el proyecto 🧠✨
