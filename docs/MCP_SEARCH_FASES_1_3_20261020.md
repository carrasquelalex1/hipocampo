# MCP Hipocampo — Fases 1-3 de búsqueda (2026-10-20)

Implementación y despliegue de recuperación estructurada, resúmenes/tsvector y chunks para el MCP de Hipocampo. El objetivo fue sacar al vector del camino crítico de `code`, categorías, ID, fecha y nivel, y reducir la latencia y el ruido del ranking.

> Estado: **commiteado** en `~/.hipocampo/repo` — local `d5ec27b`, servidor remoto `5bca72d` (árbol idéntico `5fcc4da`); sin push. Desplegado en local y en el servidor remoto el 2026-10-20.

## 1. Qué cambió

### Fase 1 — Recuperación estructurada

- Filtros por argumentos: `code`, `categories`, `nivel`, `memory_type`, `ids`, `created_after`, `created_before`, `include_pending`.
- Sintaxis en la consulta: `code:`, `category:`, `nivel:`, `type:`, `id:`/`#`, `after:`/`since:`/`before:`, frases entre comillas.
- `get_hipocampo(id, format)` para traer una memoria exacta sin ranking.
- Índices: GIN sobre `metadatos` (`jsonb_path_ops`), expresión `lower(metadatos->>'code')`, nivel y fecha.
- El canal estructurado solo se activa con identificadores específicos (`_`/`-`), un token exacto de `code` o `trigger:xxx`; no con palabras naturales que coinciden parcialmente con categorías.
- Paginación con `offset`; salida compacta por defecto (`format="compact"`), `full` conserva el formateador histórico y `json` devuelve IDs, scores, snippet, summary, canales y motivos.

### Fase 2 — Summary + tsvector

- `memoria_vectorial.summary` (resumen extractivo) y `summary_embedding` (1024d, opcional).
- `memoria_vectorial.contenido_tsv` generada con `to_tsvector('spanish', contenido)` e índice GIN.
- El summary se embebe aparte para que un recuerdo largo no se diluya en un único vector.
- Boosts:
  - Frase completa de la consulta: +20 y sin decaimiento temporal.
  - Proximidad de conceptos (sinónimos incluidos): hasta +30, con recorte del pasaje a una línea/frase legible.
  - Penalización a reglas/meta-documentos que solo citan la consulta entre comillas o backticks (si todas las apariciones están delimitadas; si también aparece sin delimitar, no se penaliza).
- `rerank` pasa a `"auto" | "always" | "never"`:
  - `auto` solo re-rankea si el top es débil o está empatado (score <90, gap <6, sin proximidad fuerte ni frase exacta).
  - `always` usa TypeSafe → classifier con presupuesto HTTP (`rerank_budget_ms`, default 800) y cache de 300 s.
  - `never` no hace la llamada extra.
- Factor de mezcla `0.5 + 0.5·noul`: el juez puede reordenar, no anular la señal léxica.

### Fase 3 — Chunks de recuerdos largos

- Tabla `memoria_vectorial_chunks`:
  - `parent_id` con `ON DELETE CASCADE`, `chunk_index`, `contenido`, `embedding vector(1024)`, `contenido_tsv` generada.
  - Único `(parent_id, chunk_index)`; índice por padre, HNSW de embedding, GIN trigram y GIN tsvector.
- Agregación por memoria padre: el padre se devuelve una vez con el mejor chunk como pasaje.
- El canal léxico de chunks usa `to_tsquery('spanish', 't1 | t2 | …')` sobre el GIN, no `ILIKE ANY` con stopwords. Medido: ~15-50 ms para 4.325 chunks (antes ~1,9 s por Seq Scan + `similarity`).
- Score de chunks acotado a 45: es un canal de rescate, no debe superar a una memoria que contiene los conceptos juntos (proximidad) ni inundar el top con 100.
- Al guardar/actualizar se generan summary y chunks en background; los embeddings auxiliares están **apagados por defecto** para no saturar Ollama CPU (en CPU un embedding de summary/chunk puede tardar ~68 s y compite con la consulta). Se activan con `HIPOCAMPO_SUMMARY_EMBED=1` / `HIPOCAMPO_CHUNK_EMBED_MAX>0` o con el backfill offline.

## 2. API

```python
search_hipocampo(
    query="transcript temporal eliminado",
    code="", categories=None, nivel="", memory_type="",
    ids=None, created_after="", created_before="",
    include_pending=True,
    rerank="auto",          # "auto" | "always" | "never" (bool antiguo aceptado)
    rerank_top_k=8, rerank_budget_ms=800,
    k=5, offset=0,
    format="compact",       # "compact" | "full" | "json"
    snippet_chars=300, include_scores=False, explain=False,
)
```

Ejemplos:

```python
search_hipocampo(query="transcript temporal eliminado")
# → #4039 primero, con motivo "léxico, proximidad"

search_hipocampo(query="", code="opencode_session_forensics")
search_hipocampo(query="duplicados", created_after="2026-10-20")
search_hipocampo(query="", ids=[909])
search_hipocampo(query="modal duplicado", offset=1, k=2)
get_hipocampo(id="#909", format="compact")
get_hipocampo(id="vmi<uuid>", format="json")
```

`quick_hipocampo_search` es un alias con los mismos argumentos.

## 3. Migración y backfill

Respaldo previo obligatorio (regla 0.1). Migración idempotente:

```bash
python3 scripts/hipocampo_backfill_summary_chunks.py --dry-run
python3 scripts/hipocampo_backfill_summary_chunks.py
# opcional, lento en CPU:
python3 scripts/hipocampo_backfill_summary_chunks.py --ids 4039,4040 --embed-summaries --embed-chunks
```

Aplicación en una BD existente:

```bash
psql -h "$DB_HOST" -U "$DB_USER" -d "$DB_NAME" -v ON_ERROR_STOP=1 -1 \
  -f scripts/migrate_mcp_mejoras_20261020.sql
```

`scripts/setup_database.sql` incluye el esquema para instalaciones nuevas.

## 4. Evaluación

Set: `tests/eval_search_cases.json` (17 casos locales) y `scripts/hipocampo_eval_search.py`.

```bash
PYTHONPATH=.:scripts python3 scripts/hipocampo_eval_search.py --rerank never --k 5
PYTHONPATH=.:scripts python3 scripts/hipocampo_eval_search.py --rerank auto --k 5
```

Resultados locales:

| Versión | Recall@5 | MRR@5 | Top-1 |
|---|---:|---:|---:|
| Código anterior (HEAD) | 0,824 | 0,765 | 0,706 |
| Nuevo, `rerank=never` | 1,000 | 1,000 | 1,000 |
| Nuevo, `rerank=auto` | 1,000 | 1,000 | 1,000 |

Servidor remoto (8 casos reales del corpus, `tests/eval_search_cases_server` en `/tmp/opencode`):

| Métrica | Valor |
|---|---:|
| Recall@5 | 1,000 |
| MRR@5 | 0,917 |
| Top-1 | 0,875 |

El caso `duplicados exactos proyecto interno 29 campos` aparece en #3 (Recall@5 sí; MRR baja el promedio); el resto es Top-1. Latencias del servidor: 0,4-1,1 s.

## 5. Rendimiento: causas y arreglos

| Problema | Causa | Arreglo |
|---|---|---|
| Ranking ruidoso | `expandir_consulta` hacía `substring` con stopwords: `"el"` está dentro de `"eliminar"` y expandía a borrar/eliminar/suprimir | Solo subcadena con tokens/raíces de ≥4 letras y fuera de stopwords |
| Chunks lentos (~1,9 s) | `ILIKE ANY` incluía `%de%`, `%el%`, `%en%` → Seq Scan + `similarity` sobre 4.325 chunks | `to_tsquery` OR sobre términos fuertes + GIN |
| Léxico MV lento (~1,5 s) | Traía 500-1.200 filas y calculaba pasajes para todas | `LIMIT 200`; memory_items `LIMIT 120` |
| Auto-rerank añadía latencia | Re-rankeaba casi toda consulta multi-palabra | Gating: no si top ≥90, frase exacta, proximidad fuerte o ganador claro |
| Chunks dominaban el top | Score 100 para muchos chunks | Cap 45, fórmula `30 + rank·60 + cobertura·10` |
| Embeddings de chunks saturaban Ollama | 40 por guardado | Default 0 (opt-in); el canal léxico ya funciona |

## 6. Flags de entorno

| Flag | Default | Efecto |
|---|---|---|
| `HIPOCAMPO_TAG_EXPANSION` | `0` | `1` reactiva el rescate por tags cuando hay <5 resultados (score 20, hasta 5) |
| `HIPOCAMPO_SUMMARY_EMBED` | `0` | `1` genera el embedding del summary al guardar (CPU: ~68 s) |
| `HIPOCAMPO_CHUNK_EMBED_MAX` | `0` | Máximo de embeddings de chunks por guardado; `0` = solo texto/léxico |
| `HIPOCAMPO_RERANK_CACHE_TTL` | `300` | TTL del cache de juicios de rerank (segundos) |
| `HIPOCAMPO_LEXICO_GIN` | `1` | `0` vuelve al léxico anterior sin GIN |
| `HIPOCAMPO_PREFILTRO` | `1` | `0` apaga el pre-filtro de contenido idéntico al guardar |

## 7. Despliegue 2026-10-20

- Respaldo servidor: `ruta-interna-omitida (4,9 MB, `gzip -t` y `pg_restore -l` OK).
- Respaldo de código: `.../hipocampo_code_pre_mejoras_mcp_20261020_144230.tar.gz`.
- Migración aplicada y re-ejecutada (idempotente) en PostgreSQL 15.19 del servidor.
- Backfill: 821 summaries, 137 chunks; 0 embeddings auxiliares (texto por defecto).
- `hipocampo-mcp.service` reiniciado; 40 tools vivas, incluida `get_hipocampo`.
- Smoke E2E: save/update/delete de un recuerdo ZZTEST (summary 585 chars, 3 chunks, borrado en cascada), filtros `code`/`categories`/`ids`/`created_after`/`nivel`, paginación, `format=compact|json|full`, `rerank=always` y `get_hipocampo` con `#909`/`v909`.
- Se endureció `~/.hipocampo/.env` del servidor a `600` (el test `test_secrets_hygiene` lo exigía; antes 664).
- Tests: 176 passed, 14 deselected en local y servidor.

## 8. Deudas y notas

- Los embeddings de summary/chunks del backfill quedaron en 0; los canales semánticos de summary/chunk funcionarán cuando se ejecute el backfill con `--embed-summaries --embed-chunks` o cuando se activen `HIPOCAMPO_SUMMARY_EMBED=1` / `HIPOCAMPO_CHUNK_EMBED_MAX>0`. En CPU cada embedding extra puede tardar ~68 s y compite con la consulta; por eso el default es 0. El canal léxico ya funciona.
- `rerank="always"` puede degradar casos donde el juez solo ve el inicio de un recuerdo largo; el default `auto` evita ese caso con el gating por proximidad/frase/score. Si se necesita máximo recall, usar `never` y revisar el top.
- Los cambios no están commiteados. Antes de commitear: revisar el diff, excluir `.bak_*` y `hipocampo_search.php` (no forman parte de esta fase), y actualizar el README si se publica la nueva firma.
