---
name: hipocampo-protocol
description: Protocolo de memoria dual con Sparse Selective Caching (SSC). Persiste en memoria_vectorial y memory_items con búsqueda semántica progresiva.
---

# Protocolo Hipocampo — Memoria Dual con SSC + Checkpointing

**Arquitectura:** Dos sistemas de memoria independientes + cache semántico con escalado progresivo (SSC).

---

## 📚 Estructura

```
hipocampo_db (PostgreSQL 17 + pgvector + pg_trgm)
├── 🧠 memoria_vectorial (814 registros)
│   ├── contenido (text), metadatos (jsonb), embedding (vector 768d)
│   └── Índices: HNSW (cosine), GIN trigram
├── 🤖 memory_items (323 registros) ← perfil del usuario
│   ├── memory_type → 'profile' | 'event' | 'decision'
│   ├── summary, embedding (768d), extra (jsonb)
│   └── Índices: HNSW (cosine), GIN trigram
├── 🏷️ memory_categories
├── 🔗 category_items
└── 📎 resources
```

---

## 🔍 Fase 1: Pre-actuación — Búsqueda SSC

Usar `hipocampo_ssc_search.py` (NO psql ILIKE directo):

```bash
python3 scripts/hipocampo_ssc_search.py "término de búsqueda"
python3 scripts/hipocampo_ssc_search.py "término" 5   # umbral personalizado
```

### Algoritmo SSC (4 fases progresivas)
```
Fase 1 (TAG ROUTER): Clasifica consulta → perfil/técnico/mixto → asigna pesos
Fase 2 (PGVECTOR):   Búsqueda semántica top-20 en AMBAS tablas ← si confianza > 70%, para aquí
Fase 3 (TRIGRAM):    Expansión GIN si confianza < 70% 
Fase 4 (ILIKE):      Full scan solo si confianza < 40%
```

Esto reemplaza a `ILIKE %...% LIMIT 10`. SSC escala de lo más rápido a lo más completo solo cuando es necesario, reduciendo ruido y tiempo de respuesta.

---

## ⚙️ Fase 2: Ejecución

| Tipo de dato | Tabla destino | Método |
|---|---|---|
| Proyectos, código, sesiones | `memoria_vectorial` | `mm_brain_tool.py` |
| Perfil (gustos, familia, datos personales) | `memory_items` | SQL + `hipocampo_autotag` |
| Ambos | Ambos | Persistencia Dual |

---

## 💾 Fase 3: Post-actuación (Persistencia)

### Opción A: memoria_vectorial
```bash
python3 scripts/mm_brain_tool.py \
  "<path_freeplane>" "<texto>" [color] [link] [note] \
  --type "<Tipo>" --code "<código>"
```

### Opción B: memory_items (con auto-tagging)
```python
from hipocampo_autotag import auto_tag_full
clasificacion = auto_tag_full(summary)
# → {'tags': [...], 'category': '...', 'memory_type': 'profile'|'event'}
# Luego INSERT con embedding 768d
```

### Opción C: Persistencia Dual
Ejecutar A y B secuencialmente.

---

## 📋 Categorías Disponibles

`personal_info`, `relationships`, `preferences`, `habits`, `goals`,
`knowledge`, `opinions`, `work_life`, `activities`, `experiences`

---

## ✅ Reglas Operativas

1. **Familia (esposa, hijos)** → `memory_type='profile'`, categoría `relationships`. NUNCA como `event`.
2. **Auto-tagging obligatorio** en todo `memory_items` nuevo.
3. **SSC preferido sobre ILIKE** para búsquedas.
4. **Checkpoints periódicos** para comprimir memorias viejas (>7 días).

---

## 🕒 Checkpointing (Decaimiento Logarítmico)

Ejecutar periódicamente para comprimir memorias antiguas:

```bash
# Vista previa (sin guardar)
python3 scripts/hipocampo_checkpoint.py --dry-run

# Guardar checkpoints
python3 scripts/hipocampo_checkpoint.py --force
```

### Escalas de compresión:
| Edad | Granularidad |
|---|---|
| < 24h | Sin compresión (detalle completo) |
| 1-7 días | Top 3 items por proyecto |
| 7-30 días | Resumen 200 chars por proyecto |
| 30-90 días | Resumen 100 chars por semana |
| > 90 días | 1 checkpoint por proyecto/dominio |
