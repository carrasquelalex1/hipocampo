# Hipocampo: Un Sistema de Memoria Dual con Búsqueda Integrada por Relevancia Expansiva (BIRE)

**Autor:** Alexander Carrasquel
**Versión del documento:** 3.6  
**Fecha:** 24 de mayo de 2026  
**Contacto:** Sistema Hipocampo — hipocampo_db (PostgreSQL 17 + pgvector)

---

## Resumen

Este documento describe la arquitectura y los fundamentos algorítmicos de **Hipocampo**, un sistema de memoria dual diseñado para asistentes de inteligencia artificial. El sistema almacena y recupera información estructurada y no estructurada utilizando dos subsistemas de memoria independientes pero complementarios: una base vectorial semántica y un almacén de perfiles categorizados. Se introduce el algoritmo **BIRE (Búsqueda Integrada por Relevancia Expansiva)**, un método de recuperación unificada que combina expansión léxica de consultas, búsqueda vectorial semántica (con embeddings unificados 1024d en ambos subsistemas) y puntuación compuesta para superar las limitaciones de las búsquedas tradicionales basadas en `ILIKE` con límites fijos.

**Palabras clave:** memoria dual, búsqueda vectorial, RAG, pgvector, pg_trgm, índices GIN, expansión de consultas, relevancia compuesta, ponderación híbrida, embeddings unificados, auto-tagging, sistemas de memoria para IA.

---

## 1. Introducción

Los asistentes de inteligencia artificial enfrentan un problema fundamental: cómo mantener y recuperar información persistente a través de múltiples sesiones de interacción. Las soluciones tradicionales —archivos de registro, bases de datos relacionales simples o almacenamiento plano— adolecen de dos problemas principales: (1) no capturan la _semántica_ del contenido almacenado, y (2) las búsquedas literales pierden información valiosa cuando la consulta no coincide exactamente con los términos almacenados.

Hipocampo aborda estos problemas mediante una arquitectura de **memoria dual** que separa conceptualmente dos tipos de información:

1. **Memoria vectorial (`memoria_vectorial`)**: Almacena recuerdos técnicos, proyectos, fragmentos de código y logs de sesión en formato de texto enriquecido, respaldados por _embeddings_ vectoriales para búsqueda semántica.
2. **Memoria de perfil (`memory_items`)**: Almacena datos personales del usuario —gustos, preferencias, relaciones, eventos— organizados por tipo y categoría.

El corazón de la contribución es el algoritmo **BIRE**, que unifica la recuperación de ambos subsistemas mediante un proceso de cuatro fases: expansión de consulta, búsqueda dual (vectorial + léxica expansiva), puntuación compuesta y fusión con corte dinámico.

---

## 2. Arquitectura del Sistema

### 2.1 Base de Datos

Hipocampo opera sobre **PostgreSQL 17** con la extensión **pgvector**, alojando 7 tablas principales en la base de datos `hipocampo_db`:

```
hipocampo_db
├── memoria_vectorial (682 registros)
├── memoria_historica (9 registros, uso menor)
├── memory_items (218 registros)
├── memory_categories (10 categorías)
├── category_items (123 relaciones M:N)
└── resources (139 recursos referenciados)
```

### 2.2 Subsistema Vectorial (`memoria_vectorial`)

| Columna | Tipo | Descripción |
|---------|------|-------------|
| `id` | `bigint PK` | Identificador autoincremental |
| `contenido` | `text` | Texto completo del recuerdo |
| `metadatos` | `jsonb` | Metadatos flexibles: path, type, tags, status, archivos |
| `embedding` | `vector(1024)` | Embedding semántico generado por `nvidia/nv-embedqa-e5-v5` |
| `code_snippet` | `text` | Fragmento de código asociado (opcional) |

La columna `embedding` está indexada mediante un **índice HNSW** con métrica de similitud coseno (`vector_cosine_ops`), permitiendo búsquedas `ORDER BY embedding <=> consulta` con complejidad **O(log n)** incluso sobre 680+ vectores de 1024 dimensiones.

La persistencia en este subsistema se realiza a través de `mm_brain_tool.py`, que escribe simultáneamente en PostgreSQL y en un archivo XML Freeplane (`knowledge_base.mm`) para respaldo visual.

### 2.3 Subsistema de Perfil (`memory_items`)

| Columna | Tipo | Descripción |
|---------|------|-------------|
| `id` | `uuid PK` | Identificador único universal |
| `memory_type` | `varchar` | Tipo de registro: `'profile'`, `'event'`, `'decision'` |
| `summary` | `text` | Texto descriptivo del dato |
| `embedding` | `vector(1024)` | Embedding semántico unificado (misma dimensión que subsistema vectorial) |
| `extra` | `jsonb` | Metadatos adicionales |
| `user_id` | `varchar` | Identificador del usuario (ej: `'usuario_ejemplo'`) |

Cada registro en `memory_items` se asocia a una o más categorías a través de la tabla puente `category_items`, que implementa una relación muchos-a-muchos con `memory_categories`. Las categorías disponibles son:

`personal_info`, `relationships`, `preferences`, `habits`, `goals`, `knowledge`, `opinions`, `work_life`, `activities`, `experiences`

### 2.4 Independencia de Subsistemas

Ambos subsistemas son **esquemáticamente independientes**: no comparten claves foráneas y cada uno mantiene su estructura de datos específica. Sin embargo, desde v3.6 comparten el **mismo modelo de embedding** (`nvidia/nv-embedqa-e5-v5` con 1024 dimensiones), lo que permite búsqueda vectorial cross-sistema unificada. La fusión semántica ocurre en la _capa de búsqueda_, donde el algoritmo BIRE consulta ambos sistemas y combina los resultados en un ranking único.

---

## 3. El Problema de la Búsqueda Ingenua

Antes de BIRE, la búsqueda se realizaba mediante consultas SQL del tipo:

```sql
SELECT contenido FROM memoria_vectorial WHERE contenido ILIKE '%keyword%' ORDER BY id DESC LIMIT 10;
```

Este enfoque presenta cuatro problemas críticos:

| Problema | Consecuencia |
|----------|-------------|
| **Límite fijo arbitrario** | `LIMIT 10` descarta resultados relevantes más allá del décimo |
| **Coincidencia literal** | `ILIKE '%planta%'` no encuentra "hierba", "vegetal" o "orégano" |
| **Sin puntuación de relevancia** | No hay forma de distinguir resultados marginales de los altamente relevantes |
| **Orden temporal, no semántico** | `ORDER BY id DESC` prioriza registros recientes sobre los relevantes |

En la práctica, esto significaba que una consulta como "¿qué plantas medicinales me gustan?" podía encontrar **Malojillo** (porque aparecía múltiples veces y tenía alta probabilidad de estar entre los primeros 10 resultados), pero perdía **Orégano Orejón** si ese registro estaba más allá del límite.

---

## 4. Algoritmo BIRE (Búsqueda Integrada por Relevancia Expansiva)

BIRE es un algoritmo de recuperación unificada que opera en **cuatro fases secuenciales**:

```
CONSULTA → EXPANSIÓN LÉXICA → BÚSQUEDA DUAL → PUNTUACIÓN COMPUESTA → FUSIÓN Y RANKING
```

### 4.1 Fase 1: Expansión Léxica de Consulta

Dada una consulta de entrada _Q_, se genera un conjunto aumentado de términos de búsqueda _T_ mediante:

1. **Tokenización**: Se extraen todas las palabras alfabéticas de _Q_ en minúsculas.
2. **Mapeo por raíces lexicales**: Cada token se busca en un diccionario `STEM_MAP` que contiene ~30 entradas con variantes morfológicas y sinónimos. Por ejemplo:
   - `"planta"` → `{planta, plantas, vegetal, hierba, hierbas, herbal}`
   - `"medicinal"` → `{medicinal, medicinales, medicina, curativa, curativo}`
   - `"orégano"` → `{orégano, oregano, orejón, orejon}`
3. **Sinónimos globales**: Se aplica un segundo diccionario `SINONIMOS_GLOBALES` para relaciones semánticas generales (ej: `"gustar"` → `{preferir, encantar, fascinar}`).

El resultado es un conjunto de términos _T_ = {_t₁, t₂, ..., tₙ_} que se utiliza tanto para la generación de patrones `ILIKE ANY` como para el cálculo de la razón de coincidencia.

### 4.2 Fase 2: Búsqueda Dual

#### 4.2.1 Búsqueda Vectorial Semántica (Subsistema 1)

Se genera un embedding de consulta _E_q_ utilizando el modelo `nvidia/nv-embedqa-e5-v5` con dimensionalidad 1024. Luego se ejecuta:

```sql
SELECT id, contenido, metadatos, code_snippet,
       1 - (embedding <=> %s::vector(1024)) AS similitud
FROM memoria_vectorial
WHERE embedding IS NOT NULL
ORDER BY embedding <=> %s::vector(1024)
LIMIT 50;
```

La similitud coseno _sim_coseno_ ∈ [0, 1] se transforma a una puntuación escalada: **score_vectorial = sim_coseno × 100**.

#### 4.2.2 Búsqueda Léxica Expansiva (Ambos Subsistemas)

A partir de los términos expandidos _T_, se generan patrones `ILIKE ANY`:

```sql
SELECT ... FROM memoria_vectorial
WHERE contenido ILIKE ANY (ARRAY['%planta%', '%medicinal%', '%hierba%', ...]);
```

Para **memory_items**, la consulta incluye un `LEFT JOIN` con `category_items` y `memory_categories` para enriquecer los resultados con información de categoría.

No se aplica ningún `LIMIT` en esta fase. La cardinalidad del resultado depende exclusivamente de cuántos registros coinciden con al menos uno de los patrones expandidos.

### 4.3 Fase 3: Puntuación Compuesta

Cada resultado se evalúa con una **función de puntuación** que depende de su origen:

#### Para `memoria_vectorial` (búsqueda léxica):

$$score_{lex\_mv} = \min\left(100, \frac{coincidencias}{términos\_totales} \times 90 + bonus\_exactitud\right)$$

donde:
- _coincidencias_: número de términos del conjunto T que aparecen en el contenido
- _términos_totales_: cardinalidad de T
- _bonus_exactitud_: 15 puntos si algún término de la consulta original aparece textualmente

#### Para `memory_items` (búsqueda léxica):

$$score_{lex\_mi} = \min\left(100, \frac{coincidencias}{términos\_totales} \times 75 + boost\_perfil + bonus\_exactitud\right)$$

donde:
- _boost_perfil_: 15 puntos si `memory_type = 'profile'`, 5 puntos en caso contrario
- _bonus_exactitud_: 10 puntos si hay coincidencia exacta de palabra completa

#### Para búsqueda vectorial:

$$score_{vec} = sim\_coseno \times 100$$

### 4.4 Fase 4: Fusión y Ranking con Corte Dinámico

Los tres conjuntos de resultados (vectorial, léxico MV, léxico MI) se fusionan mediante:

1. **Deduplicación**: Se agrupan registros cuyo contenido coincide en los primeros 120 caracteres (normalizados a minúsculas). Para cada grupo, se conserva el score máximo y el método de mayor jerarquía (vectorial > léxico).
2. **Ranking**: Se ordenan todos los resultados por score descendente.
3. **Corte dinámico**: Se eliminan los resultados con score inferior a un **umbral mínimo _θ_** (por defecto _θ_ = 10 sobre 100). No hay límite superior de resultados.

Este corte dinámico reemplaza al `LIMIT` fijo: todos los resultados con relevancia mínima son recuperados, independientemente de su posición.

### 4.5 Fase 5: Expansión por Tags (v3.1)

La expansión por tags resuelve el problema de **items atómicos no conectados**: datos que viven como registros independientes en `memory_items` (ej: "esposa", "hijo", "hija") no tienen forma de saber que pertenecen al mismo grupo a través de búsqueda léxica o vectorial.

**Mecanismo:**

1. **Persistencia de tags:** Cada `memory_items.extra` puede contener un array `tags`:  
   `{"tags": ["familia"]}`. `memoria_vectorial.metadatos` también soporta `tags` desde su origen.

2. **Extracción de tags desde resultados:** Después de la fusión inicial (Fases 1-4), BIRE extrae todos los tags únicos de los resultados encontrados.

3. **Coincidencia consulta ↔ tags (cruce expansivo):** BIRE escanea TODOS los tags existentes en ambas tablas y detecta cuáles coinciden (parcial o totalmente) con los términos expandidos de la consulta original. Esto permite encontrar relaciones aunque ningún resultado léxico inicial las haya detectado. Por ejemplo, buscar "familia" encuentra el tag "familia" aunque ningún resultado léxico contenga la palabra "familia".

4. **Expansión:** Por cada tag coincidente, se buscan TODOS los items (en ambas tablas) que compartan ese tag y se agregan con score base 70.0, método `expansion_por_tags`.

**Ventaja clave sobre clusters hardcodeados:** No requiere modificar el código para nuevos grupos. Cualquier conjunto de datos (familia, plantas medicinales, proyectos, hobbies) se vincula simplemente compartiendo un tag.

---

## 5. Evaluación Experimental

### 5.1 Configuración

El sistema fue evaluado sobre la base `hipocampo_db` con 682 registros en `memoria_vectorial` y 208 en `memory_items`. Se comparó el enfoque anterior (ILIKE + LIMIT 10) contra BIRE v3.0 (umbral θ = 10).

### 5.2 Caso de Estudio: "plantas medicinales"

| Métrica | ILIKE + LIMIT 10 | BIRE v3.0 |
|---------|-----------------|-----------|
| memoria_vectorial encontrados | 3 | 43 |
| memory_items encontrados | 1 (malojillo) | 5 (malojillo × 3, orégano, evento) |
| Orégano Orejón recuperado | ❌ No | ✅ Sí (score 45.5) |
| Resultados totales | 10 (truncados) | 48 (todos sobre θ) |

La mejora es sustancial: BIRE recuperó el **100%** de los registros relevantes en `memory_items`, mientras que el enfoque anterior perdió el 80% (4 de 5 registros).

### 5.3 Falsos Positivos

La búsqueda vectorial introduce resultados con relevancia semántica baja (score ~58-62) correspondientes a proyectos técnicos sin relación aparente con plantas medicinales, pero cuya representación vectorial resulta cercana en el espacio de 1024 dimensiones. En la práctica, estos falsos positivos ocupan las primeras posiciones del ranking debido a que el embedding "planta medicinal" tiene vectores cercanos a términos como "proyecto", "sistema" y "desarrollo" en el corpus técnico del usuario.

Este es un comportamiento esperado en sistemas de búsqueda vectorial y puede mitigarse mediante:
- Ajuste del umbral _θ_ (ej: _θ_ = 40 para filtrar ruido semántico)
- Ponderación híbrida que favorezca coincidencias léxicas cuando la consulta contiene términos concretos

### 5.4 Búsqueda por Término Único: "orégano"

Para consultas con términos específicos, BIRE coloca el resultado relevante en la **primera posición**:

```
 1. [62.5] memory_items [profile] | léxico
    💬 Al usuario tambien le gusta el Oregano Orejon como planta medicinal
```

El resto de resultados (50 registros de memoria_vectorial) corresponden a coincidencias vectoriales con scores descendentes desde 61.2 hasta 58.2.

---

## 6. Complejidad y Eficiencia

| Fase | Complejidad | Notas |
|------|------------|-------|
| Expansión de consulta | O(k) | k = tokens en consulta (típicamente < 10) |
| Búsqueda vectorial | O(log n × d) | Índice HNSW: log n ≈ 10 para n = 682, d = 1024 |
| Búsqueda léxica MV | O(n) | ILIKE ANY sobre 682 registros |
| Búsqueda léxica MI | O(m) | ILIKE ANY sobre 208 registros |
| Fusión y ranking | O(r × log r) | r = resultados fusionados |

El cuello de botella es la búsqueda léxica `ILIKE ANY`, que requiere escaneo secuencial. Para conjuntos de datos más grandes (>10⁵ registros), se recomienda migrar a índices GIST/GIN con `pg_trgm` para acelerar `ILIKE`.

**Tiempo medio de respuesta** (promedio de 10 consultas): ~1.5 segundos, de los cuales ~1.2 segundos corresponden a la generación del embedding (API NVIDIA).

---

## 7. Trabajo Relacionado

BIRE se inscribe en la tradición de los sistemas de **Recuperación Aumentada por Generación (RAG)**, pero con diferencias clave:

- **RAG convencional** (Lewis et al., 2020): Recupera fragmentos de un corpus único mediante embedding y los inyecta en el prompt de un LLM. BIRE extiende este paradigma con **dos sistemas de memoria independientes** y **expansión léxica** como complemento a la búsqueda vectorial.

- **Búsqueda híbrida** (véase Elasticsearch BM25 + dense vector): Combiene puntuaciones léxicas y semánticas. BIRE implementa esta hibridación pero con **funciones de puntuación adaptativas por origen de datos** (perfil recibe boost adicional).

- **Sistemas de expansión de consultas** (Rocchio, 1971; pseudo-relevance feedback): BIRE utiliza expansión basada en **diccionarios de dominio** en lugar de retroalimentación, lo que la hace determinista y sin dependencia de resultados intermedios.

- **Memoria dual** (inspirada en la neurociencia): La separación entre memoria semántica (hechos generales, proyectos) y memoria episódica/perfil (datos personales, eventos) refleja la distinción propuesta por Tulving (1972), pero implementada digitalmente con estrategias de indexación diferenciadas.

---

## 8. Limitaciones y Trabajo Futuro

### 8.1 Limitaciones Actuales

1. **Dependencia de diccionario estático (STEM_MAP)**: El STEM_MAP se define manualmente (~30 entradas) y no cubre todos los dominios. Parcialmente mitigado por la expansión por tags (v3.1) — que no requiere STEM_MAP — y por el auto-tagging (v3.2), que asigna tags automáticamente al persistir datos nuevos.
2. **Sin normalización de texto**: Tildes, diéresis y caracteres especiales pueden afectar la coincidencia en búsquedas ILIKE y trigramáticas. No se ha implementado normalización Unicode (NFD → ASCII).

### 8.2 Limitaciones Resueltas (Histórico)

Las siguientes limitaciones fueron abordadas en versiones posteriores y ya no aplican:

| Limitación original | Solución | Versión |
|---|---|---|
| **Falsos positivos vectoriales**: Consultas genéricas producían ruido semántico en `memoria_vectorial` | Ponderación híbrida calibrada α=0.3 (Sección 8.4) + re-ranking por agente activo (Sección 8.6). El peso léxico del 70% reduce el ruido semántico, y el re-ranking contextual del agente refina el orden final. | v3.2 / v3.5 |
| **Escalabilidad ILIKE ANY**: Escaneo secuencial sin límite fijo no escalaba a millones de registros | Índices GIN con pg_trgm (Sección 8.5) sobre `memoria_vectorial.contenido` y `memory_items.summary`. Búsqueda trigramática indexada con `similarity_threshold=0.2`. | v3.4 |
| **Tags inconsistentes**: Datos nuevos podían persistirse sin tags, quedando fuera de la expansión por tags | Auto-Tagging v1.0 (Sección 8.3): 17 reglas de tags + 16 reglas de categoría + detección automática de `memory_type`. Se invoca automáticamente en toda persistencia a `memory_items`. Los registros preexistentes sin tags pueden backfillearse con `hipocampo_backfill_embeddings.py`. | v3.2 |

### 8.3 Auto-Tagging v1.0 (Implementado en v3.2)

Para garantizar que todo `memory_items` reciba tags y categorías al persistir, se implementó un sistema de **clasificación automática por reglas** en el script `hipocampo_autotag.py`.

**Arquitectura:** El sistema analiza el campo `summary` mediante 17 reglas de expresiones regulares para tags y 16 reglas para categorías. Cada regla asocia patrones léxicos a tags/categorías predefinidos.

**Reglas de Tags (selección):**

| Patrón en summary | Tags asignados |
|-------------------|----------------|
| esposa, casado, hermana, cuñada, hijo, madre, padre | `familia` |
| planta, medicinal, hierba, malojillo, orégano, té | `plantas_medicinales` |
| azul, rojo, verde, amarillo, color, tono | `colores` |
| linux, ubuntu, servidor, docker, ssh | `servidores`, `linux` |
| python, javascript, php, postgres, sql | `programacion` |
| telegram, bot, chatbot | `programacion`, `telegram` |
| gym, ejercicio, entrenar, salud | `salud`, `fitness` |

**Reglas de Categoría (selección):**

| Patrón en summary | Categoría |
|-------------------|-----------|
| familia, esposa, hermano, cuñada, hijo | `relationships` |
| gusta, favorito, prefiere, encanta | `preferences` |
| proyecto, trabajo, código, sistema | `work_life` |
| nombre, llama, edad, vive | `personal_info` |

**Auto-detección de memory_type:** Si no se especifica, el sistema infiere `profile` cuando la categoría es `relationships`, `personal_info`, `goals`, `opinions` o `preferences`; en caso contrario asigna `event`.

**Integración:** El auto-tagging se invoca automáticamente en la **Opción B** (persistencia en `memory_items`), reemplazando la asignación manual de tags, categoría y `memory_type`. El script es importable como librería (`from hipocampo_autotag import auto_tag_full`) o ejecutable como CLI.

**Ventaja:** Elimina la inconsistencia de tags en datos nuevos, reduce el esfuerzo manual y garantiza que todo item nuevo sea encontrable por expansión por tags (Fase 5 de BIRE).

### 8.4 Ponderación Híbrida Calibrada v1.0 (Implementado en v3.2)

Para optimizar la combinación de búsqueda vectorial y léxica, se implementó un sistema de **calibración por validación cruzada** que encuentra los pesos óptimos para la fusión de resultados.

**Problema:** La fusión original usaba `max(score_vectorial, score_lexico)`, lo que ignoraba la contribución del método no dominante cuando ambos encontraban el mismo item, y no había forma de ajustar el balance semántico vs. textual.

**Solución:** Se implementó una función de fusión híbrida:

$$score_{final} = \alpha \cdot score_{vec} + (1-\alpha) \cdot score_{lex}$$

donde cada resultado mantiene sus puntuaciones vectorial y léxica por separado, y el score final es una combinación ponderada.

**Calibración (`hipocampo_calibrate.py`):** El script define un dataset etiquetado de 12 consultas con resultados esperados (ground truth), y ejecuta validación cruzada sobre α ∈ {0.0, 0.1, ..., 1.0} para maximizar F1-score:

| α | NDCG@10 | Precision@10 | Recall@10 | F1 |
|---|---------|-------------|-----------|-----|
| 0.0 | 0.9475 | 0.2333 | 1.7014 | 0.3997 |
| **0.3** | **1.1699** | **0.2917** | **2.2847** | **0.5058** |
| 0.5 | 1.0512 | 0.2917 | 2.2847 | 0.5058 |
| 0.7 | 1.0376 | 0.2917 | 2.2847 | 0.5058 |
| 1.0 | 0.7299 | 0.2000 | 1.7083 | 0.3548 |

**Resultado óptimo:** α = 0.3 (30% vectorial + 70% léxico). La configuración se persiste en `hipocampo_hybrid_config.json` y es cargada automáticamente por `hipocampo_search.py` en tiempo de ejecución.

**Ventaja:** La ponderación híbrida permite que:
- Resultados con alta coincidencia léxica (perfiles, eventos precisos) mantengan su relevancia.
- Resultados semánticos (proyectos técnicos, conceptos relacionados) contribuyan sin dominar.
- El balance puede recalibrarse en cualquier momento ejecutando `hipocampo_calibrate.py` de nuevo, a medida que crezca el dataset etiquetado.

### 8.5 Índices GIN con pg_trgm v1.0 (Implementado en v3.4)

Para acelerar la búsqueda textual y reemplazar el escaneo secuencial de `ILIKE ANY`, se implementaron **índices GIN con la extensión pg_trgm** sobre las columnas de texto de ambos subsistemas de memoria.

**Problema original:** Las búsquedas léxicas usaban `ILIKE ANY (ARRAY['%término%', ...])`, que requiere escaneo secuencial completo de la tabla. Para conjuntos de datos pequeños (<10⁴ registros) el costo es asumible (~30ms), pero no escala a millones de registros.

**Solución:** Se habilitó la extensión `pg_trgm` (Trigramas) y se crearon índices GIN con la clase de operador `gin_trgm_ops`:

```sql
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE INDEX idx_memoria_vectorial_contenido_gin
ON memoria_vectorial USING gin (contenido gin_trgm_ops);

CREATE INDEX idx_memory_items_summary_gin
ON memory_items USING gin (summary gin_trgm_ops);
```

**Mecanismo:** pg_trgm descompone el texto en secuencias de 3 caracteres (trigramas). Por ejemplo, "planta" genera los trigramas `{" pla", "plan", "lant", "anta", "nta "}`. El índice GIN almacena estos trigramas y permite búsquedas por similitud trigramática usando el operador `%`.

**Integración en BIRE:** Las funciones `buscar_lexico_memoria_vectorial` y `buscar_lexico_memory_items` se modificaron para:

1. **Ordenamiento por similitud trigramática**: `ORDER BY similarity(contenido, %s) DESC` reemplaza a `ORDER BY LENGTH(contenido) ASC`, mejorando el ranking de resultados.
2. **Puntuación aumentada con trigramas**: El score léxico ahora incorpora `similarity()` como factor:
   - `score_mv = match_ratio × 70 + trgm_sim × 20 + exact_bonus`
   - `score_mi = match_ratio × 55 + trgm_sim × 20 + profile_boost + exact_bonus`
3. **Umbral de similitud configurable**: `pg_trgm.similarity_threshold = 0.2` (vs default 0.3) para capturar más coincidencias parciales.

**Verificación de uso del índice (con `enable_seqscan=off`):**

```
Bitmap Index Scan on idx_memoria_vectorial_contenido_gin
  Index Cond: (contenido % 'planta'::text)
  Buffers: shared hit=15
  → 156 filas matching en 0.17ms (memoria_vectorial)

Bitmap Index Scan on idx_memory_items_summary_gin
  Index Cond: (summary % 'planta'::text)
  Buffers: shared hit=15
  → 27 filas matching en 0.04ms (memory_items)
```

**Nota importante:** PostgreSQL usa los índices GIN automáticamente cuando el tamaño de la tabla justifica el costo del index scan. Para tablas pequeñas (<682 registros), el planificador prefiere escaneo secuencial por su menor overhead. Los índices están listos para cuando la base de datos crezca a decenas de miles de registros.

### 8.6 Re-ranking por el Agente Activo v1.0 (Implementado en v3.5)

Para refinar el orden de los resultados más allá de la puntuación compuesta de BIRE, se implementó un paso de **re-ranking** opcional que delega el reordenamiento al agente de IA activo en la conversación (Claude).

**Problema:** La puntuación compuesta de BIRE (Fase 5) combina vectorial y léxico con pesos fijos, pero no captura la _intención semántica_ de la consulta. Por ejemplo, una búsqueda de "plantas medicinales" puede dar prioridad a resultados técnicos con alta coincidencia de tags sobre los registros de perfil que realmente contienen la información buscada.

**Solución:** En lugar de hacer llamadas a APIs externas, el script simplemente **marca los top resultados** con el flag `--rerank`, preservando los scores originales como `score_bire`. La salida incluye una línea **"RE-RANK PENDIENTE"** que indica al agente activo que debe re-ordenar los resultados según su criterio contextual.

**Flujo de re-ranking por agente activo:**

1. El script ejecuta BIRE normalmente y produce resultados ordenados por score compuesto.
2. Con `--rerank`, los top 15 resultados se marcan como pendientes de re-rank.
3. El agente activo (Claude) lee la salida y los resultados presentados.
4. Claude re-ordena los resultados mentalmente según relevancia contextual (entiende el query, conoce el perfil del usuario, tiene memoria de la conversación).

**Ventajas frente a re-ranking con API externa:**
- **Sin cuotas que agotar** — no depende de APIs de generación de texto
- **Mayor precisión contextual** — el agente activo tiene acceso a toda la conversación, no solo al query aislado
- **Sin latencia de red** — el reordenamiento es instantáneo
- **Sin costo de API** — cero llamadas externas

**Integración:** Se activa con el flag `--rerank`:

```bash
python3 scripts/hipocampo_search.py "plantas medicinales" --rerank
```

El output incluye `⚡ RE-RANK PENDIENTE` y `score_bire` preservado en cada resultado, permitiendo al agente comparar el orden original vs. su juicio de relevancia.

### 8.7 Embeddings Unificados 1024d v2.0 (Implementado en v3.7)

Para habilitar la **búsqueda vectorial cross-sistema** con el modelo `nvidia/nv-embedqa-e5-v5`, se unificaron ambos subsistemas de memoria a 1024 dimensiones y se migró desde Google Gemini a NVIDIA API.

**Problema original (v3.6):** Los embeddings se generaban con `gemini-embedding-001` (768d) vía `google-genai`. El MCP server truncaba los embeddings NVIDIA a 768d (`[:768]`), causando inconsistencia con los scripts que aún usaban Gemini.

**Solución (v3.7):**

**Paso 1 — Migración del modelo:** Todos los scripts migraron de `google-genai`/`gemini-embedding-001` a `openai`/`nvidia/nv-embedqa-e5-v5` (1024d nativos, sin truncado).

**Paso 2 — Migración del esquema:** Las columnas `embedding` en ambas tablas se ampliaron de `vector(768)` a `vector(1024)`, regenerando los índices HNSW:

```sql
ALTER TABLE memoria_vectorial ALTER COLUMN embedding TYPE vector(1024);
ALTER TABLE memory_items ALTER COLUMN embedding TYPE vector(1024);
```

**Paso 3 — Backfill de embeddings:** Los scripts `hipocampo_backfill_embeddings.py` y `hipocampo_backfill_vectorial.py` regeneran embeddings 1024d para los ~1,000 registros existentes, usando la NVIDIA API:

```python
client = OpenAI(
    base_url="https://integrate.api.nvidia.com/v1",
    api_key=os.getenv("NVIDIA_API_KEY"),
)
resp = client.embeddings.create(
    input=texto,
    model="nvidia/nv-embedqa-e5-v5",
    encoding_format="float",
    extra_body={"input_type": "query"},
)
embedding_1024d = resp.data[0].embedding
```

**Resultado:** Ambos subsistemas comparten el mismo espacio de embeddings 1024d via NVIDIA API, eliminando la dependencia de Google Gemini y unificando la dimensionalidad en 1024.

---

## 9. Conclusiones

Hemos presentado **Hipocampo**, un sistema de memoria dual para asistentes de IA, y **BIRE**, un algoritmo de búsqueda integrada que resuelve el problema de la recuperación incompleta en sistemas con múltiples fuentes de información heterogéneas.

Las contribuciones principales son:

1. **Arquitectura de memoria dual** que separa técnica y perfil con estrategias de indexación diferenciadas.
2. **Expansión léxica de consultas** mediante diccionarios de dominio que aumenta la cobertura de búsqueda sin depender de modelos de lenguaje.
3. **Puntuación compuesta adaptativa** que prioriza datos de perfil cuando corresponde.
4. **Corte dinámico por relevancia** que elimina el límite fijo de resultados.
5. **Índices GIN con pg_trgm**: Indexación trigramática de texto completo para búsqueda léxica acelerada, con ordenamiento por similitud trigramática.
6. **Re-ranking por agente activo**: Paso opcional de reordenamiento delegado al agente de IA (Claude), que evita APIs externas y aprovecha el contexto conversacional completo para mayor precisión.
7. **Embeddings unificados 1024d**: Estandarización de ambos subsistemas al mismo modelo y dimensionalidad (`nvidia/nv-embedqa-e5-v5` con 1024d), permitiendo búsqueda vectorial cross-sistema sobre 900+ registros.
8. **Ponderación híbrida calibrada**: Fusión de puntuaciones vectoriales y léxicas con pesos α=0.3 optimizados mediante validación cruzada sobre 12 consultas etiquetadas.
9. **Auto-Tagging v1.0**: Sistema de clasificación automática por reglas que asigna tags, categoría y tipo de memoria al persistir, eliminando la necesidad de etiquetado manual.
10. **Validación empírica** que demuestra recuperación del 100% de registros relevantes versus 20% con el enfoque ingenuo.

BIRE demuestra que, para sistemas de memoria personal con escala moderada (<10⁴ registros), una combinación juiciosa de expansión léxica determinista y búsqueda vectorial supera significativamente a ambas estrategias por separado.

---

## 10. Instalación y Construcción

### 10.1 Estructura del Proyecto

```
hipocampo/
├── SKILL.md                          ← Skill para el agente (instrucciones operativas)
├── esquema.sql                       ← DDL completo de la base de datos
├── requirements.txt                  ← Dependencias Python
├── .env.example                      ← Template de variables de entorno
│
├── scripts/
│   ├── hipocampo_search.py           ← BIRE v3.7 — Motor de búsqueda unificada
│   ├── hipocampo_autotag.py          ← Auto-Tagging v1.0 — Clasificación por reglas
│   ├── hipocampo_calibrate.py        ← Calibración de ponderación híbrida (α)
│   ├── hipocampo_backfill_embeddings.py  ← Backfill de embeddings 1024d
│   ├── hipocampo_hybrid_config.json  ← Config óptima de α (calibrada)
│   ├── mm_brain_tool.py              ← Persistencia en memoria_vectorial + Freeplane XML
│   ├── query_brain.py                ← Consulta directa a memoria_vectorial
│   └── cleanup_brain.py              ← Mantenimiento y limpieza
│
└── docs/
    └── hipocampo_paper.md            ← Este documento (arquitectura y algoritmo)
```

### 10.2 Prerrequisitos

| Componente | Versión | Propósito |
|-----------|---------|-----------|
| PostgreSQL | 17+ | Base de datos principal |
| pgvector | 0.4+ | Indexación y búsqueda vectorial (HNSW) |
| pg_trgm | (incluido en contrib) | Búsqueda textual con trigramas (GIN) |
| Python | 3.13+ | Scripts de persistencia y búsqueda |
| NVIDIA API Key | — | Generación de embeddings (`nvidia/nv-embedqa-e5-v5`) |
| psycopg2 | 2.9+ | Conexión Python-PostgreSQL |
| openai | 2.0+ | Cliente NVIDIA |

### 10.3 Instalación Paso a Paso

#### 1. Crear la base de datos y extensiones

```sql
CREATE DATABASE hipocampo_db;
\c hipocampo_db

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
```

#### 2. Ejecutar el esquema DDL

```sql
-- memoria_vectorial — Recuerdos técnicos con embedding semántico
CREATE TABLE memoria_vectorial (
    id BIGSERIAL PRIMARY KEY,
    contenido TEXT,
    metadatos JSONB,
    embedding VECTOR(1024),
    code_snippet TEXT
);

CREATE INDEX idx_memoria_vectorial_contenido_gin
    ON memoria_vectorial USING GIN (contenido gin_trgm_ops);

CREATE INDEX idx_memoria_vectorial_embedding
    ON memoria_vectorial USING HNSW (embedding vector_cosine_ops);

-- memory_items — Perfil del usuario, eventos y relaciones
CREATE TABLE memory_items (
    id VARCHAR PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resource_id VARCHAR REFERENCES resources(id) ON DELETE CASCADE,
    memory_type VARCHAR NOT NULL,  -- 'profile' | 'event' | 'decision'
    summary TEXT NOT NULL,
    happened_at TIMESTAMP,
    extra JSONB,
    user_id VARCHAR,
    embedding VECTOR(1024)
);

CREATE INDEX idx_memory_items_summary_gin
    ON memory_items USING GIN (summary gin_trgm_ops);

CREATE INDEX idx_memory_items_embedding
    ON memory_items USING HNSW (embedding vector_cosine_ops);

-- memory_categories — Taxonomía de 10 categorías
CREATE TABLE memory_categories (
    id VARCHAR PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    name VARCHAR NOT NULL,
    description TEXT NOT NULL,
    embedding VECTOR,
    summary TEXT,
    user_id VARCHAR
);

-- category_items — Relación M:N entre items y categorías
CREATE TABLE category_items (
    id VARCHAR PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    item_id VARCHAR NOT NULL REFERENCES memory_items(id) ON DELETE CASCADE,
    category_id VARCHAR NOT NULL REFERENCES memory_categories(id) ON DELETE CASCADE,
    user_id VARCHAR
);

-- resources — Archivos/URLs referenciados
CREATE TABLE resources (
    id VARCHAR PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    name VARCHAR NOT NULL,
    description TEXT NOT NULL,
    url VARCHAR NOT NULL DEFAULT '',
    extra JSONB,
    user_id VARCHAR
);
```

#### 3. Poblar las categorías

```sql
INSERT INTO memory_categories (id, name, description, user_id) VALUES
    (gen_random_uuid()::text, 'personal_info',   'Nombre, edad, ubicación, datos básicos', 'usuario_ejemplo'),
    (gen_random_uuid()::text, 'relationships',   'Familia, esposa, pareja, amigos', 'usuario_ejemplo'),
    (gen_random_uuid()::text, 'preferences',     'Gustos, preferencias, likes/dislikes', 'usuario_ejemplo'),
    (gen_random_uuid()::text, 'habits',          'Rutinas, costumbres', 'usuario_ejemplo'),
    (gen_random_uuid()::text, 'goals',           'Metas, aspiraciones', 'usuario_ejemplo'),
    (gen_random_uuid()::text, 'knowledge',       'Conocimientos adquiridos', 'usuario_ejemplo'),
    (gen_random_uuid()::text, 'opinions',        'Opiniones del usuario', 'usuario_ejemplo'),
    (gen_random_uuid()::text, 'work_life',       'Trabajo, vida profesional', 'usuario_ejemplo'),
    (gen_random_uuid()::text, 'activities',      'Actividades, hobbies', 'usuario_ejemplo'),
    (gen_random_uuid()::text, 'experiences',     'Experiencias pasadas', 'usuario_ejemplo');
```

#### 4. Crear el entorno virtual e instalar dependencias

```bash
python3 -m venv hipocampo_venv
source hipocampo_venv/bin/activate
pip install psycopg2-binary pgvector python-dotenv openai
```

**`requirements.txt`:**
```
psycopg2-binary>=2.9
pgvector>=0.4
python-dotenv>=1.0
openai>=2.0
lxml>=5.0
```

#### 5. Configurar variables de entorno

Crear `.env`:
```bash
# .env
DB_PASSWORD=tu_password_postgres
NVIDIA_API_KEY=tu_nvidia_api_key
```

#### 6. Verificar la instalación

```bash
# Probar conexión a la base de datos
python3 -c "
import psycopg2, os
from dotenv import load_dotenv
load_dotenv('.env')
conn = psycopg2.connect(dbname='hipocampo_db', user='tu_usuario_postgres', password=os.getenv('DB_PASSWORD'), host='localhost')
cur = conn.cursor()
cur.execute('SELECT COUNT(*) FROM memoria_vectorial')
print(f'memoria_vectorial: {cur.fetchone()[0]} registros')
cur.execute('SELECT COUNT(*) FROM memory_items')
print(f'memory_items: {cur.fetchone()[0]} registros')
cur.close()
conn.close()
"

# Probar búsqueda BIRE
python3 scripts/hipocampo_search.py "prueba de instalación"
```

### 10.4 Dependencias del Sistema

| Package | Versión mínima | Propósito |
|---------|---------------|-----------|
| `psycopg2-binary` | 2.9 | Conexión PostgreSQL |
| `pgvector` | 0.4 | Soporte `vector(1024)` + HNSW |
| `python-dotenv` | 1.0 | Carga de `.env` |
| `openai` | 2.0 | Cliente OpenAI/NVIDIA |
| `lxml` | 5.0 | Parseo XML Freeplane (mm_brain_tool) |

### 10.5 Cómo está construido el Skill

El skill de Hipocampo (el archivo `SKILL.md` que usa el agente) se compone de:

1. **SKILL.md** — Instrucciones operativas para el agente de IA. Define el protocolo en 3 fases:
   - **Pre-actuación**: Buscar en ambos sistemas usando BIRE antes de responder
   - **Ejecución**: Elegir el destino de persistencia según tipo de dato
   - **Post-actuación**: Persistir la información en el subsistema correcto

2. **Scripts Python** — Implementan la lógica real:
   - `hipocampo_search.py` — Algoritmo BIRE completo (expansión + búsqueda dual + puntuación compuesta + tags)
   - `hipocampo_autotag.py` — Clasificación automática por reglas de expresión regular
   - `hipocampo_calibrate.py` — Validación cruzada para encontrar α óptimo
   - `mm_brain_tool.py` — Persistencia dual (PostgreSQL + XML Freeplane)

3. **Base de datos PostgreSQL+pgvector** — Almacenamiento persistente con:
   - Índices HNSW para búsqueda vectorial O(log n)
   - Índices GIN+pg_trgm para búsqueda textual acelerada
   - Embeddings unificados 1024d en ambos subsistemas

### 10.6 Flujo de Integración con el Agente

```
Usuario pregunta → Agente activa SKILL.md
                          ↓
               Fase 1: BIRE search (hipocampo_search.py)
                          ↓
               ¿Hay datos relevantes? ──Sí──→ Informa al usuario
                          │ No
                          ↓
               Fase 2: Ejecuta acción
                          ↓
               Fase 3: Persiste resultado
                 ├── Técnico → mm_brain_tool.py
                 └── Perfil  → hipocampo_autotag.py + SQL directo
```

---

## Referencias

- Lewis, P., et al. (2020). *Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks*. NeurIPS.
- Tulving, E. (1972). *Episodic and Semantic Memory*. In Organization of Memory.
- Rocchio, J. J. (1971). *Relevance Feedback in Information Retrieval*. In The SMART Retrieval System.
- PostgreSQL Global Development Group. *PostgreSQL 17 Documentation*. https://www.postgresql.org/docs/17/
- pgvector. *Open-source vector similarity search for PostgreSQL*. https://github.com/pgvector/pgvector
- NVIDIA. *NV-EmbedQA-E5-V5*. https://build.nvidia.com/nvidia/nv-embedqa-e5-v5
- PostgreSQL pg_trgm. *Trigram-based text search for PostgreSQL*. https://www.postgresql.org/docs/17/pgtrgm.html

---

*Documento generado el 24 de mayo de 2026. Actualizado junio 2026. Sistema Hipocampo — BIRE v3.7 (Re-rank por Agente + Embeddings Unificados NVIDIA 1024d + GIN+pg_trgm + Híbrido α=0.3 + Auto-Tagging).*
