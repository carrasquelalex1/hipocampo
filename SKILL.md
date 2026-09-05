---
name: hipocampo-protocol
description: Protocolo de memoria dual con Sparse Selective Caching (SSC) v4.0 + Memory Graph + Compresión Híbrida. Persiste en memoria_vectorial y memory_items con búsqueda semántica progresiva. Cargar al inicio de cada sesión.
---

# Hipocampo Protocol v4.0 — SSC + Memory Graph + Compresión Híbrida

Sistema de memoria externa persistente con **Sparse Selective Caching** (inspirado en "Memory Caching: RNNs with Growing Memory", Google 2025).

Repo: `https://github.com/carrasquelalex1/hipocampo`
MCP Server live: `https://alexbell1-hipocampo-mcp.hf.space/mcp` (Streamable HTTP)

---

## 📚 Estructura

```
hipocampo_db (PostgreSQL 17 + pgvector + pg_trgm + memory_links)
├── 🧠 memoria_vectorial (~830 registros, embedding 1024d)
│   └── contenido, metadatos (jsonb), embedding HNSW (cosine), code_snippet
├── 🤖 memory_items (~250 registros, embedding 1024d)
│   └── memory_type (profile|event|decision), summary, extra, categories
├── 🔗 memory_links — grafo dirigido entre recuerdos (source → target, tipo, peso)
├── 🏷️ memory_categories
├── 🔗 category_items (M:N)
├── 📎 query_stats — métricas de rendimiento de búsqueda
└── 📎 watches — webhooks para eventos de memoria
```

Embeddings: **1024d** (Ollama `qwen3-embedding:0.6b` local por defecto; NVIDIA NIM como fallback).

---

## 🔍 Fase 1: Pre-actuación — Buscar con SSC v4.0

Usar las tools MCP `search_hipocampo()` o `quick_hipocampo_search()`:

### Pipeline SSC (4 fases, escala progresiva)
```
Fase 1 TAG ROUTER  → clasifica consulta (perfil/técnico/mixto), pesos dinámicos
Fase 2 PGVECTOR    → top-20 semántico en AMBAS tablas ← 70%+ confianza: para aquí
Fase 3 TRIGRAM     → expande con GIN si confianza < 70%
Fase 4 ILIKE       → full scan solo si confianza < 40%
```

### Decaimiento temporal exponencial
```math
score_final = score_bruto × max(0.20, e^{-λ × días})
```
- λ = 0.05 configurable en configuración
- Floor 20%: ningún recuerdo pierde más del 80% de su score por edad
- Auto-ajuste de thresholds vía `hipocampo_tune()`

NO usar `ILIKE '%...%' LIMIT 20` directamente.

---

## ⚙️ Fase 2: Persistencia — Herramientas MCP v4.0

### Búsqueda y Recuperación
| Tool | Descripción |
|---|---|
| `search_hipocampo(query, session_id)` | Búsqueda semántica + léxica híbrida con BIRE + SSC |
| `quick_hipocampo_search(query, session_id)` | Alias corto de search_hipocampo |
| `preload_context(project_path, k)` | Extrae keywords del path, busca y comprime contexto relevante del proyecto |
| `compress_hipocampo(query, k, method, budget_ratio)` | Compresión híbrida (extractiva + LLM) de memorias; auto-estima tokens según budget |

### Guardado y Perfil
| Tool | Descripción |
|---|---|
| `save_hipocampo(content, memory_type, code, categories, session_id, force, auto_link)` | Guardar en memoria_vectorial. `auto_link=True` enlaza automáticamente con recuerdos similares |
| `profile_hipocampo(summary, extra, categories)` | Guardar perfil personal en memory_items |
| `update_hipocampo(id, content, memory_type, code, categories)` | Actualizar recuerdo existente |
| `delete_hipocampo(id)` | Eliminar recuerdo |

### Memory Graph (v4.0 Phase 3)
| Tool | Descripción |
|---|---|
| `link_hipocampo(source_id, target_id, relation_type, weight)` | Crea enlace dirigido (related, follow_up, part_of, references, similar, chain) |
| `unlink_hipocampo(id / source+target+type)` | Elimina enlace(s) del grafo |
| `graph_hipocampo(node_id, depth)` | Árbol ASCII BFS desde un nodo; vista general con node_id=0 |
| `path_hipocampo(from_id, to_id, max_depth)` | Camino más corto BFS entre dos recuerdos |

### Webhooks
| Tool | Descripción |
|---|---|
| `watch_hipocampo(pattern, webhook_url)` | Registra webhook que se dispara al crear/modificar/eliminar recuerdos |
| `unwatch_hipocampo(id)` | Elimina webhook |
| `list_watches()` | Lista todos los webhooks registrados |

---

## 🕒 Fase 3: Mantenimiento (Auto-Mejora MCP)

El servidor MCP expone 7 herramientas de auto-mantenimiento:

### Autodiagnóstico y Reparación
- `hipocampo_health()` — Health check completo (PostgreSQL, API, disco, extensiones, índice HNSW)
- `hipocampo_auto_repair()` — Repara problemas automáticamente (incluye creación de índice HNSW si falta)

### Optimización de Rendimiento
- `hipocampo_stats()` — Métricas de latencia, SCORE promedio, recomendaciones
- `hipocampo_tune()` — Ajusta thresholds SSC y pesos híbridos según uso real

### Mantenimiento de Memoria
- `hipocampo_dedup(merge)` — Detecta y fusiona duplicados (exactos + semánticos por cosine)
- `hipocampo_checkpoint(dry_run)` — Checkpointing logarítmico con auto-ejecución al iniciar
- `hipocampo_maintenance()` — Ciclo completo: repair → dedup → checkpoint → tune

### Compresión de Contexto
| Parámetro | Descripción |
|---|---|
| `budget_ratio` | Escala el target de tokens auto-estimado (0.5 = mitad del presupuesto, 2.0 = doble) |
| `target_token=-1` | Auto-estima: 30% del contenido total, min 200, max 2000 |
| `method=hybrid` | Usa LLM para contenido técnico, extractiva para genérico |

### Auto-summarización de Sesiones
Cada 20 saves en una misma sesión, se consolida automáticamente un resumen en segundo plano.

---

## 🧠 Fase 4: Memory Graph — Grafo de Memoria

Los recuerdos en Hipocampo pueden relacionarse entre sí formando un **grafo dirigido** navegable.

### Tipos de relación
| Tipo | Uso |
|---|---|
| `related` | Relación semántica genérica (default) |
| `follow_up` | El origen es continuación/secuela del destino |
| `part_of` | El origen es parte del destino (jerarquía) |
| `references` | El origen referencia al destino |
| `similar` | Semánticamente similar (auto-asignado por auto_link) |
| `chain` | Parte de una cadena de contexto |

### Auto-linking
Al guardar con `auto_link=True`, el sistema busca los 3 recuerdos más similares (>0.75 cosine) y crea enlaces `similar` automáticamente.

### Ejemplo de uso
```python
# Crear enlace manual
link_hipocampo(source_id=1106, target_id=1105, relation_type="follow_up", weight=0.9)

# Explorar grafo desde un nodo
graph_hipocampo(node_id=1106, depth=3)

# Encontrar camino entre dos recuerdos
path_hipocampo(from_id=1000, to_id=1106, max_depth=5)

# Guardar con auto-linking
save_hipocampo("Nueva memoria", auto_link=True)
```

---

## 🧬 Fase 5: Jerarquía de Memoria — Reglas Automáticas (Nivel 3)

Los recuerdos en Hipocampo tienen 3 niveles jerárquicos que replican la consolidación de memoria biológica: desde el detalle frágil (episódica) hasta el reflejo permanente (automática).

### Niveles

| Nivel | Comportamiento | Cuándo usar |
|---|---|---|
| `episodica` (default) | Detalle completo, comprimible por checkpoint | Eventos cotidianos, decisiones, aprendizajes |
| `semantica` | Conocimiento consolidado, protegido de checkpoint | Lecciones confirmadas, reglas estables |
| `automatica` | Regla permanente, **nunca** se comprime ni elimina | Errores críticos, patrones de seguridad, invariantes |

### Flujo de consolidación

```
episodica ──(consolidate, min_age_days)──→ semantica ──(set_nivel)──→ automatica
     ↑                                         ↑                         ↑
   frágil,                                  protegida,               permanente,
comprimible                              checkpoint-safe           inmutable
```

### Mecanismo de disparo preventivo (triggers)

Las reglas `automatica` usan **categorías trigger** para reactivarse por contexto. Antes de editar código en un proyecto, buscar con la combinación de triggers que apliquen:

```
search_hipocampo("trigger:<proyecto> trigger:<lenguaje> trigger:<tecnologia>")
```

El sistema replica el mecanismo del hipocampo biológico: una pista parcial del contexto actual dispara la recuperación de memorias de error relevantes **antes** de actuar, no después.

### Catálogo de triggers estándar

| Trigger | Contexto de disparo |
|---|---|
| `trigger:<proyecto>` | Al trabajar en un proyecto específico (ej. `trigger:sgv`) |
| `trigger:php`, `trigger:javascript`, `trigger:python`, `trigger:bash` | Lenguaje del archivo a editar |
| `trigger:chartjs`, `trigger:tomcat`, `trigger:json_encode` | Biblioteca o tecnología |
| `trigger:csv`, `trigger:deploy`, `trigger:edit`, `trigger:audit` | Tipo de operación |
| `trigger:password`, `trigger:hash`, `trigger:seguridad` | Contexto de seguridad |
| `trigger:frontend`, `trigger:dom`, `trigger:css` | Auditoría de frontend |

### Ejemplo de flujo completo

```python
# 1. Guardar un error como regla automática con triggers
save_hipocampo(
    content="NUNCA usar variables JS dentro de <?= json_encode() ?> en PHP. Usar literales.",
    memory_type="decision",
    categories=["trigger:sgv", "trigger:chartjs", "trigger:php", "trigger:json_encode"],
    nivel="automatica"
)

# 2. Días después, al editar un gráfico en el mismo proyecto, buscar triggers
search_hipocampo("trigger:sgv trigger:chartjs trigger:php")

# 3. La regla automática aparece en los resultados → el agente la aplica preventivamente
```

### Tools de jerarquía

| Tool | Descripción |
|---|---|
| `set_nivel_hipocampo(id, nivel)` | Cambia el nivel de un recuerdo: `episodica`, `semantica`, `automatica` |
| `consolidate_hipocampo(min_age_days, dry_run)` | Migra recuerdos episódicos antiguos a semánticos |

> **Importante**: El nivel `automatica` es irreversible por diseño. Una regla automática es un reflejo condicionado — no se comprime con checkpoint, no se fusiona en dedup, no se elimina con consolidate. Usar con criterio.

---

## 🛡️ Fase 6: Sistema Inmunológico — Protección contra Regresiones (v4.2)

Las reglas automáticas previenen errores YA cometidos. Pero un agente también puede romper algo que funcionaba perfectamente — un error NUEVO, sin registro previo. Esta fase implementa un **sistema inmunológico de código**: detecta la rotura en el momento en que ocurre y genera inmunidad permanente para el futuro.

### Ciclo de 3 pasos

**Paso 1 — Snapshot pre-cambio.** Antes de editar un archivo, guardar un snapshot de lo que funciona:
```python
save_hipocampo(
    "PRE-CHANGE SNAPSHOT: header.php en SGV.pro.
     Dependencias críticas: sesión PHP, conexión PDO, 40+ archivos include.
     Verificación: abrir dashboard.php, confirmar que carga sin error 500.",
    categories=["snapshot", "trigger:sgv", "trigger:regresion", "trigger:header"],
    nivel="episodica"  # barato — se comprime si no hubo problema
)
```

**Paso 2 — Post-cambio: verificar.** Después de editar, ejecutar las verificaciones del snapshot:
- Si todo OK → el snapshot episódico se comprimirá solo con checkpoint
- Si algo se rompió → paso 3

**Paso 3 — Inmunizar.** Crear regla automática que capture causa-efecto:
```python
save_hipocampo(
    "REGLA INMUNOLÓGICA: Editar header.php en SGV.pro rompió dashboard.
     Causa: se eliminó session_start() accidentalmente.
     Síntoma: HTTP 500 en todas las páginas, 'session already started' en log.
     Solución: restaurar session_start() al inicio del archivo.",
    categories=["trigger:sgv","trigger:regresion","trigger:header","trigger:session"],
    nivel="automatica"  # permanente — nunca se comprime
)
```

### Principio de economía inmune

| Momento | Costo | Nivel |
|---------|-------|-------|
| Pre-cambio (snapshot) | Barato | `episodica` — se comprime si no hubo problema |
| Post-rotura (regla) | Caro | `automatica` — permanente, inmutable |

El sistema solo paga el costo de la memoria cuando realmente ocurrió un daño — igual que el sistema inmunológico biológico: genera anticuerpos solo después de exponerse al patógeno.

### Archivos frágiles pre-cargados

| Archivo | Qué rompe si se edita mal |
|---------|--------------------------|
| `header.php` | Sesiones, conexión PDO, decenas de dependientes |
| `conexion.php` | Toda la capa de datos del proyecto |
| `utils.php` | Funciones compartidas (CSRF, geografía, fechas) |
| `auth.php` | Login, roles, permisos en todo el sistema |
| `db_connection.php` | Stack completo si cambian credenciales |

### Cómo usar con triggers

Antes de cualquier edición, buscar regresiones previas en ese archivo:
```
search_hipocampo("trigger:regresion trigger:<archivo> trigger:<proyecto>")
```

Si existe una regla inmunológica para ese archivo, aparecerá en los resultados y el agente sabrá exactamente qué no debe tocar.

---

## 🌐 Servidor MCP — Conexión

### Local (Streamable HTTP, recomendado)
```bash
python3 /home/alex/.hipocampo/scripts/hipocampo_mcp_server.py --http 8001
```

### Local (stdio, para clientes desktop)
```bash
python3 /home/alex/.hipocampo/scripts/hipocampo_mcp_server.py
```

### Remoto (Hugging Face Spaces — gratis, sin API key)
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

> **⚠️ SSE** está deprecado desde MCP spec 2025-03-26. Usar Streamable HTTP.

### Systemd (servicio persistente)
```bash
systemctl --user status hipocampo-mcp.service
systemctl --user restart hipocampo-mcp.service
journalctl --user -u hipocampo-mcp.service -n 50
```

---

## ✅ Reglas Críticas

1. **Familia** → `memory_type='profile'`, categoría `relationships`. NUNCA `event`.
2. **Auto-tagging** obligatorio en todo `memory_items` nuevo.
3. **SSC preferido sobre ILIKE** para búsquedas. No usar psql ILIKE directo.
4. **memory_items** es solo lectura vía MCP (no inserts directos).
5. **PostgreSQL** usa socket Unix (`/var/run/postgresql`), usuario `alex`, sin contraseña.
6. **Embeddings**: 1024d vía Ollama local (por defecto) o NVIDIA NIM.
7. **API Keys**: `NVIDIA_API_KEY` solo si se usa NIM; con Ollama local no hace falta.
8. **Dedup automático**: al guardar, si existe recuerdo con similitud >0.9 se bloquea (excepto con `force=True`).
9. **Auto-checkpoint**: se ejecuta al iniciar el servidor MCP.
10. **HNSW index**: si falta en health check, se auto-crea.

---

## 📂 Scripts del Repo

Clonar para acceso local:
```bash
git clone https://github.com/carrasquelalex1/hipocampo.git /tmp/opencode/hipocampo
```

| Script | Propósito |
|---|---|
| `hipocampo_mcp_server.py` | Servidor FastMCP (stdio / HTTP / SSE) — 22+ tools MCP |
| `hipocampo_ssc_search.py` | Búsqueda SSC v3.7 (router + vectorial + trigram + ilike) |
| `hipocampo_search.py` | BIRE v3.7 (búsqueda unificada con time decay + search_with_stats) |
| `hipocampo_compress.py` | Compresión híbrida extractiva + LLM con context budget |
| `hipocampo_health.py` | Health check (PostgreSQL, API, disco, extensiones, HNSW) |
| `hipocampo_stats.py` | Métricas de rendimiento y auto-tune de thresholds |
| `hipocampo_dedup.py` | Detección y fusión de duplicados semánticos |
| `hipocampo_checkpoint.py` | Checkpointing con decaimiento logarítmico |
| `hipocampo_autotag.py` | Auto-tagging por reglas regex |
| `hipocampo_backfill_vectorial.py` | Backfill embeddings faltantes |
| `hipocampo_calibrate.py` | Calibración de ponderación híbrida |
| `mm_brain_tool.py` | Persistencia en memoria_vectorial + Freeplane |

### Módulos
| Módulo | Propósito |
|---|---|
| `hipocampo/db.py` | Conexión compartida, get_embedding, load_config, init_pool |

### Despliegue
- `Dockerfile`, `Dockerfile.fly`, `Dockerfile.simple` — contenedores
- `docker-compose.yml` — stack completo
- `fly.toml` — deploy a Fly.io

---

## 🆕 Changelog v4.2

| Fase | Features |
|---|---|
| **6** | Sistema Inmunológico — Protección contra Regresiones: ciclo snapshot → verificar → inmunizar, archivos frágiles pre-cargados, economía inmune (snapshot=barato, regla=caro) |

## 🆕 Changelog v4.1

| Fase | Features |
|---|---|
| **5** | Jerarquía de memoria (episódica/semántica/automática) + triggers preventivos contextuales + `set_nivel_hipocampo` tool + `consolidate_hipocampo` |

## 🆕 Changelog v4.0

| Fase | Features |
|---|---|
| **1** | Time decay exponencial (λ=0.05, floor 20%), cache de embeddings, dedup en save, search_with_stats() estructurado, auto-checkpoint al iniciar |
| **2** | HNSW health check + auto-create, context budget aware (budget_ratio, auto token estimation), session auto-summary cada 20 saves, preload_context(project_path) |
| **3** | Memory Graph: tabla memory_links + 4 tools (link/unlink/graph/path), auto_link=True en save_hipocampo |

---

## 🇬🇧 English Version

---

name: hipocampo-protocol
description: Dual-memory protocol with Sparse Selective Caching (SSC) v4.0 + Memory Graph + Hybrid Compression. Persists in memoria_vectorial and memory_items with progressive semantic search. Load at session start.

---

# Hipocampo Protocol v4.1 — SSC + Memory Graph + Hybrid Compression

External persistent memory system with **Sparse Selective Caching** (inspired by "Memory Caching: RNNs with Growing Memory", Google 2025).

Repo: `https://github.com/carrasquelalex1/hipocampo`
MCP Server live: `https://alexbell1-hipocampo-mcp.hf.space/mcp` (Streamable HTTP)

---

## 📚 Structure

```
hipocampo_db (PostgreSQL 17 + pgvector + pg_trgm + memory_links)
├── 🧠 memoria_vectorial (~830 records, 1024d embedding)
│   └── content, metadata (jsonb), HNSW embedding (cosine), code_snippet
├── 🤖 memory_items (~250 records, 1024d embedding)
│   └── memory_type (profile|event|decision), summary, extra, categories
├── 🔗 memory_links — directed graph between memories (source → target, type, weight)
├── 🏷️ memory_categories
├── 🔗 category_items (M:N)
├── 📎 query_stats — search performance metrics
└── 📎 watches — webhooks for memory events
```

Embeddings: **1024d** (Ollama `qwen3-embedding:0.6b` local por defecto; NVIDIA NIM como fallback).

---

## 🔍 Phase 1: Pre-action — Search with SSC v4.0

Use MCP tools `search_hipocampo()` or `quick_hipocampo_search()`:

### SSC Pipeline (4 phases, progressive scale)
```
Phase 1 TAG ROUTER  → classify query (profile/technical/mixed), dynamic weights
Phase 2 PGVECTOR    → top-20 semantic in BOTH tables ← 70%+ confidence: stop here
Phase 3 TRIGRAM     → expand with GIN if confidence < 70%
Phase 4 ILIKE       → full scan only if confidence < 40%
```

### Exponential time decay
```math
final_score = raw_score × max(0.20, e^{-λ × days})
```
- λ = 0.05 configurable
- Floor 20%: no memory loses more than 80% of its score due to age
- Auto-adjust thresholds via `hipocampo_tune()`

DO NOT use `ILIKE '%...%' LIMIT 20` directly.

---

## ⚙️ Phase 2: Persistence — MCP Tools v4.0

### Search & Retrieval
| Tool | Description |
|---|---|
| `search_hipocampo(query, session_id)` | Hybrid semantic + lexical search with BIRE + SSC |
| `quick_hipocampo_search(query, session_id)` | Short alias for search_hipocampo |
| `preload_context(project_path, k)` | Extract keywords from path, search and compress relevant project context |
| `compress_hipocampo(query, k, method, budget_ratio)` | Hybrid compression (extractive + LLM) of memories; auto-estimates tokens based on budget |

### Save & Profile
| Tool | Description |
|---|---|
| `save_hipocampo(content, memory_type, code, categories, session_id, force, auto_link)` | Save to memoria_vectorial. `auto_link=True` auto-links with similar memories |
| `profile_hipocampo(summary, extra, categories)` | Save personal profile to memory_items |
| `update_hipocampo(id, content, memory_type, code, categories)` | Update existing memory |
| `delete_hipocampo(id)` | Delete memory |

### Memory Graph (v4.0 Phase 3)
| Tool | Description |
|---|---|
| `link_hipocampo(source_id, target_id, relation_type, weight)` | Create directed edge (related, follow_up, part_of, references, similar, chain) |
| `unlink_hipocampo(id / source+target+type)` | Remove edge(s) from graph |
| `graph_hipocampo(node_id, depth)` | BFS ASCII tree from a node; overview with node_id=0 |
| `path_hipocampo(from_id, to_id, max_depth)` | Shortest BFS path between two memories |

### Webhooks
| Tool | Description |
|---|---|
| `watch_hipocampo(pattern, webhook_url)` | Register webhook triggered on create/modify/delete |
| `unwatch_hipocampo(id)` | Remove webhook |
| `list_watches()` | List all registered webhooks |

---

## 🕒 Phase 3: Maintenance (MCP Self-Improvement)

The MCP server exposes 7 self-maintenance tools:

### Self-diagnosis & Repair
- `hipocampo_health()` — Full health check (PostgreSQL, API, disk, extensions, HNSW index)
- `hipocampo_auto_repair()` — Auto-repair issues (including HNSW index creation)

### Performance Optimization
- `hipocampo_stats()` — Latency metrics, avg score, recommendations
- `hipocampo_tune()` — Adjust SSC thresholds and hybrid weights based on real usage

### Memory Maintenance
- `hipocampo_dedup(merge)` — Detect and merge duplicates (exact + semantic via cosine)
- `hipocampo_checkpoint(dry_run)` — Logarithmic checkpointing with auto-run on startup
- `hipocampo_maintenance()` — Full cycle: repair → dedup → checkpoint → tune

### Context Compression
| Parameter | Description |
|---|---|
| `budget_ratio` | Scale auto-estimated token target (0.5 = half budget, 2.0 = double) |
| `target_token=-1` | Auto-estimates: 30% of total content, min 200, max 2000 |
| `method=hybrid` | Uses LLM for technical content, extractive for generic |

### Session Auto-Summary
Every 20 saves in the same session, a summary is auto-consolidated in the background.

---

## 🧠 Phase 4: Memory Graph

Memories in Hipocampo can relate to each other forming a navigable **directed graph**.

### Relation types
| Type | Usage |
|---|---|
| `related` | Generic semantic relation (default) |
| `follow_up` | Origin is continuation/sequel of target |
| `part_of` | Origin is part of target (hierarchy) |
| `references` | Origin references target |
| `similar` | Semantically similar (auto-assigned by auto_link) |
| `chain` | Part of a context chain |

### Auto-linking
When saving with `auto_link=True`, the system finds the 3 most similar memories (>0.75 cosine) and creates `similar` edges automatically.

### Usage example
```python
# Create manual link
link_hipocampo(source_id=1106, target_id=1105, relation_type="follow_up", weight=0.9)

# Explore graph from a node
graph_hipocampo(node_id=1106, depth=3)

# Find path between two memories
path_hipocampo(from_id=1000, to_id=1106, max_depth=5)

# Save with auto-linking
save_hipocampo("New memory", auto_link=True)
```

---

## 🧬 Phase 5: Memory Hierarchy — Automatic Rules (Level 3)

Memories in Hipocampo have 3 hierarchical levels that replicate biological memory consolidation: from fragile detail (episodic) to permanent reflex (automatic).

### Levels

| Level | Behavior | When to use |
|---|---|---|
| `episodica` (default) | Full detail, compressible by checkpoint | Daily events, decisions, learnings |
| `semantica` | Consolidated knowledge, checkpoint-protected | Confirmed lessons, stable rules |
| `automatica` | Permanent rule, **never** compressed or deleted | Critical errors, security patterns, invariants |

### Consolidation flow

```
episodica ──(consolidate, min_age_days)──→ semantica ──(set_nivel)──→ automatica
     ↑                                         ↑                         ↑
   fragile,                                protected,               permanent,
compressible                             checkpoint-safe           immutable
```

### Trigger-based preventive mechanism

`automatica` rules use **trigger categories** to reactivate by context. Before editing code in a project, search with the trigger combination that applies:

```
search_hipocampo("trigger:<project> trigger:<language> trigger:<tech>")
```

The system replicates the biological hippocampus mechanism: a partial cue from the current context triggers retrieval of error memories **before** acting, not after.

### Standard trigger catalog

| Trigger | Activation context |
|---|---|
| `trigger:<project>` | When working on a specific project (e.g., `trigger:sgv`) |
| `trigger:php`, `trigger:javascript`, `trigger:python`, `trigger:bash` | Language of the file being edited |
| `trigger:chartjs`, `trigger:tomcat`, `trigger:json_encode` | Library or technology |
| `trigger:csv`, `trigger:deploy`, `trigger:edit`, `trigger:audit` | Type of operation |
| `trigger:password`, `trigger:hash`, `trigger:security` | Security context |
| `trigger:frontend`, `trigger:dom`, `trigger:css` | Frontend audit |

### Full flow example

```python
# 1. Save an error as an automatic rule with triggers
save_hipocampo(
    content="NEVER use JS variables inside <?= json_encode() ?> in PHP. Use literals.",
    memory_type="decision",
    categories=["trigger:project", "trigger:chartjs", "trigger:php", "trigger:json_encode"],
    nivel="automatica"
)

# 2. Days later, when editing a chart in the same project, search triggers
search_hipocampo("trigger:project trigger:chartjs trigger:php")

# 3. The automatic rule appears in results → agent applies it preventively
```

### Hierarchy tools

| Tool | Description |
|---|---|
| `set_nivel_hipocampo(id, nivel)` | Change memory level: `episodica`, `semantica`, `automatica` |
| `consolidate_hipocampo(min_age_days, dry_run)` | Migrate old episodic memories to semantic |

> **Important**: The `automatica` level is irreversible by design. An automatic rule is a conditioned reflex — it is never compressed by checkpoint, never merged in dedup, never deleted by consolidate. Use with criteria.

---

## 🛡️ Phase 6: Immune System — Regression Protection (v4.2)

Automatic rules prevent errors ALREADY committed. But an agent can also break something that was working fine — a NEW error with no prior record. This phase implements a **code immune system**: it detects breakage the moment it happens and generates permanent immunity for the future.

### 3-step cycle

**Step 1 — Pre-change snapshot.** Before editing a file, save a snapshot of what works:
```python
save_hipocampo(
    "PRE-CHANGE SNAPSHOT: header.php in SGV.pro.
     Critical dependencies: PHP session, PDO connection, 40+ dependent files.
     Verification: open dashboard.php, confirm it loads without error 500.",
    categories=["snapshot", "trigger:project", "trigger:regression", "trigger:header"],
    nivel="episodica"  # cheap — compressed away if no problem
)
```

**Step 2 — Post-change: verify.** After editing, run the snapshot verification steps:
- If OK → the episodic snapshot gets compressed by checkpoint (zero lingering cost)
- If something broke → step 3

**Step 3 — Immunize.** Create an automatic rule capturing cause and effect:
```python
save_hipocampo(
    "IMMUNE RULE: Editing header.php in SGV.pro broke dashboard.
     Cause: session_start() was accidentally removed.
     Symptom: HTTP 500 on all pages, 'session already started' in logs.
     Fix: restore session_start() at the top of the file.",
    categories=["trigger:project","trigger:regression","trigger:header","trigger:session"],
    nivel="automatica"  # permanent — never compressed
)
```

### Immune economy principle

| Moment | Cost | Level |
|--------|------|-------|
| Pre-change (snapshot) | Cheap | `episodica` — auto-compressed if no damage |
| Post-break (rule) | Expensive | `automatica` — permanent, immutable |

The system only pays the memory cost when real damage occurred — just like the biological immune system: it generates antibodies only after exposure to the pathogen.

### Pre-loaded fragile files

| File | What breaks if edited incorrectly |
|------|----------------------------------|
| `header.php` | Sessions, PDO connection, dozens of dependent files |
| `conexion.php` | Entire data layer of the project |
| `utils.php` | Shared functions (CSRF, geography, dates) |
| `auth.php` | Login, roles, permissions system-wide |
| `db_connection.php` | Full stack if credentials change |

### How to use with triggers

Before any edit, search for previous regressions on that file:
```
search_hipocampo("trigger:regression trigger:<file> trigger:<project>")
```

If an immune rule exists for that file, it will surface and the agent will know exactly what to avoid touching.

---

## 🌐 MCP Server — Connection

### Local (Streamable HTTP, recommended)
```bash
python3 /path/to/hipocampo/scripts/hipocampo_mcp_server.py --http 8001
```

### Local (stdio, for desktop clients)
```bash
python3 /path/to/hipocampo/scripts/hipocampo_mcp_server.py
```

### Remote (Hugging Face Spaces — free, no API key)
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

> **⚠️ SSE** is deprecated since MCP spec 2025-03-26. Use Streamable HTTP.

### Systemd (persistent service)
```bash
systemctl --user status hipocampo-mcp.service
systemctl --user restart hipocampo-mcp.service
journalctl --user -u hipocampo-mcp.service -n 50
```

---

## ✅ Critical Rules

1. **Family** → `memory_type='profile'`, category `relationships`. NEVER `event`.
2. **Auto-tagging** mandatory for all new `memory_items`.
3. **SSC preferred over ILIKE** for searches. Do not use raw psql ILIKE.
4. **memory_items** is read-only via MCP (no direct inserts).
5. **PostgreSQL** uses Unix socket (`/var/run/postgresql`), user `alex`, no password.
6. **Embeddings**: 1024d via Ollama local (default) or NVIDIA NIM.
7. **API Keys**: `NVIDIA_API_KEY` only if using NIM; not needed with local Ollama.
8. **Auto-dedup**: when saving, if a memory with similarity >0.9 exists, it's blocked (except with `force=True`).
9. **Auto-checkpoint**: runs when the MCP server starts.
10. **HNSW index**: if missing in health check, auto-created.

---

## 📂 Repo Scripts

```bash
git clone https://github.com/carrasquelalex1/hipocampo.git
```

| Script | Purpose |
|---|---|
| `hipocampo_mcp_server.py` | FastMCP server (stdio / HTTP / SSE) — 22+ MCP tools |
| `hipocampo_ssc_search.py` | SSC v3.7 search (router + vectorial + trigram + ilike) |
| `hipocampo_search.py` | BIRE v3.7 (unified search with time decay + search_with_stats) |
| `hipocampo_compress.py` | Hybrid extractive + LLM compression with context budget |
| `hipocampo_health.py` | Health check (PostgreSQL, API, disk, extensions, HNSW) |
| `hipocampo_stats.py` | Performance metrics and threshold auto-tuning |
| `hipocampo_dedup.py` | Detection and merging of semantic duplicates |
| `hipocampo_checkpoint.py` | Checkpointing with logarithmic decay |
| `hipocampo_autotag.py` | Auto-tagging via regex rules |
| `hipocampo_backfill_vectorial.py` | Backfill missing embeddings |
| `hipocampo_calibrate.py` | Hybrid weighting calibration |
| `mm_brain_tool.py` | Persistence in memoria_vectorial + Freeplane |

### Modules
| Module | Purpose |
|---|---|
| `hipocampo/db.py` | Shared connection, get_embedding, load_config, init_pool |

### Deployment
- `Dockerfile`, `Dockerfile.fly`, `Dockerfile.simple` — containers
- `docker-compose.yml` — full stack
- `fly.toml` — deploy to Fly.io
