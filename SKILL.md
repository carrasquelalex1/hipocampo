---
name: hipocampo-protocol
description: Protocolo de memoria dual con Sparse Selective Caching (SSC). Persiste en memoria_vectorial y memory_items con búsqueda semántica progresiva.
---

# Protocolo Hipocampo: Memoria Dual, SSC y Checkpointing

**Visión General Arquitectónica:** Sistema de memoria persistente de doble capa (Técnica y Perfil) asistida por un caché semántico progresivo (SSC - Sparse Selective Caching). Diseñado para otorgar contexto a largo plazo con latencia optimizada.

---

## 📚 Estructura de Datos (PostgreSQL 17)

```text
hipocampo_db (pgvector + pg_trgm)
├── 🧠 memoria_vectorial (Conocimiento Técnico)
│   ├── Campos: contenido (text), metadatos (jsonb), embedding (vector 1024d)
│   └── Índices: HNSW (búsqueda por coseno), GIN (trigramas)
├── 🤖 memory_items (Perfil e Historial del Usuario)
│   ├── Campos: memory_type ('profile' | 'event' | 'decision'), summary, embedding, extra
│   └── Índices: HNSW (búsqueda por coseno), GIN (trigramas)
├── 🏷️ memory_categories (Taxonomía)
├── 🔗 category_items (Mapeo M:N)
└── 📎 resources (Archivos y URLs de referencia)
```

---

## 🔍 Fase 1: Pre-actuación y Búsqueda (SSC)

Para consultar la base de conocimiento, se debe utilizar de manera excluyente el script `hipocampo_ssc_search.py` (evitar sentencias `ILIKE` directas sobre la base de datos).

```bash
# Búsqueda estándar
python3 scripts/hipocampo_ssc_search.py "término de búsqueda"

# Búsqueda con umbral de confianza personalizado
python3 scripts/hipocampo_ssc_search.py "término" 5   
```

### El Algoritmo SSC (Aproximación Progresiva)
El algoritmo prioriza la velocidad y solo profundiza si la confianza de los resultados es baja:
1. **Fase 1 (TAG ROUTER):** Enruta y clasifica la consulta (perfil, técnico, mixto) ajustando los pesos dinámicamente.
2. **Fase 2 (PGVECTOR):** Realiza una búsqueda semántica (Top-20) en ambas tablas. *Si la confianza supera el 70%, el proceso finaliza aquí.*
3. **Fase 3 (TRIGRAMAS GIN):** Ejecuta una expansión léxica sobre el índice GIN si la confianza es < 70%.
4. **Fase 4 (ILIKE):** Recurre a un escaneo completo (Full Scan) de seguridad solo si la confianza es crítica (< 40%).

---

## ⚙️ Fase 2: Inserción y Auto-Categorización

| Tipo de Datos | Tabla de Destino | Herramienta/Método Preferido |
| :--- | :--- | :--- |
| **Proyectos, Código, ADRs** | `memoria_vectorial` | Herramienta MCP `save_hipocampo` o `mm_brain_tool.py` |
| **Datos Personales, Hábitos, Relaciones** | `memory_items` | Herramienta MCP `profile_hipocampo` o `hipocampo_autotag.py` |
| **Persistencia Dual** | *Ambas tablas* | Orquestar ambas inserciones de forma secuencial |

---

## ✅ Directrices y Mejores Prácticas

1. **Clasificación Estricta de Relaciones:** Los miembros de la familia (ej. esposa, hijos) o personas cercanas DEBEN registrarse en `memory_items` con `memory_type='profile'` y la categoría `relationships`. NUNCA clasificarlos como un `event`.
2. **Auto-Tagging:** Todo registro nuevo en `memory_items` debe pasar obligatoriamente por el motor de auto-tagging.
3. **Prevalencia de SSC:** El uso del pipeline SSC tiene prioridad absoluta sobre cualquier consulta SQL manual.
4. **Higiene de Datos:** Se requiere la ejecución regular del sistema de *Checkpointing* para consolidar y comprimir la memoria antigua.

### Categorías Soportadas en memory_items
`personal_info`, `relationships`, `preferences`, `habits`, `goals`, `knowledge`, `opinions`, `work_life`, `activities`, `experiences`

---

## 🕒 Compresión Temporal (Logarithmic Checkpointing)

Para mitigar el crecimiento exponencial de la base de datos, Hipocampo implementa una compresión basada en el decaimiento logarítmico del tiempo.

```bash
# Realizar un simulacro (auditoría de compresión)
python3 scripts/hipocampo_checkpoint.py --dry-run

# Ejecutar compresión definitiva
python3 scripts/hipocampo_checkpoint.py --force
```

**Escala de Retención:**
* **< 24h:** Sin compresión (alta granularidad y detalle absoluto).
* **1-7 días:** Retención exclusiva de los 3 eventos/registros top por proyecto.
* **7-30 días:** Consolidación en resúmenes de 200 caracteres por proyecto.
* **30-90 días:** Consolidación en resúmenes semanales de 100 caracteres.
* **> 90 días:** Fusión total en un (1) checkpoint maestro por proyecto/dominio.