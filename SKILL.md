---
name: hipocampo-protocol
description: Protocolo de memoria dual para el Hipocampo Digital. Persiste acciones en memoria_vectorial (Freeplane+PGVector) y memory_items (MCP Agent-Memory) con búsqueda RAG unificada y categorización inteligente.
---

# Protocolo Hipocampo — Memoria Dual con Auto-Tagging + Expansión por Tags

**Arquitectura:** El Hipocampo tiene **dos sistemas de memoria independientes**. Toda acción debe persistir en al menos `memoria_vectorial`. Datos de perfil/relaciones deben ir también a `memory_items`.

---

## 📚 Estructura de la Base de Datos

```
hipocampo_db (PostgreSQL)
├── 🧠 memoria_vectorial ← Recuerdos + búsqueda vectorial
│   ├── id (bigint PK)
│   ├── contenido (text)
│   ├── metadatos (jsonb) → {path, type, tags, status, archivos}
│   ├── embedding (vector 768d) ← Índice HNSW
│   └── code_snippet (text)
│
├── 🤖 memory_items ← Perfil del usuario, eventos, relaciones
│   ├── id (uuid PK)
│   ├── memory_type → 'profile' | 'event' | 'decision'
│   ├── summary (text)
│   ├── embedding (vector 768d)
│   ├── extra (jsonb) → {tags: [...]}
│   └── user_id
│
├── 🏷️ memory_categories (10 categorías)
├── 🔗 category_items ← Relación M:N
└── 📎 resources ← Archivos/URLs referenciados
```

---

## 🔍 Fase 1: Pre-actuación — BIRE

Usar el script `hipocampo_search.py` para buscar en **ambos sistemas**:

```bash
python3 scripts/hipocampo_search.py "término de búsqueda"
python3 scripts/hipocampo_search.py "término" 5  # umbral personalizado
```

### Algoritmo BIRE
```
CONSULTA → EXPANSIÓN → BÚSQUEDA DUAL → PUNTUACIÓN → FUSIÓN → EXPANSIÓN POR TAGS
```

No usar ILIKE con LIMIT fijo.

---

## ⚙️ Fase 2: Ejecución

| Tipo de dato | Tabla destino | Método |
|-------------|---------------|--------|
| Proyectos, código, acciones técnicas | `memoria_vectorial` | `mm_brain_tool.py` |
| Datos de perfil (nombre, gustos) | `memory_items` | SQL directo + categoría |
| **Familia (esposa, hijos, padres)** | **`memory_items` como `profile`** | **SQL + categoría `relationships`** |
| Eventos, relaciones | Ambos | Ambos métodos |

---

## 💾 Fase 3: Post-actuación (Persistencia)

### Opción A: Persistir en `memoria_vectorial`
```bash
python3 scripts/mm_brain_tool.py \
  "<path_en_freeplane>" \
  "<texto_del_nodo>" \
  [color] [link] [note] \
  --type "<TipoNodo>" \
  --code "<code_snippet>"
```

### Opción B: Persistir en `memory_items` (con auto-tagging + embedding)
```python
from hipocampo_autotag import auto_tag_full

clasificacion = auto_tag_full(summary)
# → {'tags': [...], 'category': '...', 'memory_type': 'profile'|'event'}
# Luego INSERT en memory_items con embedding 768d
```

### Opción C: Persistencia Dual Completa
Ejecutar Opción A **y** Opción B secuencialmente.

---

## 📋 Categorías Disponibles

`personal_info`, `relationships`, `preferences`, `habits`, `goals`,
`knowledge`, `opinions`, `work_life`, `activities`, `experiences`

---

## ✅ Reglas

1. Datos de **perfil/relaciones** → `memory_items` con categoría.
2. **Familia** → `memory_type='profile'`, categoría `relationships`. NUNCA como `event`.
3. Todo item en `memory_items` debe usar `auto_tag_full()` para asignar tags automáticamente.
4. Proyectos/código → `memoria_vectorial` vía `mm_brain_tool.py`.
5. Si aplica a ambos → **Persistencia Dual (Opción C)**.
