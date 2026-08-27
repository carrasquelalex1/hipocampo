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


# ─── CONFIGURACIÓN ─────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.dirname(BASE_DIR))  # project root for hipocampo package


from hipocampo.db import get_conn, get_embedding, get_embedding_last_error, init_pool, validate_config
from hipocampo.rate_limit import embedding_limiter, tool_limiter

import hipocampo_search as _search
import hipocampo_health as _health
import hipocampo_stats as _stats
import hipocampo_dedup as _dedup
import hipocampo_checkpoint as _checkpoint
import hipocampo_compress as _compress
import hipocampo_index_project as _indexer

# Ensure query_stats table exists (lazy — safe if DB not reachable)
try:
    _stats.ensure_stats_table()
except Exception:
    logger.warning("query_stats table not available (DB not reachable yet)")

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

MEMORY_LINKS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS memory_links (
    id SERIAL PRIMARY KEY,
    source_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    relation_type TEXT NOT NULL DEFAULT 'related',
    weight REAL NOT NULL DEFAULT 1.0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata JSONB DEFAULT '{}',
    UNIQUE(source_id, target_id, relation_type)
);
CREATE INDEX IF NOT EXISTS idx_memory_links_source ON memory_links(source_id);
CREATE INDEX IF NOT EXISTS idx_memory_links_target ON memory_links(target_id);
CREATE INDEX IF NOT EXISTS idx_memory_links_type ON memory_links(relation_type);
"""

MEMORY_LINKS_MIGRATION_SQL = """
ALTER TABLE memory_links ALTER COLUMN source_id TYPE TEXT;
ALTER TABLE memory_links ALTER COLUMN target_id TYPE TEXT;
"""

MEMORY_LINKS_DECAY_MIGRATION_SQL = """
ALTER TABLE memory_links ADD COLUMN IF NOT EXISTS last_accessed TIMESTAMPTZ;
ALTER TABLE memory_links ADD COLUMN IF NOT EXISTS reinforced_at TIMESTAMPTZ DEFAULT NOW();
CREATE INDEX IF NOT EXISTS idx_memory_links_last_accessed ON memory_links(last_accessed);
CREATE INDEX IF NOT EXISTS idx_memory_links_reinforced ON memory_links(reinforced_at);
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


def _init_memory_links_table():
    try:
        conn = _conn()
        cur = conn.cursor()
        for stmt in MEMORY_LINKS_TABLE_SQL.split(";"):
            if stmt.strip():
                cur.execute(stmt)
        for stmt in MEMORY_LINKS_MIGRATION_SQL.split(";"):
            stmt = stmt.strip()
            if stmt:
                try:
                    cur.execute(stmt)
                except psycopg2.Error:
                    conn.rollback()
        for stmt in MEMORY_LINKS_DECAY_MIGRATION_SQL.split(";"):
            stmt = stmt.strip()
            if stmt:
                try:
                    cur.execute(stmt)
                except psycopg2.Error:
                    conn.rollback()
        conn.commit()
        cur.close()
        conn.close()
        logger.info("✅ memory_links table initialized (decay columns ready)")
    except psycopg2.Error as e:
        logger.warning("DB error al inicializar memory_links: %s", e)
    except Exception as e:
        logger.warning("Error inesperado al inicializar memory_links: %s", e)


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


_SESSION_CHECK_INTERVAL = 20  # summarize every N saves per session


def _auto_summarize_session(session_id: str):
    """Auto-consolidate session records into a high-level summary.

    Triggered every SESSION_CHECK_INTERVAL saves for a given session.
    Runs in background thread.
    """
    if not session_id:
        return

    def _do():
        try:
            conn = _conn()
            cur = conn.cursor()
            cur.execute(
                """SELECT count(*) FROM memoria_vectorial
                   WHERE metadatos->>'session_id' = %s""",
                (session_id,),
            )
            count = cur.fetchone()[0]
            if count < _SESSION_CHECK_INTERVAL or count % _SESSION_CHECK_INTERVAL != 0:
                cur.close()
                conn.close()
                return

            cur.execute(
                """SELECT id, contenido, metadatos FROM memoria_vectorial
                   WHERE metadatos->>'session_id' = %s
                   ORDER BY id DESC LIMIT %s""",
                (session_id, _SESSION_CHECK_INTERVAL),
            )
            rows = cur.fetchall()
            if not rows:
                cur.close()
                conn.close()
                return

            texts = "\n---\n".join(f"[{r[0]}] {r[1][:200]}" for r in rows)
            summary_text = (
                f"[SESSION SUMMARY] Sesión {session_id}: {count} registros consolidados. Últimos {len(rows)}:\n{texts}"
            )

            import hipocampo_compress as _cp

            compressed = _cp._extractive_compress(summary_text, session_id, ratio=0.3)
            metadatos = json.dumps(
                {
                    "type": "session_summary",
                    "session_id": session_id,
                    "consolidated_count": count,
                    "date": str(date.today()),
                    "source": "auto_summarize",
                }
            )
            emb = get_embedding(compressed)
            cur.execute(
                """INSERT INTO memoria_vectorial (contenido, metadatos, embedding)
                   VALUES (%s, %s, %s::vector(1024)) RETURNING id""",
                (compressed, metadatos, emb),
            )
            conn.commit()
            cur.close()
            conn.close()
            logger.info("📋 Session summary created for %s (%d records)", session_id, count)
        except Exception as e:
            logger.warning("Auto-summarize failed: %s", e)

    import threading

    threading.Thread(target=_do, daemon=True).start()


def _auto_checkpoint():
    """Auto-trigger checkpoint if memory count > 150 or oldest > 30 days."""
    try:
        conn = _conn()
        cur = conn.cursor()
        cur.execute("SELECT count(*) FROM memoria_vectorial")
        count = cur.fetchone()[0]
        cur.execute("SELECT min((metadatos->>'date')::date) FROM memoria_vectorial WHERE metadatos ? 'date'")
        oldest = cur.fetchone()[0]
        cur.close()
        conn.close()

        reason = None
        if count > 150:
            reason = f"count ({count}) > 150"
        elif oldest:
            from datetime import date as dt_date

            days_old = (dt_date.today() - oldest).days
            if days_old > 30:
                reason = f"oldest memory {days_old}d > 30d"

        if reason:
            logger.info("📦 Auto-checkpoint triggered: %s", reason)
            import hipocampo_checkpoint as _cp

            result = _cp.run_checkpoint(dry_run=False)
            logger.info("📦 Auto-checkpoint result: %s", result[:200] if result else "OK")
    except Exception as e:
        logger.warning("Auto-checkpoint skipped: %s", e)


mcp = FastMCP("hipocampo")


@mcp.tool()
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
        output, stats = await asyncio.to_thread(_search.search_with_stats, query, session_id)

        latency_ms = int((time.time() - t0) * 1000)
        logger.info(
            "Hipocampo search OK query=%r latency=%dms results=%d top=%.1f avg=%.1f",
            query,
            latency_ms,
            stats["results_count"],
            stats["top_score"],
            stats["avg_score"],
        )

        try:
            await asyncio.to_thread(
                _stats.record_query,
                query,
                latency_ms,
                stats["results_count"],
                stats["method"],
                stats["top_score"],
                stats["avg_score"],
            )
        except Exception as e:
            logger.warning("Stats record falló: %s", e)

        return output

    except (psycopg2.Error, ValueError, TypeError) as e:
        return _tool_err("search_hipocampo", e)
    except Exception as e:
        return _tool_err("search_hipocampo", e)


@mcp.tool()
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


@mcp.tool()
async def compress_hipocampo(
    query: str,
    k: int = 5,
    method: str = "hybrid",
    target_token: int = -1,
    include_metadata: bool = False,
    budget_ratio: float = 1.0,
) -> str:
    """
    Compress retrieved memories using a hybrid approach (extractive + LLM).

    First searches Hipocampo (SSC v1.0), then compresses the top-k results:
    - method="extractive": sentence-level keyword relevance (fast, no API cost)
    - method="llm": summarization via NVIDIA NIM (highest quality, API cost)
    - method="hybrid" (default): uses LLM for technical/code content, extractive for generic text

    Use this tool BEFORE sending context to another LLM to reduce prompt size
    while preserving critical information.

    Args:
        query: Natural language search query.
        k: Number of memories to retrieve (default 5, max 20).
        method: Compression method: "hybrid" (default), "extractive", or "llm".
        target_token: Target token count (-1 = auto, based on content).
        include_metadata: Include per-memory details in output.
        budget_ratio: Scale factor for auto-estimated tokens (default 1.0).

    Returns:
        Compressed context as plain text with compression statistics.
        Includes: compressed text, original/compressed char counts, ratio, latency.
    """
    rate_err = _check_rate(tool_limiter, "compress_hipocampo")
    if rate_err:
        return rate_err

    try:
        result = await asyncio.to_thread(
            _compress.compress_hipocampo,
            query=query,
            k=min(k, 20),
            method=method,
            target_token=target_token,
            include_metadata=include_metadata,
            budget_ratio=budget_ratio,
        )

        if "error" in result:
            return f"❌ {result['error']}"

        lines = [
            f"📦 Compress result ({result['method']}):",
            f"   Original: {result['original_len']} chars → Compressed: {result['compressed_len']} chars",
            f"   Ratio: {result['ratio'] * 100:.1f}% reduction",
            f"   Latency: {result['total_latency_ms']}ms",
            "",
            result["compressed"],
        ]

        if include_metadata and "memories" in result:
            lines.append("\n📋 Per-memory details:")
            for i, m in enumerate(result["memories"], 1):
                lines.append(f"  [{i}] method={m['method']} score={m['score']} technical={m['is_technical']}")

        return "\n".join(lines)

    except (ValueError, TypeError) as e:
        return _tool_err("compress_hipocampo", e)
    except Exception as e:
        return _tool_err("compress_hipocampo", e)


@mcp.resource("hipocampo://info")
def hipocampo_info() -> str:
    """Información general sobre el sistema Hipocampo."""
    return (
        "🧠 Hipocampo Protocol v4.0\n"
        "Sistema de memoria dual con SSC (Sparse-Semantic Clusters)\n"
        "· Búsqueda vectorial 1024d (nvidia/nv-embedqa-e5-v5)\n"
        "· Búsqueda léxica expansiva (pg_trgm + GIN)\n"
        "· Re-ranking híbrido BIRE con auto-tagging\n"
        "· Compresión híbrida de prompts (extractiva + LLM)\n"
        "· Tablas: memoria_vectorial, memory_items\n"
    )


# ─── EMBEDDING HELPER ────────────────────────────────────────────────────────


def _check_dedup(content: str, threshold: float = 0.9) -> str | None:
    """Check if content already exists in memoria_vectorial.

    Returns a warning string if duplicate found, None otherwise.
    """
    try:
        emb = get_embedding(content)
        if emb is None:
            return None
        conn = _conn()
        cur = conn.cursor()
        cur.execute(
            """SELECT id, contenido,
                      (embedding <=> %s::vector(1024)) AS dist
               FROM memoria_vectorial
               WHERE (embedding <=> %s::vector(1024)) < %s
               ORDER BY dist
               LIMIT 1""",
            (emb, emb, 1 - threshold),
        )
        row = cur.fetchone()
        cur.close()
        conn.close()
        if row:
            sim = round((1 - row[2]) * 100, 1)
            return (
                f"⚠️ Ya existe un recuerdo muy similar (id={row[0]}, similitud={sim}%). "
                f"Contenido existente: {row[1][:120]}... "
                f"Usa update_hipocampo(id={row[0]}) para actualizarlo, "
                f"o pasa force=True para guardar de todas formas."
            )
        return None
    except Exception as e:
        logger.warning("Dedup check falló: %s", e)
        return None


def _generar_embedding(texto: str, tool_name: str = "unknown") -> list[float]:
    rate_err = _check_rate(embedding_limiter, tool_name)
    if rate_err:
        raise RuntimeError(rate_err)
    emb = get_embedding(texto)
    if emb is None:
        detalle = get_embedding_last_error() or "razón desconocida"
        raise RuntimeError(f"No se pudo generar embedding: {detalle}")
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
    force: bool = False,
    auto_link: bool = False,
    nivel: str = "episodica",
) -> str:
    """
    Guarda un recuerdo en el Hipocampo (memoria_vectorial).

    Genera embedding automáticamente y persiste el contenido para que sea
    encontrable por búsqueda semántica futura.

    Si ya existe un recuerdo con similitud semántica >0.9, se advierte
    y se omite el guardado a menos que force=True.

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
        force: Si True, guarda incluso si existe un recuerdo muy similar.
        auto_link: Si True, busca recuerdos semánticamente similares (>0.75)
                   y crea enlaces "similar" automáticamente.
        nivel: Nivel de memoria jerárquica:
               "episodica" (default) — detalle completo, comprimible,
               "semantica" — conocimiento consolidado, protegido,
               "automatica" — regla permanente, nunca se comprime.

    Returns:
        Confirmación con el ID asignado.
    """
    rate_err = _check_rate(tool_limiter, "save_hipocampo")
    if rate_err:
        return rate_err

    def _do():
        logger.info("🧠 Guardando en Hipocampo: content=%r...", content[:80])

        if not content or not content.strip():
            return "❌ El contenido no puede estar vacío."

        if nivel not in ("episodica", "semantica", "automatica"):
            return f"❌ Nivel inválido: {nivel}. Usa: episodica, semantica, automatica."

        if not force:
            dedup_warning = _check_dedup(content)
            if dedup_warning:
                logger.info("Dedup bloqueó guardado (similar existente)")
                return dedup_warning

        embedding = _generar_embedding(content, "save_hipocampo")
        metadatos = {
            "type": memory_type,
            "code": code or "",
            "categories": categories or [],
            "date": str(date.today()),
            "source": "mcp",
            "nivel": nivel,
        }
        if nivel == "automatica":
            metadatos["review_count"] = 0
            metadatos["created_at"] = str(date.today())
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
        _auto_summarize_session(session_id)

        links_created = 0
        if auto_link:
            try:
                if embedding:
                    link_conn = _conn()
                    link_cur = link_conn.cursor()
                    link_cur.execute(
                        """SELECT id, contenido, (embedding <=> %s::vector(1024)) AS dist
                           FROM memoria_vectorial
                           WHERE id != %s AND (embedding <=> %s::vector(1024)) < 0.25
                           ORDER BY dist
                           LIMIT 3""",
                        (embedding, row_id, embedding),
                    )
                    similar = link_cur.fetchall()
                    link_cur.close()
                    link_conn.close()
                    for sim_id, sim_content, dist in similar:
                        sim = round((1 - dist) * 100, 1)
                        if sim > 75:
                            try:
                                c2 = _conn()
                                c2_cur = c2.cursor()
                                c2_cur.execute(
                                    """INSERT INTO memory_links (source_id, target_id, relation_type, weight)
                                       VALUES (%s, %s, 'similar', %s) ON CONFLICT DO NOTHING""",
                                    (str(row_id), str(sim_id), sim / 100),
                                )
                                c2.commit()
                                c2_cur.close()
                                c2.close()
                                links_created += 1
                            except Exception:
                                pass
                    if logger.isEnabledFor(logging.INFO):
                        logger.info("auto_link: %d enlaces creados para id=%s", links_created, row_id)
            except Exception:
                logger.warning("Auto-link falló para id=%s", row_id)

        logger.info("✅ Guardado id=%s", row_id)
        msg = f"✅ Guardado en Hipocampo (id={row_id})"
        if links_created:
            msg += f" 🔗 {links_created} auto-enlace(s) creado(s)"
        return msg

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

        # Profile merge: buscar si ya existe un perfil similar (>0.85 similitud)
        PROFILE_MERGE_THRESHOLD = 0.85
        cur.execute("SELECT id, summary, embedding FROM memory_items WHERE embedding IS NOT NULL")
        rows = cur.fetchall()
        best_match = None
        best_sim = 0.0

        import math

        def _cosine_sim(a, b):
            if not a or not b:
                return 0.0
            dot = sum(x * y for x, y in zip(a, b))
            na = math.sqrt(sum(x * x for x in a))
            nb = math.sqrt(sum(x * x for x in b))
            return dot / (na * nb) if na * nb > 0 else 0.0

        if isinstance(embedding, str):
            import ast

            new_emb = ast.literal_eval(embedding)
        else:
            new_emb = embedding

        for row in rows:
            try:
                db_emb = row[2]
                if isinstance(db_emb, str):
                    db_emb = ast.literal_eval(db_emb)
                if db_emb is None:
                    continue
                sim = _cosine_sim(new_emb, db_emb)
                if sim > best_sim and sim >= PROFILE_MERGE_THRESHOLD:
                    best_sim = sim
                    best_match = row
            except Exception:
                pass

        if best_match:
            existing_id = best_match[0]
            logger.info(
                "🔄 Perfil similar encontrado (id=%s, sim=%.1f%%). Actualizando...", existing_id, best_sim * 100
            )
            cur.execute(
                """UPDATE memory_items SET summary = %s, extra = %s, embedding = %s::vector(1024), updated_at = NOW()
                   WHERE id = %s""",
                (
                    summary,
                    json.dumps({"extra": extra, "categories": cat_list, "date": str(date.today())}),
                    embedding,
                    existing_id,
                ),
            )
            conn.commit()
            cur.close()
            conn.close()
            logger.info("✅ Perfil actualizado id=%s (similitud %.1f%%)", existing_id, best_sim * 100)
            return f"✅ Perfil actualizado en Hipocampo (id={existing_id}, similitud={best_sim * 100:.1f}%)"
        else:
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


@mcp.tool()
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


@mcp.tool()
async def set_nivel_hipocampo(id: int, nivel: str) -> str:
    """
    Cambia el nivel jerárquico de un recuerdo.

    Niveles:
      - "episodica" — detalle completo, comprimible por checkpoint
      - "semantica" — conocimiento consolidado, protegido de compresión
      - "automatica" — regla permanente, nunca se comprime/checkpointea

    Args:
        id: ID del recuerdo.
        nivel: Nuevo nivel: "episodica", "semantica", o "automatica".

    Returns:
        Confirmación del cambio.
    """
    if nivel not in ("episodica", "semantica", "automatica"):
        return f"❌ Nivel inválido: {nivel}. Usa: episodica, semantica, automatica."

    def _do():
        conn = _conn()
        cur = conn.cursor()
        cur.execute("SELECT metadatos FROM memoria_vectorial WHERE id = %s", (id,))
        row = cur.fetchone()
        if not row:
            cur.close()
            conn.close()
            return f"❌ No existe recuerdo con id={id}."

        meta = (row[0] or {}).copy()
        meta["nivel"] = nivel
        cur.execute("UPDATE memoria_vectorial SET metadatos = %s WHERE id = %s", (json.dumps(meta), id))
        conn.commit()
        cur.close()
        conn.close()
        return f"✅ Recuerdo #{id} promovido a nivel '{nivel}'."

    try:
        return await asyncio.to_thread(_do)
    except Exception as e:
        return _tool_err("set_nivel_hipocampo", e)


@mcp.tool()
async def consolidate_hipocampo(min_age_days: int = 7, dry_run: bool = True) -> str:
    """
    Consolidación jerárquica: migra memorias episódicas antiguas a semánticas.

    Busca recuerdos con nivel 'episodica' más antiguos que min_age_days
    y los promueve a 'semantica', opcionalmente comprimiendo su contenido.

    Args:
        min_age_days: Edad mínima en días para consolidar (default 7).
        dry_run: Si True, solo muestra qué se consolidaría.

    Returns:
        Reporte de la consolidación.
    """

    def _do():
        conn = _conn()
        cur = conn.cursor()
        cur.execute(
            """SELECT id, contenido, metadatos::text FROM memoria_vectorial
               WHERE metadatos->>'nivel' = 'episodica'
                  OR metadatos->>'nivel' IS NULL
               ORDER BY id"""
        )
        rows = cur.fetchall()
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        candidates = []
        for row in rows:
            meta = json.loads(row[2])
            fecha_str = meta.get("date") or meta.get("fecha")
            if not fecha_str:
                continue
            try:
                fecha = datetime.fromisoformat(fecha_str)
                if fecha.tzinfo is None:
                    fecha = fecha.replace(tzinfo=timezone.utc)
                edad = (now - fecha).days
                if edad >= min_age_days:
                    candidates.append(row)
            except (ValueError, TypeError):
                continue
        if not candidates:
            cur.close()
            conn.close()
            return "✅ No hay recuerdos episódicos antiguos para consolidar."
        if dry_run:
            lines = [f"📋 Consolidación (dry-run): {len(candidates)} candidatos a promover a semántica:"]
            for c in candidates[:20]:
                meta = json.loads(c[2])
                lines.append(f"  [{c[0]}] {c[1][:60]}... (nivel: {meta.get('nivel', 'episodica')})")
            if len(candidates) > 20:
                lines.append(f"  ... y {len(candidates) - 20} más")
            cur.close()
            conn.close()
            return "\n".join(lines)
        promoted = 0
        for c in candidates:
            meta = json.loads(c[2])
            meta["nivel"] = "semantica"
            meta["consolidated_at"] = str(date.today())
            cur.execute("UPDATE memoria_vectorial SET metadatos = %s WHERE id = %s", (json.dumps(meta), c[0]))
            promoted += 1
        conn.commit()
        cur.close()
        conn.close()
        return f"✅ {promoted} recuerdos promovidos de episódica → semántica."

    try:
        return await asyncio.to_thread(_do)
    except Exception as e:
        return _tool_err("consolidate_hipocampo", e)


@mcp.tool()
async def review_automatica(max_age_days: int = 30, dry_run: bool = True) -> str:
    """
    Revisa reglas 'automatica' sin revisión en los últimos N días.

    Las reglas automatica son permanentes por diseño, pero pueden degradarse
    a 'semantica' si no han sido útiles (review_count=0) después de max_age_days.

    Con dry_run=True solo lista las reglas candidatas a degradación.
    Con dry_run=False las degrada a 'semantica' (no se borran, solo pierden
    inmunidad de compresión).

    Args:
        max_age_days: Edad máxima sin revisión antes de considerar degradación (default 30).
        dry_run: Si True, solo muestra qué se degradaría.

    Returns:
        Reporte de reglas encontradas.
    """

    def _do():
        from datetime import datetime, timezone, timedelta

        cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
        conn = _conn()
        cur = conn.cursor()
        cur.execute(
            """SELECT id, contenido, metadatos::text FROM memoria_vectorial
               WHERE metadatos->>'nivel' = 'automatica'
               ORDER BY id"""
        )
        rows = cur.fetchall()
        candidates = []
        for row in rows:
            meta = json.loads(row[2])
            review_count = int(meta.get("review_count", 0))
            created_str = meta.get("created_at") or meta.get("date") or ""
            try:
                created = datetime.fromisoformat(created_str)
                if created.tzinfo is None:
                    created = created.replace(tzinfo=timezone.utc)
                if created < cutoff and review_count == 0:
                    candidates.append((row[0], row[1][:80], created_str, review_count))
            except (ValueError, TypeError):
                if review_count == 0:
                    candidates.append((row[0], row[1][:80], created_str or "desconocida", review_count))
        if not candidates:
            cur.close()
            conn.close()
            return "✅ No hay reglas automatica pendientes de revisión."
        if dry_run:
            lines = [
                f"📋 Revisión de reglas automatica (dry-run, >{max_age_days}d, review_count=0):",
                f"   {len(candidates)} candidatas a degradación → semantica",
                "",
            ]
            for rid, content, created, rc in candidates[:20]:
                lines.append(f"  [{rid}] review_count={rc}, creada={created}")
                lines.append(f"       {content}...")
            if len(candidates) > 20:
                lines.append(f"  ... y {len(candidates) - 20} más")
            cur.close()
            conn.close()
            return "\n".join(lines)
        degraded = 0
        for rid, _, _, _ in candidates:
            cur.execute("SELECT metadatos FROM memoria_vectorial WHERE id=%s", (rid,))
            row = cur.fetchone()
            if row:
                meta = (row[0] or {}).copy()
                meta["nivel"] = "semantica"
                meta["degraded_at"] = str(date.today())
                meta["degraded_reason"] = "auto_review_expired"
                cur.execute("UPDATE memoria_vectorial SET metadatos=%s WHERE id=%s", (json.dumps(meta), rid))
                degraded += 1
        conn.commit()
        cur.close()
        conn.close()
        return f"✅ {degraded} reglas automatica degradadas a semantica por inactividad."

    try:
        return await asyncio.to_thread(_do)
    except Exception as e:
        return _tool_err("review_automatica", e)


@mcp.tool()
async def validate_immune_rule(rule_id: int) -> str:
    """
    Valida una regla inmunológica (Nivel 4).

    Analiza una regla 'automatica' marcada como REGLA INMUNOLÓGICA:
    1. Verifica snapshots pre-cambio vinculados en memory_links
    2. Detecta reglas contradictorias sobre el mismo archivo/proyecto
    3. Reporta reglas huérfanas (>30d sin enlaces entrantes)

    Args:
        rule_id: ID de la regla inmunológica a validar.

    Returns:
        Reporte de validación con recomendaciones.
    """

    def _do():
        conn = _conn()
        cur = conn.cursor()
        cur.execute(
            "SELECT contenido, metadatos::text FROM memoria_vectorial WHERE id=%s",
            (rule_id,),
        )
        row = cur.fetchone()
        if not row:
            cur.close()
            conn.close()
            return f"❌ No existe regla con id={rule_id}."
        content = row[0]
        meta = json.loads(row[1])
        if meta.get("nivel") != "automatica":
            cur.close()
            conn.close()
            return f"⚠️  La regla #{rule_id} no es nivel 'automatica' (es {meta.get('nivel', 'desconocido')})."
        lines = [f"🧬 Validación de regla inmunológica #{rule_id}:"]
        lines.append(f"   Contenido: {content[:100]}...")
        review_count = int(meta.get("review_count", 0))
        lines.append(f"   review_count: {review_count}")
        cur.execute(
            "SELECT target_id, relation_type, metadata FROM memory_links WHERE source_id=%s",
            (str(rule_id),),
        )
        links = cur.fetchall()
        incoming = 0
        cur.execute(
            "SELECT source_id FROM memory_links WHERE target_id=%s",
            (str(rule_id),),
        )
        incoming = len(cur.fetchall())
        lines.append(f"   Enlaces salientes: {len(links)} | Entrantes: {incoming}")
        for target_id, rel, link_meta in links:
            lines.append(f"      → [{target_id}] ({rel})")
        if incoming == 0 and review_count == 0:
            created_str = meta.get("created_at") or meta.get("date") or ""
            try:
                from datetime import datetime, timezone

                created = datetime.fromisoformat(created_str)
                if created.tzinfo is None:
                    created = created.replace(tzinfo=timezone.utc)
                age_days = (datetime.now(timezone.utc) - created).days
                if age_days > 30:
                    lines.append(
                        f"   ⚠️  Regla huérfana: {age_days}d sin uso ni enlaces. Considere degradar a semantica con review_automatica."
                    )
            except (ValueError, TypeError):
                pass
        import re

        filenames = re.findall(r"(?:archivo|file|snapshot)\s+(\S+)", content, re.IGNORECASE)
        if filenames:
            contradictions = []
            for fname in filenames[:3]:
                cur.execute(
                    """SELECT id, contenido FROM memoria_vectorial
                       WHERE id != %s AND metadatos->>'nivel' = 'automatica'
                       AND (contenido ILIKE %s OR contenido ILIKE %s)
                       LIMIT 5""",
                    (rule_id, f"%{fname}%", f"%REGLA INMUNOLÓGICA%{fname}%"),
                )
                for cid, ccontent in cur.fetchall():
                    contradictions.append((cid, ccontent[:80]))
            if contradictions:
                lines.append(f"   ⚠️  {len(contradictions)} reglas similares sobre los mismos archivos:")
                for cid, ccontent in contradictions:
                    lines.append(f"      [{cid}] {ccontent}...")
                lines.append("   Revise si hay contradicciones entre reglas.")
        cur.close()
        conn.close()
        if links:
            lines.append("   ✅ Tiene enlaces salientes — la regla está conectada al grafo.")
        return "\n".join(lines)

    try:
        return await asyncio.to_thread(_do)
    except Exception as e:
        return _tool_err("validate_immune_rule", e)


@mcp.tool()
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


@mcp.tool()
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


@mcp.tool()
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


@mcp.tool()
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


@mcp.tool()
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
            if info is None:
                return "❌ Dedup analysis returned None — possible config or DB connection issue"
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


@mcp.tool()
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
async def rollback_checkpoint(snapshot_id: int) -> str:
    """
    Revierte un checkpoint usando el snapshot guardado previamente.

    Busca el snapshot por ID y verifica qué IDs originales fueron comprimidos.
    Si los originales aún existen, reporta que no se necesita rollback.
    Si fueron eliminados, intenta restaurarlos.

    Args:
        snapshot_id: ID del snapshot [CHECKPOINT SNAPSHOT] guardado.

    Returns:
        Reporte de la operación de rollback.
    """

    def _do():
        conn = _conn()
        cur = conn.cursor()
        try:
            cur.execute(
                "SELECT contenido, metadatos::text FROM memoria_vectorial WHERE id=%s",
                (snapshot_id,),
            )
            row = cur.fetchone()
            if not row:
                return f"❌ No existe snapshot con id={snapshot_id}."
            content = row[0]
            meta = json.loads(row[1])
            if meta.get("tipo") != "checkpoint_snapshot":
                return f"❌ El registro {snapshot_id} no es un checkpoint snapshot (tipo={meta.get('tipo')})."

            import re

            ids_match = re.search(r"\[([0-9,\s]+)\]", content)
            if not ids_match:
                return "❌ No se encontraron IDs en el snapshot."
            original_ids = [int(x.strip()) for x in ids_match.group(1).split(",") if x.strip()]
            still_present = 0
            missing = 0
            for oid in original_ids:
                cur.execute("SELECT 1 FROM memoria_vectorial WHERE id=%s", (oid,))
                if cur.fetchone():
                    still_present += 1
                else:
                    missing += 1
            lines = [
                f"📦 Rollback snapshot #{snapshot_id}:",
                f"   Comprimidos: {meta.get('comprimidos_count', '?')}",
                f"   IDs rastreados: {len(original_ids)}",
                f"   Aún presentes: {still_present}",
                f"   Eliminados: {missing}",
            ]
            if missing > 0:
                lines.append("   ⚠️  Algunos originales fueron eliminados. Restauración no disponible.")
                lines.append("   Las memorias comprimidas permanecen como checkpoints en la DB.")
            else:
                lines.append("   ✅ Todos los originales aún existen. No se necesita rollback.")
            return "\n".join(lines)
        finally:
            cur.close()
            conn.close()

    try:
        return await asyncio.to_thread(_do)
    except Exception as e:
        return _tool_err("rollback_checkpoint", e)


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


@mcp.tool()
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


@mcp.tool()
async def preload_context(project_path: str = "", k: int = 8) -> str:
    """
    Pre-load context for a project or workspace. Extracts relevant memories
    from the project path and returns them as a compressed summary.

    Use this when starting work on a known project to restore working context.

    Args:
        project_path: Absolute path to the project or workspace.
                      If empty, uses current working directory.
        k: Number of relevant memories to retrieve (default 8, max 20).

    Returns:
        Compressed context summary with project-relevant memories.
    """
    if not project_path:
        project_path = os.getcwd()

    dirname = os.path.basename(os.path.normpath(project_path))
    segments = [s for s in os.path.normpath(project_path).split(os.sep) if s and len(s) > 2]
    keywords = list(dict.fromkeys(segments[-3:]))  # last 3 dir levels, deduped

    query = f"proyecto {dirname} " + " ".join(keywords)

    try:
        output, stats = await asyncio.to_thread(_search.search_with_stats, query, session_id="")
    except Exception as e:
        return f"Search failed for project context: {e}"

    if not output.strip():
        return f"No se encontraron memorias relevantes para {dirname}."

    result = await asyncio.to_thread(
        _compress.compress_hipocampo,
        query=query,
        k=min(k, 20),
        method="hybrid",
        include_metadata=False,
    )

    lines = [
        f"📂 Contexto precargado: {project_path}",
        f"   Palabras clave: {' · '.join(keywords)}",
        f"   Memorias recuperadas: {stats.get('results_count', 0)}",
    ]

    if "compressed" in result and result["compressed"]:
        lines.extend(["", "📝 Resumen:", result["compressed"]])

    lines.extend(
        [
            "",
            f"📊 Compresión: {result.get('original_len', 0)} → {result.get('compressed_len', 0)} chars "
            f"({result.get('ratio', 0) * 100:.0f}%)",
        ]
    )

    return "\n".join(lines)


# ─── MEMORY GRAPH — Helpers ────────────────────────────────────────────────────


def _compute_effective_weight(weight: float, last_accessed, decay_half_life_days: int = 90) -> float:
    if last_accessed is None:
        return weight
    try:
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        if last_accessed.tzinfo is None:
            last_accessed = last_accessed.replace(tzinfo=timezone.utc)
        days = (now - last_accessed).days
        if days <= 0:
            return weight
        decay = 0.5 ** (days / decay_half_life_days)
        return round(weight * decay, 4)
    except Exception:
        return weight


def _reinforce_link_db(cur, link_id: int):
    cur.execute("UPDATE memory_links SET reinforced_at = NOW(), last_accessed = NOW() WHERE id = %s", (link_id,))


def _fetch_effective_edges(conn, source_id):
    cur = conn.cursor()
    try:
        cur.execute(
            """SELECT target_id, relation_type, weight, id, last_accessed, reinforced_at
               FROM memory_links
               WHERE source_id = %s::text
               ORDER BY weight DESC, id""",
            (str(source_id),),
        )
        edges = []
        for target_id, rel_type, weight, link_id, last_accessed, reinforced_at in cur.fetchall():
            effective = _compute_effective_weight(weight, last_accessed)
            edges.append((target_id, rel_type, effective, link_id, weight, last_accessed))
        return edges
    finally:
        cur.close()


# ─── MEMORY GRAPH — Tools ────────────────────────────────────────────────────


@mcp.tool()
async def link_hipocampo(source_id: int, target_id: int, relation_type: str = "related", weight: float = 1.0) -> str:
    """
    Crea un enlace entre dos recuerdos en el grafo de memoria.

    Args:
        source_id: ID del recuerdo origen (numérico: memoria_vectorial; string: memory_items).
        target_id: ID del recuerdo destino.
        relation_type: Tipo de relación. Valores comunes:
                       "related" (default), "follow_up", "part_of",
                       "references", "similar", "chain", "validates", "contradicts".
        weight: Peso de la relación (0.0 a 1.0, default 1.0).

    Returns:
        Confirmación del enlace creado.
    """
    if str(source_id) == str(target_id):
        return "❌ No se puede enlazar un recuerdo consigo mismo."

    def _do():
        conn = _conn()
        cur = conn.cursor()
        try:
            sid = str(source_id)
            tid = str(target_id)
            for rid in (sid, tid):
                cur.execute("SELECT id FROM memory_items WHERE id = %s", (rid,))
                if cur.fetchone():
                    continue
                try:
                    cur.execute("SELECT id FROM memoria_vectorial WHERE id = %s::bigint", (rid,))
                    if cur.fetchone():
                        continue
                except psycopg2.Error:
                    pass
                return f"❌ No existe recuerdo con id={rid} en ninguna tabla."

            cur.execute(
                """INSERT INTO memory_links (source_id, target_id, relation_type, weight, reinforced_at)
                   VALUES (%s, %s, %s, %s, NOW()) RETURNING id""",
                (sid, tid, relation_type, weight),
            )
            link_id = cur.fetchone()[0]
            conn.commit()
            return f"✅ Enlace #{link_id} creado: [{sid}] --{relation_type}--> [{tid}] (peso={weight})"
        except psycopg2.Error as e:
            if "unique" in str(e).lower():
                return f"⚠️ Ya existe un enlace {relation_type} entre {source_id} y {target_id}."
            return f"❌ Error de BD: {e}"
        finally:
            cur.close()
            conn.close()

    try:
        return await asyncio.to_thread(_do)
    except Exception as e:
        return _tool_err("link_hipocampo", e)


@mcp.tool()
async def unlink_hipocampo(id: int = 0, source_id: int = 0, target_id: int = 0, relation_type: str = "") -> str:
    """
    Elimina un enlace del grafo de memoria.

    Args:
        id: ID del enlace a eliminar (si se conoce).
        source_id: Si no se provee id, elimina por source+target+type.
        target_id: ID destino (requerido si no hay id).
        relation_type: Tipo de relación (opcional si no hay id).

    Returns:
        Confirmación de eliminación.
    """

    def _do():
        conn = _conn()
        cur = conn.cursor()
        try:
            if id:
                cur.execute("DELETE FROM memory_links WHERE id = %s RETURNING id", (id,))
                if cur.fetchone():
                    conn.commit()
                    return f"✅ Enlace #{id} eliminado."
                return f"❌ No existe enlace con id={id}."
            elif source_id and target_id:
                if relation_type:
                    cur.execute(
                        "DELETE FROM memory_links WHERE source_id=%s::text AND target_id=%s::text AND relation_type=%s RETURNING id",
                        (str(source_id), str(target_id), relation_type),
                    )
                else:
                    cur.execute(
                        "DELETE FROM memory_links WHERE source_id=%s::text AND target_id=%s::text RETURNING id",
                        (str(source_id), str(target_id)),
                    )
                deleted = cur.fetchall()
                conn.commit()
                if deleted:
                    ids = [r[0] for r in deleted]
                    return f"✅ {len(ids)} enlace(s) eliminado(s): {ids}."
                return f"❌ No se encontró enlace entre {source_id} y {target_id}."
            else:
                return "❌ Debes proveer id, o source_id + target_id."
        finally:
            cur.close()
            conn.close()

    try:
        return await asyncio.to_thread(_do)
    except Exception as e:
        return _tool_err("unlink_hipocampo", e)


@mcp.tool()
async def graph_hipocampo(node_id: int = 0, depth: int = 2, max_nodes: int = 50) -> str:
    """
    Explora el grafo de memoria desde un nodo raíz.

    Args:
        node_id: ID del recuerdo raíz. Si es 0, lista todos los nodos
                 con enlaces (vista general).
        depth: Profundidad de exploración (default 2, max 5).
        max_nodes: Máximo de nodos a mostrar (default 50).

    Returns:
        Árbol ASCII del grafo de memoria.
    """
    depth = min(depth, 5)

    def _fetch_content_from_mv(rid: str) -> str | None:
        try:
            int(rid)
            conn = _conn()
            cur = conn.cursor()
            try:
                cur.execute("SELECT contenido FROM memoria_vectorial WHERE id=%s::bigint", (rid,))
                row = cur.fetchone()
                if row:
                    return row[0][:80].replace("\n", " ")
            finally:
                cur.close()
                conn.close()
        except (ValueError, TypeError):
            pass
        return None

    def _fetch_content_from_mi(rid: str) -> str | None:
        conn = _conn()
        cur = conn.cursor()
        try:
            cur.execute("SELECT summary FROM memory_items WHERE id=%s", (rid,))
            row = cur.fetchone()
            if row:
                return row[0][:80].replace("\n", " ")
        finally:
            cur.close()
            conn.close()
        return None

    def _fetch_content(rid) -> str:
        rid_str = str(rid)
        text = _fetch_content_from_mv(rid_str)
        if text:
            return f"[{rid}] {text}"
        text = _fetch_content_from_mi(rid_str)
        if text:
            return f"[{rid}] {text}"
        return f"[{rid}] (desconocido)"

    def _fetch_edges(rid) -> list[tuple]:
        conn = _conn()
        try:
            return _fetch_effective_edges(conn, rid)
        finally:
            conn.close()

    def _build_tree(rid: int, current_depth: int, visited: set) -> list[str]:
        if len(visited) >= max_nodes or current_depth > depth:
            return ["..."]

        if rid in visited:
            return [f"↩ [{rid}] (ya visitado)"]
        visited.add(rid)

        label = _fetch_content(rid)
        lines = [label]

        if current_depth < depth:
            edges = _fetch_edges(rid)
            for target_id, rel_type, effective_weight, link_id, raw_weight, last_accessed in edges:
                indent = "  " * (current_depth + 1)
                prefix = f"{indent}└── ({rel_type}, w={effective_weight}) "
                child_lines = _build_tree(target_id, current_depth + 1, visited)
                if child_lines:
                    lines.append(prefix + child_lines[0])
                    for cl in child_lines[1:]:
                        lines.append(indent + "   " + cl)

        return lines

    def _list_all():
        conn = _conn()
        cur = conn.cursor()
        try:
            cur.execute(
                """SELECT COUNT(DISTINCT source_id) as nodes,
                          COUNT(*) as edges,
                          COUNT(DISTINCT relation_type) as types
                   FROM memory_links"""
            )
            stats = cur.fetchone()
            cur.execute("""
                SELECT source_id, COUNT(*) as link_count
                FROM memory_links GROUP BY source_id
                ORDER BY link_count DESC LIMIT 20
            """)
            top = cur.fetchall()
            lines = [
                "📊 GRAFO DE MEMORIA — Vista General",
                f"   Nodos con enlaces: {stats[0]}",
                f"   Total enlaces: {stats[1]}",
                f"   Tipos de relación: {stats[2]}",
                "",
                "🏆 Nodos más conectados:",
            ]
            for src, cnt in top:
                content = _fetch_content(src)
                lines.append(f"   · {content} ({cnt} enlaces)")
            return "\n".join(lines)
        finally:
            cur.close()
            conn.close()

    try:
        if node_id == 0:
            return await asyncio.to_thread(_list_all)

        tree = await asyncio.to_thread(_build_tree, str(node_id), 0, set())
        return f"🌳 Grafo desde [{node_id}] (depth={depth}):\n" + "\n".join(tree)
    except Exception as e:
        return _tool_err("graph_hipocampo", e)


@mcp.tool()
async def path_hipocampo(from_id: int, to_id: int, max_depth: int = 5) -> str:
    """
    Encuentra el camino más corto entre dos recuerdos en el grafo de memoria.

    Args:
        from_id: ID del recuerdo origen.
        to_id: ID del recuerdo destino.
        max_depth: Profundidad máxima de búsqueda (default 5, max 10).

    Returns:
        Camino encontrado como secuencia de nodos.
    """
    max_depth = min(max_depth, 10)

    def _fetch_content(rid) -> str:
        rid_str = str(rid)
        conn = _conn()
        cur = conn.cursor()
        try:
            try:
                int(rid_str)
                cur.execute("SELECT contenido FROM memoria_vectorial WHERE id=%s::bigint", (rid_str,))
                row = cur.fetchone()
                if row:
                    return row[0][:60].replace("\n", " ")
            except (ValueError, TypeError):
                pass
            cur.execute("SELECT summary FROM memory_items WHERE id=%s", (rid_str,))
            row = cur.fetchone()
            if row:
                return row[0][:60].replace("\n", " ")
            return f"[{rid}]"
        finally:
            cur.close()
            conn.close()

    def _fetch_neighbors(rid) -> list:
        conn = _conn()
        cur = conn.cursor()
        try:
            cur.execute(
                "SELECT target_id, id FROM memory_links WHERE source_id=%s "
                "UNION ALL SELECT source_id, id FROM memory_links WHERE target_id=%s",
                (str(rid), str(rid)),
            )
            return [(r[0], r[1]) for r in cur.fetchall()]
        finally:
            cur.close()
            conn.close()

    def _bfs():
        from collections import deque

        start, goal = str(from_id), str(to_id)
        visited = {start: (None, None)}
        q = deque([start])
        while q:
            current = q.popleft()
            if current == goal:
                path = []
                link_ids = []
                node = current
                while node is not None:
                    path.append(node)
                    parent, link_id = visited[node]
                    if link_id is not None:
                        link_ids.append(link_id)
                    node = parent
                path.reverse()
                link_ids.reverse()
                return path, link_ids
            for nb, link_id in _fetch_neighbors(current):
                if nb not in visited:
                    visited[nb] = (current, link_id)
                    q.append(nb)
            if len(visited) > 1000:
                break
        return None, []

    def _reinforce_path(link_ids):
        if not link_ids:
            return
        conn = _conn()
        cur = conn.cursor()
        try:
            for lid in link_ids:
                _reinforce_link_db(cur, lid)
            conn.commit()
        finally:
            cur.close()
            conn.close()

    try:
        if from_id == to_id:
            label = await asyncio.to_thread(_fetch_content, from_id)
            return f"📍 Origen = destino: {label}"

        path, link_ids = await asyncio.to_thread(_bfs)
        if not path or len(path) > max_depth + 1:
            return f"❌ No se encontró camino entre [{from_id}] y [{to_id}] (hasta depth={max_depth})."

        await asyncio.to_thread(_reinforce_path, link_ids)

        lines = [f"🔗 Camino encontrado ({len(path) - 1} saltos):"]
        for i, nid in enumerate(path):
            label = await asyncio.to_thread(_fetch_content, nid)
            arrow = " → " if i < len(path) - 1 else ""
            lines.append(f"  {i}.[{nid}] {label}{arrow}")
        return "\n".join(lines)
    except Exception as e:
        return _tool_err("path_hipocampo", e)


# ─── RAG DE CÓDIGO — Tools ────────────────────────────────────────────────────


@mcp.tool()
async def index_project(project_path: str = "", force: bool = False) -> str:
    """
    Indexa archivos de código fuente de un proyecto en Hipocampo (RAG).

    Escanea archivos PHP, JS, TS, Python, SQL, HTML, CSS, JSON, YAML,
    los divide en chunks significativos y los guarda como recuerdos con
    embedding para búsqueda semántica.

    La segunda corrida solo indexa archivos modificados (por mtime).

    Args:
        project_path: Ruta absoluta del proyecto a indexar.
                      Si está vacía, usa el directorio actual.
        force: Si True, re-indexa todo aunque no haya cambios.

    Returns:
        Estadísticas de la indexación.
    """
    if not project_path:
        project_path = os.getcwd()

    try:
        stats = await asyncio.to_thread(_indexer.index_project, project_path, force)
        return _indexer.format_stats(stats, project_path)
    except Exception as e:
        return f"❌ Error indexando proyecto: {e}"


@mcp.tool()
async def search_code(query: str, k: int = 5, language: str = "") -> str:
    """
    Busca código fuente indexado en Hipocampo (RAG).

    Similar a search_hipocampo pero filtra solo recuerdos de tipo
    code_snippet y devuelve fragmentos de código real con
    ubicación de archivo.

    Args:
        query: Consulta en lenguaje natural.
        k: Número de resultados (default 5, max 20).
        language: Filtrar por lenguaje (php, javascript, python, sql, etc.).
                  Vacío = todos los lenguajes.

    Returns:
        Fragmentos de código relevantes con metadatos de archivo.
    """
    k = min(k, 20)

    def _do():
        import time

        t0 = time.time()
        emb = get_embedding(query)
        if not emb:
            return "❌ No se pudo generar embedding para la consulta."

        conn = get_conn()
        cur = conn.cursor()
        lang_filter = "AND metadatos->>'language' = %s" if language else ""
        params = [emb, emb]
        if language:
            params.append(language)

        cur.execute(
            f"""SELECT id, contenido, metadatos::text,
                       (embedding <=> %s::vector(1024)) AS dist
                FROM memoria_vectorial
                WHERE metadatos->>'source' = 'code_index'
                  AND metadatos->>'status' IS DISTINCT FROM 'obsolete'
                  {lang_filter}
                ORDER BY (embedding <=> %s::vector(1024))
                LIMIT %s""",
            params + [k],
        )
        rows = cur.fetchall()
        cur.close()
        conn.close()

        if not rows:
            return f"No se encontró código relevante para: {query}"

        latency = int((time.time() - t0) * 1000)
        lines = [f"🔍 Resultados de código para: {query!r}  ({latency}ms)"]
        for i, row in enumerate(rows, 1):
            rid, content, meta_str, dist = row
            score = round((1 - dist) * 100, 1)
            meta = json.loads(meta_str)
            rel_path = meta.get("rel_path", "?")
            lang = meta.get("language", "?")
            lines.extend(
                [
                    "",
                    f"── [{i}] {rel_path}  (score={score:.1f})  {lang}",
                    f"    Líneas {meta.get('line_start', '?')}-{meta.get('line_end', '?')}",
                    f"```{lang}",
                    content[:600],
                    "```" if len(content) > 600 else "",
                ]
            )
        return "\n".join(lines)

    try:
        return await asyncio.to_thread(_do)
    except Exception as e:
        return _tool_err("search_code", e)


# ─── GRAPH DECAY — Tool ──────────────────────────────────────────────────────


@mcp.tool()
async def decay_hipocampo(dry_run: bool = True) -> str:
    """
    Aplica decaimiento temporal a los pesos de los enlaces del grafo.

    Los enlaces pierden peso exponencialmente si no son accedidos.
    Half-life: 90 días (el peso se reduce a la mitad cada 90 días sin acceso).

    Con dry_run=True (default) solo muestra el estado actual sin modificar.
    Con dry_run=False aplica el decaimiento y elimina enlaces con peso < 0.01.

    Returns:
        Reporte del decaimiento aplicado.
    """

    def _do():
        conn = _conn()
        cur = conn.cursor()
        try:
            cur.execute("""
                SELECT id, source_id, target_id, relation_type, weight,
                       COALESCE(last_accessed, created_at) as effective_last,
                       reinforced_at
                FROM memory_links
                ORDER BY COALESCE(last_accessed, created_at) ASC
            """)
            rows = cur.fetchall()

            if not rows:
                return "📊 No hay enlaces en el grafo."

            total = len(rows)
            decayed = 0
            dead = 0
            lines = [
                "🧠 DECAIMIENTO DE ENLACES — Análisis del Grafo",
                "   Half-life: 90 días",
                f"   Total enlaces: {total}",
                "",
            ]

            for link_id, src, tgt, rel, weight, last_acc, reinf in rows:
                effective = _compute_effective_weight(weight, last_acc)

                if effective < weight * 0.99:
                    if not dry_run:
                        cur.execute(
                            "UPDATE memory_links SET weight = %s WHERE id = %s",
                            (effective, link_id),
                        )
                    decayed += 1
                    if effective < 0.01:
                        if not dry_run:
                            cur.execute(
                                "DELETE FROM memory_links WHERE id = %s",
                                (link_id,),
                            )
                        dead += 1

            if not dry_run:
                conn.commit()

            lines.append(f"   Enlaces con decaimiento: {decayed}")
            lines.append(f"   Enlaces muertos (peso < 0.01): {dead}")
            lines.append("")

            if dry_run:
                lines.append("🔍 Modo dry_run — no se modificaron datos.")
                lines.append("   Usa dry_run=False para aplicar los cambios.")
            else:
                lines.append("✅ Decaimiento aplicado.")

            return "\n".join(lines)
        finally:
            cur.close()
            conn.close()

    try:
        return await asyncio.to_thread(_do)
    except Exception as e:
        return _tool_err("decay_hipocampo", e)


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
    _init_memory_links_table()
    init_pool()
    _auto_checkpoint()

    http_port = args.http_port
    if not http_port and args.transport == "http":
        http_port = 8001

    sse_port = args.sse
    if not sse_port and args.transport == "sse":
        sse_port = 8001

    if http_port:
        port = http_port
        host = args.host
        logger.info("🔌 Iniciando Hipocampo MCP Server (Streamable HTTP) en %s:%d", host, port)
        mcp.settings.port = port
        mcp.settings.host = host
        mcp.run(transport="streamable-http")
    elif sse_port:
        logger.warning("⚠️  --sse está deprecado desde spec MCP 2025-03-26. Usa --http en su lugar.")
        logger.info("🔌 Iniciando Hipocampo MCP Server (SSE) en puerto %d", sse_port)
        mcp.settings.port = sse_port
        mcp.run(transport="sse")
    else:
        logger.info("🔌 Iniciando Hipocampo MCP Server (stdio)")
        mcp.run()
