# 4 Mejoras de Seguridad y Resiliencia — Plan de Implementación

> **Goal:** Hardening del MCP Hipocampo: caducidad de reglas automáticas, checkpoint con snapshot, validación inmunológica Nivel 4, y grafo orgánico.

**Architecture:** 4 features independientes que tocan `hipocampo_mcp_server.py`, `hipocampo_checkpoint.py`, y esquema DB.

**Tech Stack:** Python + FastMCP + PostgreSQL 17 + pgvector

---

## Feature 1: Caducidad y revisión para reglas `automatica`

**Objetivo:** Las reglas `automatica` son permanentes y nunca se comprimen — riesgo de envenenamiento por inyección. Añadir mecanismo de cuarentena + revisión.

**Archivos:**
- Modify: `scripts/hipocampo_mcp_server.py`

**Migración DB:**
```sql
ALTER TABLE memoria_vectorial ADD COLUMN IF NOT EXISTS expires_at TIMESTAMPTZ;
ALTER TABLE memoria_vectorial ADD COLUMN IF NOT EXISTS review_count INTEGER DEFAULT 0;
```

**Herramientas MCP nuevas:**
- `review_automatica(max_age_days=30, dry_run=True)` → lista reglas `automatica` sin revisar en N días. Con `dry_run=False`, degrada reglas viejas a `semantica` (no se borran, solo pierden inmunidad de compresión).
- Añadir campo `review_count` incrementado cada vez que un agente dispara un trigger que menciona esa regla como útil. Si una regla `automatica` no recibe `review_count++` en 60 días → auto-degradar a `semantica`.

**Cambios en `save_hipocampo`:**
- Si `nivel="automatica"`, setear `expires_at = NOW() + INTERVAL '90 days'` (no se borra automáticamente, pero se marca para revisión).
- Loggear warning en server cuando se crea una regla `automatica` (para auditoría).

**Lógica en búsqueda/trigger:**
- Cuando un trigger dispara (ej: `search_hipocampo("trigger:sgv trigger:php")`), si encuentra regla `automatica` útil, incrementar `review_count` con `UPDATE memoria_vectorial SET metadatos = jsonb_set(metadatos, '{review_count}', ...) WHERE id=N`.

**Tests:**
- `test_automatica_expiry.py`: crea regla, simula 91 días, verify que `review_automatica` la detecta.

**Líneas estimadas:** ~80 en mcp_server, ~30 test.

---

## Feature 2: Sistema Inmunológico Nivel 4 — Loop de validación

**Objetivo:** El snapshot pre-cambio + regla post-rotura (ya implementado conceptualmente en AGENTS.md) necesita validación: ¿la regla inmunológica es correcta o generó un antibiótico falso?

**Archivos:**
- Modify: `scripts/hipocampo_mcp_server.py`

**Nueva tool:** `validate_immune_rule(rule_id: int) -> str`
1. Toma una regla `automatica` creada como "REGLA INMUNOLÓGICA: Editar X rompió Y. Causa: Z. Solución: W."
2. Busca en `memory_links` si hay snapshots pre-cambio o post-cambio vinculados.
3. Busca en el grafo si hay reglas contradictorias (ej: dos reglas que dicen cosas opuestas sobre el mismo archivo).
4. Si encuentra contradicción → marcar ambas con `metadatos->>'conflict' = true` y devolver warning.
5. Si la regla tiene >30 días y 0 enlaces entrantes → sugerir degradar a `semantica`.

**Cambios en save_hipocampo:**
- Si `nivel="automatica"` Y contenido contiene "REGLA INMUNOLÓGICA" → buscar automáticamente snapshots pre-cambio vinculados por filename y crear `memory_links` con `relation_type='validates'`.
- Añadir `relation_type='contradicts'` si se detecta conflicto.

**Líneas estimadas:** ~60 en mcp_server, ~25 test.

---

## Feature 3: Snapshot pre-checkpoint

**Objetivo:** El checkpoint `--force` INSERTA checkpoints sin borrar originales (no destructivo hoy), pero si algún día se añade DELETE, necesitamos snapshot previo. Implementar ahora como red de seguridad.

**Archivos:**
- Modify: `scripts/hipocampo_checkpoint.py`
- Modify: `scripts/hipocampo_mcp_server.py`

**Cambios:**
1. Antes de INSERT checkpoint, guardar snapshot de los IDs originales en un registro `memoria_vectorial` tipo `checkpoint_snapshot`:
   ```json
   {"tipo": "checkpoint_snapshot", "original_ids": [1,2,3], "escala": "7d", "fecha": "..."}
   ```
2. Añadir tool `rollback_checkpoint(snapshot_id: int)` que, dado un snapshot, re-inserta los originales desde el snapshot (si fueron borrados) o advierte que los originales aún existen.
3. Modificar `hipocampo_checkpoint(dry_run=False)` para que, si detecta que hay DELETE de originales, primero guarde snapshot. Por ahora: solo el snapshot, sin DELETE.
4. El snapshot se guarda con `nivel="episodica"` y categoría `checkpoint_snapshot` para que eventualmente se comprima (no necesitamos snapshots de hace 6 meses).

**Cambios en `hipocampo_mcp_server.py`:**
- Exponer `rollback_checkpoint` como tool MCP.

**Líneas estimadas:** ~40 checkpoint, ~30 mcp_server, ~20 test.

---

## Feature 4: Grafo orgánico (fix bugs + auto-enlace)

**Objetivo:** El grafo tiene 7 enlaces en 2229 recuerdos. Arreglar `auto_link` y hacer que `graph_hipocampo` cruce con `memory_items`.

**Bugs a arreglar:**

### Bug A: `save_hipocampo.auto_link` (línea 654-687) — conn cerrado
- **Causa:** `conn.close()` línea 648; `auto_link` línea 658 reabre `cur = conn.cursor()` sobre conn cerrado.
- **Fix:** Mover el cierre de `conn` DESPUÉS del bloque `auto_link`, o reabrir conexión fresca para auto_link.

### Bug B: `auto_link` usa `get_embedding(content)` (línea 656) — no existe
- **Fix:** Cambiar a `_generar_embedding(content, "auto_link")`.

### Bug C: `graph_hipocampo._fetch_content` (línea 1623) — type mismatch
- **Causa:** `memory_items.id` es VARCHAR(UUID) pero `rid` es int.
- **Fix:** Intentar primero `memoria_vectorial WHERE id=%s` (int), si no hay resultado, intentar `memory_items WHERE id=%s::text` (con str(rid) para UUIDs que podrían ser numéricos en memoria_vectorial). Mejor: separar la lógica en dos queries explícitas, no asumir que el fallo en una implica la otra.

**Cambios adicionales para grafo orgánico:**
- `save_hipocampo`: al guardar con `auto_link=True`, también enlazar con `memory_items` que tengan similitud semántica (no solo `memoria_vectorial`). Para eso hay que generar embedding del contenido y comparar contra `memory_items.embedding`.
- `link_hipocampo`: permitir `source_id` y `target_id` que referencien `memory_items` (hoy solo funciona con `memoria_vectorial` IDs numéricos). Solución: aceptar string IDs y detectar tipo por formato (UUID → memory_items, int → memoria_vectorial).
- `graph_hipocampo._list_all()`: mostrar también nodos de `memory_items` que tengan links.

**Archivos:**
- Modify: `scripts/hipocampo_mcp_server.py`

**Líneas estimadas:** ~100 en mcp_server, ~40 test.

---

## Ejecución

Orden recomendado:
1. **Feature 4** (grafo + bugs) — crítico, los bugs rompen funcionalidad existente.
2. **Feature 1** (caducidad automatica) — protección contra envenenamiento.
3. **Feature 3** (snapshot checkpoint) — red de seguridad, bajo riesgo.
4. **Feature 2** (validación inmunológica) — depende de Features 1 + 4 funcionando.

Total estimado: ~280 líneas código + ~115 líneas tests = ~400 líneas.

**Verificación post-implementación:**
```bash
systemctl --user restart hipocampo-mcp.service
cd /home/alex/.hipocampo/repo && .hipocampo/venv/bin/python -m pytest tests/ -x -q
```
