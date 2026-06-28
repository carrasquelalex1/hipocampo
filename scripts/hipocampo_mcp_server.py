#!/usr/bin/env python3
"""Hipocampo MCP Server v3.8 — Async MCP Native con FastMCP

Expone el motor de búsqueda BIRE v3.7 como herramientas (tools) del
Model Context Protocol. Compatible con Claude Desktop, OpenCode y cualquier
cliente MCP.

Transportes soportados:
  stdio (por defecto)     → Para clientes locales (Claude Desktop, etc.)
  http (--http)           → Streamable HTTP (recomendado para remoto)
                            ╰ Single endpoint /mcp (POST + GET)
  sse (--sse)             → SSE (deprecado, solo compatibilidad)

Referencia:
  - Streamable HTTP reemplaza a SSE desde spec MCP 2025-03-26
  - https://spec.modelcontextprotocol.io

Ejemplos:
    python hipocampo_mcp_server.py
    python hipocampo_mcp_server.py --http 8001
    python hipocampo_mcp_server.py --http 8001 --host 0.0.0.0
    python hipocampo_mcp_server.py --sse 8001        # legacy
"""

import asyncio
import logging
import sys
import os
import json
from datetime import date

import uuid

import psycopg2
import urllib.request
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.server import ToolAnnotations

# ─── CONFIGURACIÓN ─────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.dirname(BASE_DIR))  # project root for hipocampo package


from hipocampo.db import get_conn, get_embedding, init_pool, validate_config
from hipocampo.rate_limit import embedding_limiter, tool_limiter

import hipocampo_search as _search
import hipocampo_health as _health
import hipocampo_stats as _stats
import hipocampo_dedup as _dedup
import hipocampo_checkpoint as _checkpoint

WATCHES_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS watches (
    id SERIAL PRIMARY KEY,
    pattern TEXT NOT NULL,
    webhook_url TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_triggered_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_watches_pattern ON watches(pattern);
"""


def _init_watches_table():
    try:
        conn = _conn()
        cur = conn.cursor()
        for stmt in WATCHES_TABLE_SQL.split(";"):
            if stmt.strip():
                cur.execute(stmt)
        conn.commit()
        cur.close()
        conn.close()
    except psycopg2.Error as e:
        logger.warning("DB error al inicializar tabla watches: %s", e)
    except Exception as e:
        logger.warning("Error inesperado al inicializar tabla watches: %s", e)


def _fire_webhooks(event_type: str, record_id, content: str, metadatos: dict):
    try:
        conn = _conn()
        cur = conn.cursor()
        content_lower = (content or "").lower()
        meta_str = json.dumps(metadatos).lower()
        cur.execute("SELECT id, pattern, webhook_url FROM watches")
        for row in cur.fetchall():
            wid, pattern, url = row
            if pattern.lower() in content_lower or pattern.lower() in meta_str:
                payload = json.dumps(
                    {
                        "event": event_type,
                        "id": record_id,
                        "content": content,
                        "metadatos": metadatos,
                    }
                ).encode("utf-8")
                try:
                    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
                    urllib.request.urlopen(req, timeout=5)
                    cur.execute("UPDATE watches SET last_triggered_at = NOW() WHERE id = %s", (wid,))
                    conn.commit()
                    logger.info("Webhook %d disparado -> %s", wid, url)
                except urllib.error.URLError as e:
                    logger.warning("Webhook %d falló (red) (%s): %s", wid, url, e)
                except Exception as e:
                    logger.warning("Webhook %d falló (inesperado) (%s): %s", wid, url, e)
        cur.close()
        conn.close()
    except psycopg2.Error as e:
        logger.warning("DB error en webhooks: %s", e)
    except Exception as e:
        logger.warning("Error inesperado en webhooks: %s", e)


# ─── INICIALIZACIÓN MCP ─────────────────────────────────────────────────────
mcp = FastMCP("hipocampo")


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
    )
)
async def search_hipocampo(query: str, session_id: str = "") -> str:
    """
    Busca en el Hipocampo (memoria dual con SSC / BIRE v3.6).

    Es solo lectura — no modifica datos, no tiene efectos secundarios.
    Sin límites de tasa (rate limits).

    Realiza búsqueda semántica + léxica híbrida en las bases de datos de
    memoria del usuario, incluyendo memoria técnica (*memoria_vectorial*) y
    de perfil (*memory_items*).

    Si se proporciona session_id, filtra solo memorias de esa sesión.

    Para búsquedas rápidas cuando el nombre corto sea preferido, usar
    quick_hipocampo_search (alias idéntico). Esta herramienta es la
    versión completa con nombre descriptivo.

    Args:
        query: Texto de búsqueda en lenguaje natural. Máximo 500 caracteres.
               Ejemplos: "proyecto contable", "perro", "planta medicinal",
               "API REST en Python", "gusta del té".
        session_id: Opcional. Filtra resultados a una sesión específica.

    Returns:
        Resultados formateados del BIRE como texto plano.
        Incluye: contenido encontrado, scores de relevancia, y metadatos.
        Si no hay coincidencias, indica búsqueda exitosa pero sin resultados.
    """
    import time

    t0 = time.time()

    rate_err = _check_rate(tool_limiter, "search_hipocampo")
    if rate_err:
        return rate_err

    try:
        output = await asyncio.to_thread(_search.search, query, session_id)

        latency_ms = int((time.time() - t0) * 1000)
        logger.info("Hipocampo search OK query=%r latency=%dms", query, latency_ms)

        results_count = 0
        top_score = 0.0
        avg_score = 0.0
        for line in output.split("\n"):
            if "📍" in line:
                results_count += 1
            if "Score promedio:" in line:
                parts = line.split(":")
                if len(parts) >= 2:
                    try:
                        avg_score = float(parts[1].strip())
                    except Exception:
                        pass
            if "🏆 Mejor score:" in line:
                parts = line.split(":")
                if len(parts) >= 2:
                    try:
                        top_score = float(parts[1].strip())
                    except Exception:
                        pass

        try:
            await asyncio.to_thread(_stats.record_query, query, latency_ms, results_count, "ssc", top_score, avg_score)
        except Exception as e:
            logger.warning("Stats record falló: %s", e)

        return output

    except (psycopg2.Error, ValueError, TypeError) as e:
        return _tool_err("search_hipocampo", e)
    except Exception as e:
        return _tool_err("search_hipocampo", e)


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
    )
)
async def quick_hipocampo_search(query: str, session_id: str = "") -> str:
    """
    Búsqueda rápida en el Hipocampo (alias corto de search_hipocampo).

    Es solo lectura — no modifica datos, no tiene efectos secundarios.
    Comportamiento y salida idénticos a search_hipocampo.

    Útil cuando el cliente MCP prefiera nombres de herramienta más cortos.
    Para nombre descriptivo, usar search_hipocampo.

    Args:
        query: Texto de búsqueda en lenguaje natural. Igual que
               search_hipocampo. Ej: "API REST en Python", "presupuesto".
        session_id: Opcional. Filtra resultados a una sesión específica.

    Returns:
        Mismo formato que search_hipocampo: resultados como texto plano
        con scores de relevancia y metadatos.
    """
    return await search_hipocampo(query, session_id)


@mcp.resource("hipocampo://info")
def hipocampo_info() -> str:
    """Información general sobre el sistema Hipocampo."""
    return (
        "🧠 Hipocampo Protocol v3.6\n"
        "Sistema de memoria dual con SSC (Sparse-Semantic Clusters)\n"
        "· Búsqueda vectorial 1024d (nvidia/nv-embedqa-e5-v5)\n"
        "· Búsqueda léxica expansiva (pg_trgm + GIN)\n"
        "· Re-ranking híbrido BIRE con auto-tagging\n"
        "· Tablas: memoria_vectorial, memory_items\n"
    )


# ─── EMBEDDING HELPER ────────────────────────────────────────────────────────


def _generar_embedding(texto: str, tool_name: str = "unknown") -> list[float]:
    rate_err = _check_rate(embedding_limiter, tool_name)
    if rate_err:
        raise RuntimeError(rate_err)
    emb = get_embedding(texto)
    if emb is None:
        raise RuntimeError("No se pudo generar embedding (¿NVIDIA_API_KEY configurada?)")
    return emb


def _conn():
    return get_conn()


_RATE_LIMIT_TOOL_RESPONSE = (
    "⏳ Demasiadas solicitudes. Límite: {max} por {window}s. Espera {wait:.0f}s o reduce la frecuencia de llamadas."
)


def _check_rate(limiter, tool_name: str) -> str | None:
    """Check a rate limiter and return an error message if exceeded."""
    if not limiter.acquire():
        wait = limiter.wait_time()
        logger.warning(
            "Rate limit excedido en %s: %s activas de %s, espera %.0fs",
            tool_name,
            limiter.stats["active"],
            limiter.max_calls,
            wait,
        )
        return _RATE_LIMIT_TOOL_RESPONSE.format(
            max=limiter.max_calls,
            window=limiter.window_seconds,
            wait=wait,
        )
    return None


_TOOL_ERR_PREFIX = {
    "psycopg2.Error": "❌ Error de base de datos",
    "ValueError": "❌ Error de validación",
    "TypeError": "❌ Error de tipo",
    "KeyError": "❌ Error de clave faltante",
    "default": "❌ Error inesperado",
}


def _tool_err(tool_name: str, exc: Exception) -> str:
    """Build a user-facing error message with differentiated logging.

    Logs at ``exception`` level for unexpected errors (full traceback),
    ``warning`` for expected domain errors, and returns a string
    safe to return to the MCP client.
    """
    exc_type = type(exc).__name__
    prefix = _TOOL_ERR_PREFIX.get(exc_type, _TOOL_ERR_PREFIX["default"])

    if isinstance(exc, (psycopg2.Error,)):
        logger.exception("DB error en %s", tool_name)
    elif isinstance(exc, (ValueError, TypeError, KeyError)):
        logger.warning("Domain error en %s [%s]: %s", tool_name, exc_type, exc)
    else:
        logger.exception("Error inesperado en %s [%s]: %s", tool_name, exc_type, exc)

    return f"{prefix} en {tool_name}: {exc}"


# ─── HERRAMIENTA: GUARDAR ────────────────────────────────────────────────────


@mcp.tool()
async def save_hipocampo(
    content: str,
    memory_type: str = "event",
    code: str = "",
    categories: list[str] | None = None,
    session_id: str = "",
) -> str:
    """
    Guarda un recuerdo en el Hipocampo (memoria_vectorial).

    Genera embedding automáticamente y persiste el contenido para que sea
    encontrable por búsqueda semántica futura.

    Args:
        content: Texto del recuerdo a guardar.
        memory_type: Tipo de memoria. Valores comunes:
                     "event" (evento/experiencia),
                     "decision" (decisión tomada),
                     "profile" (dato personal).
                     Por defecto: "event".
        code: Código o etiqueta corta para agrupar recuerdos (opcional).
              Ej: "documentacion", "bugfix", "feature", "setup".
        categories: Lista de categorías (opcional).
                    Ej: ["python", "mcp", "infraestructura"].
        session_id: Opcional. Identificador de sesión para aislar memorias.

    Returns:
        Confirmación con el ID asignado.
    """
    rate_err = _check_rate(tool_limiter, "save_hipocampo")
    if rate_err:
        return rate_err

    def _do():
        logger.info("🧠 Guardando en Hipocampo: content=%r...", content[:80])
        embedding = _generar_embedding(content, "save_hipocampo")
        metadatos = {
            "type": memory_type,
            "code": code or "",
            "categories": categories or [],
            "date": str(date.today()),
            "source": "mcp",
        }
        if session_id:
            metadatos["session_id"] = session_id
        conn = _conn()
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO memoria_vectorial (contenido, metadatos, embedding)
               VALUES (%s, %s, %s::vector(1024)) RETURNING id""",
            (content, json.dumps(metadatos), embedding),
        )
        row_id = cur.fetchone()[0]
        conn.commit()
        cur.close()
        conn.close()

        _fire_webhooks("save", row_id, content, metadatos)

        logger.info("✅ Guardado id=%s", row_id)
        return f"✅ Guardado en Hipocampo (id={row_id})"

    try:
        return await asyncio.to_thread(_do)
    except Exception as e:
        return _tool_err("save_hipocampo", e)


@mcp.tool()
async def profile_hipocampo(
    summary: str,
    extra: str = "",
    categories: list[str] | None = None,
) -> str:
    """
    Guarda un dato de perfil personal en Hipocampo (memory_items).

    A diferencia de save_hipocampo (que guarda en memoria_vectorial técnica),
    esta herramienta guarda en memory_items, que está diseñado para datos
    personales: gustos, familia, preferencias, datos biográficos.

    Args:
        summary: Texto corto con el dato personal. Ej: "Al usuario le gusta el té de hierbas".
        extra: Información adicional en texto plano (opcional).
        categories: Categorías (opcional). Ej: ["personal_info", "gustos"].

    Returns:
        Confirmación con el ID asignado.
    """
    rate_err = _check_rate(tool_limiter, "profile_hipocampo")
    if rate_err:
        return rate_err

    def _do():
        logger.info("👤 Guardando perfil: %r...", summary[:80])
        embedding = _generar_embedding(summary, "profile_hipocampo")
        conn = _conn()
        cur = conn.cursor()
        cat_list = categories or ["personal_info"]
        row_id = str(uuid.uuid4())

        cur.execute(
            """INSERT INTO memory_items (id, summary, memory_type, extra, embedding, created_at, updated_at)
               VALUES (%s, %s, 'profile', %s, %s::vector(1024), NOW(), NOW())""",
            (
                row_id,
                summary,
                json.dumps({"extra": extra, "categories": cat_list, "date": str(date.today())}),
                embedding,
            ),
        )

        for cat in cat_list:
            cur.execute("SELECT id FROM memory_categories WHERE name = %s", (cat,))
            cat_row = cur.fetchone()
            if cat_row:
                cur.execute(
                    "INSERT INTO category_items (id, item_id, category_id, created_at, updated_at) VALUES (%s, %s, %s, NOW(), NOW()) ON CONFLICT DO NOTHING",
                    (str(uuid.uuid4()), row_id, cat_row[0]),
                )

        conn.commit()
        cur.close()
        conn.close()
        logger.info("✅ Perfil guardado id=%s", row_id)
        return f"✅ Perfil guardado en Hipocampo (id={row_id})"

    try:
        return await asyncio.to_thread(_do)
    except Exception as e:
        return _tool_err("profile_hipocampo", e)


# ─── HERRAMIENTAS: CRUD (UPDATE / DELETE) ──────────────────────────────────────


@mcp.tool(
    annotations=ToolAnnotations(
        destructiveHint=True,
        idempotentHint=True,
    )
)
async def update_hipocampo(
    id: int,
    content: str | None = None,
    memory_type: str | None = None,
    code: str | None = None,
    categories: list[str] | None = None,
) -> str:
    """
    Actualiza un recuerdo existente en el Hipocampo (memoria_vectorial).

    Si se proporciona content, se regenera el embedding automáticamente.
    Los campos no proporcionados no se modifican.

    Args:
        id: ID numérico del recuerdo a actualizar.
        content: Nuevo texto del recuerdo (opcional). Si se provee, se regenera el embedding.
        memory_type: Nuevo tipo de memoria (opcional). Ej: "event", "decision".
        code: Código o etiqueta corta (opcional).
        categories: Nueva lista de categorías (opcional).

    Returns:
        Confirmación de la actualización.
    """
    rate_err = _check_rate(tool_limiter, "update_hipocampo")
    if rate_err:
        return rate_err

    def _do():
        conn = _conn()
        cur = conn.cursor()
        cur.execute("SELECT contenido, metadatos FROM memoria_vectorial WHERE id = %s", (id,))
        row = cur.fetchone()
        if not row:
            cur.close()
            conn.close()
            return f"❌ No se encontró recuerdo con id={id}"

        current_content, current_metadatos = row
        new_content = content if content is not None else current_content
        new_metadatos = (current_metadatos or {}).copy()
        new_metadatos["updated_at"] = str(date.today())

        if memory_type is not None:
            new_metadatos["type"] = memory_type
        if code is not None:
            new_metadatos["code"] = code
        if categories is not None:
            new_metadatos["categories"] = categories

        if content is not None:
            embedding = _generar_embedding(content, "update_hipocampo")
            cur.execute(
                """UPDATE memoria_vectorial SET contenido=%s, metadatos=%s, embedding=%s::vector(1024)
                   WHERE id=%s""",
                (new_content, json.dumps(new_metadatos), embedding, id),
            )
        else:
            cur.execute(
                "UPDATE memoria_vectorial SET metadatos=%s WHERE id=%s",
                (json.dumps(new_metadatos), id),
            )

        conn.commit()
        cur.close()
        conn.close()

        _fire_webhooks("update", id, new_content, new_metadatos)

        logger.info("✅ Actualizado id=%s", id)
        return f"✅ Actualizado recuerdo id={id}"

    try:
        return await asyncio.to_thread(_do)
    except Exception as e:
        return _tool_err("update_hipocampo", e)


@mcp.tool(
    annotations=ToolAnnotations(
        destructiveHint=True,
    )
)
async def delete_hipocampo(id: int) -> str:
    """
    Elimina un recuerdo del Hipocampo (memoria_vectorial) por su ID.

    Esta operación es irreversible. Una vez eliminado, el recuerdo
    no podrá recuperarse ni aparecerá en búsquedas futuras.

    Args:
        id: ID numérico del recuerdo a eliminar.

    Returns:
        Confirmación de eliminación.
    """
    rate_err = _check_rate(tool_limiter, "delete_hipocampo")
    if rate_err:
        return rate_err

    def _do():
        conn = _conn()
        cur = conn.cursor()
        cur.execute("DELETE FROM memoria_vectorial WHERE id=%s", (id,))
        if cur.rowcount == 0:
            cur.close()
            conn.close()
            return f"❌ No se encontró recuerdo con id={id}"
        conn.commit()
        cur.close()
        conn.close()

        _fire_webhooks("delete", id, "", {})

        logger.info("🗑️ Eliminado id=%s", id)
        return f"🗑️ Eliminado recuerdo id={id}"

    try:
        return await asyncio.to_thread(_do)
    except Exception as e:
        return _tool_err("delete_hipocampo", e)


# ─── HERRAMIENTA: HEALTH CHECK ───────────────────────────────────────────────


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
    )
)
async def hipocampo_health() -> str:
    """
    Ejecuta un health check completo del sistema Hipocampo.

    Verifica: PostgreSQL, NVIDIA API, tablas, espacio en disco, extensiones.

    Returns:
        Reporte formateado del estado del sistema.
    """
    try:
        result = await asyncio.to_thread(_health.full_health_check)
        overall = result.get("overall", result.get("status", "unknown"))
        emoji = {"ok": "✅", "degraded": "⚠️", "error": "❌"}.get(overall, "❓")
        lines = [f"{emoji} Health: {overall.upper()}"]
        lines.append(f"   Timestamp: {result.get('timestamp', 'N/A')}")
        for category, checks in result.get("checks", {}).items():
            lines.append(f"\n   📊 {category}:")
            if isinstance(checks, dict):
                for k, v in checks.items():
                    lines.append(f"      {k}: {v}")
            else:
                lines.append(f"      {checks}")
        return "\n".join(lines)
    except Exception as e:
        return _tool_err("hipocampo_health", e)


@mcp.tool()
async def hipocampo_auto_repair() -> str:
    """
    Intenta reparar automáticamente problemas detectados en el sistema.

    Reparaciones posibles:
    - Reiniciar PostgreSQL si está caído
    - Crear tablas faltantes desde esquema.sql
    - Verificar/configurar NVIDIA_API_KEY

    Returns:
        Reporte de reparaciones ejecutadas.
    """
    try:
        report = await asyncio.to_thread(_health.auto_repair)
        lines = ["🔧 Auto-repair:"]
        if report.get("repaired"):
            lines.append(f"   ✅ Reparados: {', '.join(report['repaired'])}")
        if report.get("failed"):
            lines.append(f"   ❌ Fallaron: {', '.join(report['failed'])}")
        if report.get("skipped"):
            lines.append(f"   ⏭️  Omitidos: {', '.join(report['skipped'])}")
        return "\n".join(lines) or "🔧 Auto-repair completado (sin novedades)"
    except Exception as e:
        return _tool_err("hipocampo_auto_repair", e)


# ─── HERRAMIENTAS: STATS Y AJUSTE DINÁMICO ────────────────────────────────────


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
    )
)
async def hipocampo_stats() -> str:
    """
    Muestra estadísticas de rendimiento del sistema Hipocampo.

    Analiza latencia de queries, métodos usados, scores promedios
    y da recomendaciones de optimización.

    Returns:
        Reporte de métricas y recomendaciones.
    """
    try:
        data = await asyncio.to_thread(_stats.analyze)
        return _stats.format_result(data)
    except Exception as e:
        return _tool_err("hipocampo_stats", e)


@mcp.tool(
    annotations=ToolAnnotations(
        destructiveHint=True,
        idempotentHint=True,
    )
)
async def hipocampo_tune() -> str:
    """
    Ajusta automáticamente los thresholds y pesos del SSC
    basado en las métricas de rendimiento acumuladas.

    Es destructivo: modifica los thresholds y pesos de forma irreversible.
    Sin embargo, es idempotente: ejecutarlo múltiples veces converge al
    mismo resultado. Usar con precaución.

    Para solo ver estadísticas sin modificar nada, usar hipocampo_stats
    (solo lectura). Para ejecutar el ciclo completo de mantenimiento
    (que incluye tune como paso 5), usar hipocampo_maintenance.

    Recomendado ejecutar solo después de acumular suficientes métricas
    (al menos 100 consultas registradas). No usar si el sistema funciona
    correctamente sin degradación.

    Returns:
        Reporte de ajustes aplicados (nuevos thresholds y pesos).
    """
    try:
        data = await asyncio.to_thread(_stats.tune_thresholds)
        return _stats.format_result(data)
    except Exception as e:
        return _tool_err("hipocampo_tune", e)


# ─── HERRAMIENTAS: MANTENIMIENTO (FASE 3) ─────────────────────────────────────


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=True,
        idempotentHint=True,
    )
)
async def hipocampo_dedup(merge: bool = False) -> str:
    """
    Detecta y opcionalmente fusiona duplicados en las tablas de memoria.

    Con merge=False (default) es solo lectura — seguro de ejecutar, no modifica datos.
    Con merge=True es destructivo: consolida filas duplicadas en una sola, operación
    irreversible. Usar con precaución. Ejecutar primero sin merge para previsualizar.

    ¿Qué es un duplicado? Dos registros con alta similitud semántica (embedding
    + texto), por encima del umbral configurable (default 0.95).

    El reporte incluye: cantidad de duplicados encontrados, IDs afectados y
    resumen de fusión si se ejecutó merge.

    Para ejecutar dedup como parte del ciclo completo de mantenimiento, usar
    hipocampo_maintenance (paso 2 del ciclo). Esta herramienta es para uso
    puntual o previsualización antes del merge.

    Args:
        merge: Si es True, fusiona los duplicados encontrados (irreversible).
               Si es False (default), solo muestra análisis (seguro).

    Returns:
        Reporte de duplicados encontrados o fusionados.
    """
    try:
        if merge:
            report = await asyncio.to_thread(_dedup.full_dedup_merge)
            total_removed = sum(v.get("removed", 0) for v in report["exact"].values()) + sum(
                v.get("removed", 0) for v in report["semantic"].values()
            )
            lines = [f"🔧 Dedup merge completado: {total_removed} registros eliminados"]
            for k, v in report.items():
                for t, r in v.items():
                    if r.get("removed", 0) > 0:
                        lines.append(f"   {t} ({k}): {r['merged_groups']} grupos fusionados, {r['removed']} eliminados")
            return "\n".join(lines) + "\n   ✅ Proceso completado"
        else:
            info = await asyncio.to_thread(_dedup.full_dedup_analysis)
            lines = []
            for table, data in info.items():
                emoji = "⚠️" if data["total_recoverable"] > 0 else "✅"
                lines.append(f"{emoji} {table}:")
                lines.append(
                    f"   Duplicados exactos: {data['exact_duplicates']} grupos ({data['exact_redundant_rows']} registros redundantes)"
                )
                lines.append(
                    f"   Duplicados semánticos: {data['semantic_groups']} grupos ({data['semantic_redundant_rows']} registros redundantes)"
                )
                lines.append(f"   Espacio recuperable: {data['total_recoverable']} registros")
            lines.append("\n💡 Ejecuta con merge=True para fusionar y limpiar")
            return "\n".join(lines)
    except Exception as e:
        return _tool_err("hipocampo_dedup", e)


@mcp.tool(
    annotations=ToolAnnotations(
        destructiveHint=True,
        idempotentHint=True,
    )
)
async def hipocampo_checkpoint(dry_run: bool = True) -> str:
    """
    Comprime memorias antiguas usando checkpointing logarítmico.

    Con dry_run=True (default) es solo lectura — seguro, no modifica datos.
    Con dry_run=False es destructivo: comprime memorias antiguas de forma
    irreversible (las originales se eliminan tras comprimir). Idempotente:
    ejecutar múltiples veces no daña datos.

    Para ejecutar checkpoint como parte del ciclo completo de mantenimiento,
    usar hipocampo_maintenance (paso 3 del ciclo). Esta herramienta es para
    ejecución puntual o previsualización.

    Recomendado ejecutar periódicamente (semanal o mensual) para mantener
    el rendimiento del sistema.

    Args:
        dry_run: Si es True (default), solo muestra qué se comprimiría.
                 Si es False, ejecuta la compresión (irreversible).

    Returns:
        Reporte del checkpointing ejecutado o simulado.
        Incluye: cantidad de registros comprimidos, espacio liberado.
    """
    try:
        return await asyncio.to_thread(_checkpoint.run_checkpoint, dry_run=dry_run)
    except Exception as e:
        return _tool_err("hipocampo_checkpoint", e)


@mcp.tool()
async def hipocampo_maintenance() -> str:
    """
    Ejecuta el ciclo completo de mantenimiento:
    1. Health check → auto-repair si es necesario
    2. Dedup → fusiona duplicados
    3. Checkpoint → comprime memorias antiguas
    4. Tune → ajusta thresholds según métricas

    Returns:
        Reporte consolidado del mantenimiento.
    """

    def _do_maintenance():
        report_parts = []
        try:
            r = _health.auto_repair()
            ok = len(r.get("repaired", [])) > 0 or len(r.get("skipped", [])) > 0
            report_parts.append(f"🔧 Repair: {'✅' if ok else '❌'}")
        except Exception:
            report_parts.append("🔧 Repair: ❌")

        try:
            _dedup.full_dedup_merge()
            report_parts.append("🧹 Dedup: ✅")
        except Exception:
            report_parts.append("🧹 Dedup: ❌")

        try:
            _checkpoint.run_checkpoint(dry_run=False)
            report_parts.append("📦 Checkpoint: ✅")
        except Exception:
            report_parts.append("📦 Checkpoint: ❌")

        try:
            _stats.tune_thresholds()
            report_parts.append("⚙️ Tune: ✅")
        except Exception:
            report_parts.append("⚙️ Tune: ❌")

        return "📋 Mantenimiento completo:\n" + "\n".join(report_parts)

    try:
        return await asyncio.to_thread(_do_maintenance)
    except Exception as e:
        return _tool_err("hipocampo_maintenance", e)


# ─── HERRAMIENTAS: WEBHOOKS (WATCH) ──────────────────────────────────────────


@mcp.tool()
async def watch_hipocampo(pattern: str, webhook_url: str) -> str:
    """
    Registra un webhook que se dispara cuando se crea/modifica/elimina
    un recuerdo cuyo contenido o metadatos contengan el patrón dado.

    Args:
        pattern: Texto a buscar en contenido o metadatos del recuerdo.
        webhook_url: URL que recibirá un POST con event, id, content, metadatos.

    Returns:
        Confirmación con ID del watch creado.
    """
    rate_err = _check_rate(tool_limiter, "watch_hipocampo")
    if rate_err:
        return rate_err

    def _do():
        conn = _conn()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO watches (pattern, webhook_url) VALUES (%s, %s) RETURNING id",
            (pattern, webhook_url),
        )
        wid = cur.fetchone()[0]
        conn.commit()
        cur.close()
        conn.close()
        logger.info("🔔 Watch registrado id=%s pattern=%r -> %s", wid, pattern, webhook_url)
        return f"🔔 Watch registrado (id={wid}) para patrón '{pattern}'"

    try:
        return await asyncio.to_thread(_do)
    except Exception as e:
        return _tool_err("watch_hipocampo", e)


@mcp.tool()
async def unwatch_hipocampo(id: int) -> str:
    """
    Elimina un webhook registrado por su ID.

    Args:
        id: ID del watch a eliminar.

    Returns:
        Confirmación de eliminación.
    """
    rate_err = _check_rate(tool_limiter, "unwatch_hipocampo")
    if rate_err:
        return rate_err

    def _do():
        conn = _conn()
        cur = conn.cursor()
        cur.execute("DELETE FROM watches WHERE id = %s", (id,))
        if cur.rowcount == 0:
            cur.close()
            conn.close()
            return f"❌ No se encontró watch con id={id}"
        conn.commit()
        cur.close()
        conn.close()
        logger.info("🔕 Watch eliminado id=%s", id)
        return f"🔕 Watch id={id} eliminado"

    try:
        return await asyncio.to_thread(_do)
    except Exception as e:
        return _tool_err("unwatch_hipocampo", e)


@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
    )
)
async def list_watches() -> str:
    """
    Lista todos los webhooks registrados.

    Returns:
        Lista de watches con ID, patrón y URL.
    """

    def _do():
        conn = _conn()
        cur = conn.cursor()
        cur.execute("SELECT id, pattern, webhook_url, created_at, last_triggered_at FROM watches ORDER BY id")
        rows = cur.fetchall()
        cur.close()
        conn.close()

        if not rows:
            return "No hay watches registrados."

        lines = ["🔔 Watches registrados:"]
        for row in rows:
            last = row[4].strftime("%Y-%m-%d %H:%M") if row[4] else "nunca"
            lines.append(f"  [{row[0]}] patrón: {row[1]!r}")
            lines.append(f"       URL: {row[2]}")
            lines.append(f"       creado: {row[3].strftime('%Y-%m-%d %H:%M')}  último trigger: {last}")
        return "\n".join(lines)

    try:
        return await asyncio.to_thread(_do)
    except Exception as e:
        return _tool_err("list_watches", e)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Hipocampo MCP Server — memoria dual con BIRE v3.7")
    parser.add_argument(
        "--http",
        "--streamable-http",
        nargs="?",
        const=8001,
        type=int,
        metavar="PORT",
        dest="http_port",
        help="Iniciar en modo Streamable HTTP (default puerto 8001)",
    )
    parser.add_argument(
        "--sse", nargs="?", const=8001, type=int, metavar="PORT", help="Iniciar en modo SSE (deprecado)"
    )
    parser.add_argument("--host", default="127.0.0.1", help="Host para modo HTTP (default 127.0.0.1)")
    parser.add_argument("--transport", choices=("stdio", "http", "sse"), help="Transporte (alternativa a --http/--sse)")
    args = parser.parse_args()

    cfg_errors = validate_config()
    if cfg_errors:
        for err in cfg_errors:
            logger.warning("⚠️  Config: %s", err)
    _init_watches_table()
    init_pool()

    http_port = args.http_port
    if not http_port and args.transport == "http":
        http_port = 8001

    sse_port = args.sse
    if not sse_port and args.transport == "sse":
        sse_port = 8001

    if http_port:
        port = http_port
        host = args.host
        import uvicorn
        from starlette.routing import Route
        from starlette.responses import JSONResponse

        logger.info("🔌 Iniciando Hipocampo MCP Server (Streamable HTTP) en %s:%d", host, port)
        mcp.settings.port = port
        mcp.settings.host = host
        mcp.settings.transport_security.enable_dns_rebinding_protection = False

        async def api_search(request):
            q = request.query_params.get("q", "")
            if not q:
                return JSONResponse({"ok": False, "error": "query param 'q' required"})
            try:
                import time

                t0 = time.time()
                output = await asyncio.to_thread(_search.search, q)
                return JSONResponse({"ok": True, "results": output, "latency_ms": int((time.time() - t0) * 1000)})
            except Exception as e:
                return JSONResponse({"ok": False, "error": str(e)})

        async def api_save(request):
            try:
                body = await request.json()
                content = body.get("content", "")
                if not content:
                    return JSONResponse({"ok": False, "error": "content required"})

                def _do_save():
                    import json as j
                    from datetime import date as d

                    embedding = _generar_embedding(content)
                    metadatos = {
                        "type": body.get("type", "event"),
                        "code": body.get("code", ""),
                        "categories": body.get("categories", []),
                        "date": str(d.today()),
                        "source": "web_demo",
                    }
                    sid = body.get("session_id", "")
                    if sid:
                        metadatos["session_id"] = sid
                    conn = _conn()
                    cur = conn.cursor()
                    cur.execute(
                        "INSERT INTO memoria_vectorial (contenido, metadatos, embedding) VALUES (%s, %s, %s::vector(1024)) RETURNING id",
                        (content, j.dumps(metadatos), embedding),
                    )
                    row_id = cur.fetchone()[0]
                    conn.commit()
                    cur.close()
                    conn.close()
                    return {"ok": True, "id": row_id}

                result = await asyncio.to_thread(_do_save)
                return JSONResponse(result)
            except Exception as e:
                return JSONResponse({"ok": False, "error": str(e)})

        async def api_health(request):
            try:
                r = await asyncio.to_thread(_health.full_health_check)
                return JSONResponse({"ok": True, "output": r})
            except Exception as e:
                return JSONResponse({"ok": False, "error": str(e)})

        from starlette.applications import Starlette as StarletteApp

        mcp_app = mcp.streamable_http_app()
        api_app = StarletteApp(
            routes=[
                Route("/api/search", endpoint=api_search, methods=["GET"]),
                Route("/api/save", endpoint=api_save, methods=["POST"]),
                Route("/api/health", endpoint=api_health, methods=["GET"]),
            ]
        )
        playground_html = open(os.path.join(BASE_DIR, "..", "playground.html"), encoding="utf-8").read()

        async def app(scope, receive, send):
            if scope["type"] == "http":
                path = scope["path"]
                method = scope["method"]
                if path == "/" and method == "GET":
                    qs = scope.get("query_string", b"").decode()
                    if "logs=container" in qs:
                        body = b'{"status":"ok","server":"hipocampo","endpoint":"/mcp"}'
                        await send(
                            {
                                "type": "http.response.start",
                                "status": 200,
                                "headers": [(b"content-type", b"application/json")],
                            }
                        )
                        await send({"type": "http.response.body", "body": body})
                    else:
                        body = playground_html.encode("utf-8")
                        await send(
                            {
                                "type": "http.response.start",
                                "status": 200,
                                "headers": [(b"content-type", b"text/html; charset=utf-8")],
                            }
                        )
                        await send({"type": "http.response.body", "body": body})
                    return
                if path.startswith("/mcp") or path.startswith("/sse"):
                    await mcp_app(scope, receive, send)
                    return
                await api_app(scope, receive, send)

        config = uvicorn.Config(app, host=host, port=port, log_level=mcp.settings.log_level.lower())
        uvicorn.Server(config).run()
    elif sse_port:
        logger.warning("⚠️  --sse está deprecado desde spec MCP 2025-03-26. Usa --http en su lugar.")
        logger.info("🔌 Iniciando Hipocampo MCP Server (SSE) en puerto %d", sse_port)
        mcp.settings.port = sse_port
        mcp.run(transport="sse")
    else:
        logger.info("🔌 Iniciando Hipocampo MCP Server (stdio)")
        mcp.run()
