---
name: hipocampo-protocol
description: Protocolo de memoria dual con Sparse Selective Caching (SSC). Persiste en memoria_vectorial y memory_items con búsqueda semántica progresiva.
---

# Hipocampo Protocol v3.8 — SSC + Checkpointing

Sistema de memoria externa persistente con **Sparse Selective Caching** (inspirado en "Memory Caching: RNNs with Growing Memory", Google 2025).

---

## 📚 Estructura

```
hipocampo_db (PostgreSQL 17 + pgvector + pg_trgm)
├── 🧠 memoria_vectorial (recuerdos técnicos, embedding 1024d)
│   └── contenido, metadatos (jsonb), embedding (HNSW), code_snippet
├── 🤖 memory_items (perfil, embedding 1024d)
│   └── memory_type (profile|event|decision), summary, extra, categories
├── 🏷️ memory_categories (10 categorías)
├── 🔗 category_items (M:N)
└── 📎 resources
```

---

## 🔍 Fase 1: Pre-actuación — Buscar con SSC

Usar el script `hipocampo_ssc_search.py`:

```bash
python3 scripts/hipocampo_ssc_search.py "término"
python3 scripts/hipocampo_ssc_search.py "término" 5
```

### Pipeline SSC (4 fases, escala progresiva)
```
Fase 1 TAG ROUTER → clasifica consulta (perfil/técnico/mixto)
Fase 2 PGVECTOR  → top-20 semántico en AMBAS tablas ← 70%+ confianza: para aquí
Fase 3 TRIGRAM    → expande con GIN si confianza < 70%
Fase 4 ILIKE      → full scan solo si confianza < 40%
```

---

## ⚙️ Fase 2: Persistencia

| Dato | Destino | Método MCP |
|---|---|---|
| Proyectos, código, sesiones | `memoria_vectorial` | `save_hipocampo()` |
| Perfil (gustos, familia, datos) | `memory_items` | `profile_hipocampo()` |

---

## 🕒 Fase 3: Checkpointing (Mantenimiento)

```bash
python3 scripts/hipocampo_checkpoint.py --dry-run
python3 scripts/hipocampo_checkpoint.py --force
```

| Edad | Granularidad |
|---|---|
| < 24h | Sin compresión |
| 1-7d | Top 3 items/proyecto |
| 7-30d | Resumen 200 chars/proyecto |
| 30-90d | Resumen 100 chars/semana |
| > 90d | 1 checkpoint/proyecto |

---

## ✅ Reglas Operativas

1. **Familia** → usar `profile_hipocampo()` con `memory_type='profile'`, categoría `relationships`. NUNCA `event`.
2. **Auto-tagging** obligatorio en todo `memory_items` nuevo.
3. **SSC preferido sobre ILIKE** para búsquedas.
4. **memory_items** y **resources** son solo lectura (plugin episodic-memory MCP).
5. **PostgreSQL** usa socket Unix (`/var/run/postgresql`), usuario local, sin contraseña.
6. **Embeddings**: 1024d vía NVIDIA NIM (`nvidia/nv-embedqa-e5-v5`).

### Categorías Soportadas
`personal_info`, `relationships`, `preferences`, `habits`, `goals`, `knowledge`, `opinions`, `work_life`, `activities`, `experiences`

---

## 🔌 MCP Server (11 tools)

| Tool | Descripción |
|---|---|
| `search_hipocampo` | Búsqueda híbrida semántica + léxica |
| `quick_hipocampo_search` | Alias de búsqueda rápida |
| `save_hipocampo` | Guardar en memoria_vectorial |
| `profile_hipocampo` | Guardar perfil en memory_items |
| `hipocampo_health` | Health check completo |
| `hipocampo_auto_repair` | Reparación automática |
| `hipocampo_stats` | Estadísticas de rendimiento |
| `hipocampo_tune` | Ajustar thresholds SSC |
| `hipocampo_dedup` | Detectar/fusionar duplicados |
| `hipocampo_checkpoint` | Checkpointing logarítmico |
| `hipocampo_maintenance` | Ciclo completo de mantenimiento |
