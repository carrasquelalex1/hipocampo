#!/usr/bin/env python3
"""Hipocampo MCP Server v3 — MCP Native con FastMCP

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
import subprocess
import logging
import sys
import os
import json
from datetime import date

import uuid

import psycopg2
from openai import OpenAI
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.server import ToolAnnotations
from starlette.responses import HTMLResponse

# ─── CONFIGURACIÓN ─────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

PYTHON_BIN = sys.executable
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SEARCH_SCRIPT = os.path.join(BASE_DIR, "hipocampo_search.py")
HEALTH_SCRIPT = os.path.join(BASE_DIR, "hipocampo_health.py")
STATS_SCRIPT = os.path.join(BASE_DIR, "hipocampo_stats.py")
DEDUP_SCRIPT = os.path.join(BASE_DIR, "hipocampo_dedup.py")
CHECKPOINT_SCRIPT = os.path.join(BASE_DIR, "hipocampo_checkpoint.py")
DB_HOST = os.getenv("DB_HOST", "/var/run/postgresql")
DB_USER = os.getenv("DB_USER", "alex")
DB_NAME = os.getenv("DB_NAME", "hipocampo_db")
ENV_PATH = os.getenv("ENV_PATH", os.path.join(BASE_DIR, "..", ".env"))

# ─── INICIALIZACIÓN MCP ─────────────────────────────────────────────────────
mcp = FastMCP("hipocampo")


@mcp.tool(annotations=ToolAnnotations(
    readOnlyHint=True,
))
def search_hipocampo(query: str) -> str:
    """
    Busca en el Hipocampo (memoria dual con SSC / BIRE v3.6).

    Es solo lectura — no modifica datos, no tiene efectos secundarios.
    Sin límites de tasa (rate limits).

    Realiza búsqueda semántica + léxica híbrida en las bases de datos de
    memoria del usuario, incluyendo memoria técnica (*memoria_vectorial*) y
    de perfil (*memory_items*).

    Para búsquedas rápidas cuando el nombre corto sea preferido, usar
    quick_hipocampo_search (alias idéntico). Esta herramienta es la
    versión completa con nombre descriptivo.

    Args:
        query: Texto de búsqueda en lenguaje natural. Máximo 500 caracteres.
               Ejemplos: "proyecto contable", "perro", "planta medicinal",
               "API REST en Python", "gusta del té".

    Returns:
        Resultados formateados del BIRE como texto plano.
        Incluye: contenido encontrado, scores de relevancia, y metadatos.
        Si no hay coincidencias, indica búsqueda exitosa pero sin resultados.
    """
    import time
    t0 = time.time()
    try:
        result = subprocess.run(
            [PYTHON_BIN, SEARCH_SCRIPT, query],
            capture_output=True,
            text=True,
            check=True,
        )
        latency_ms = int((time.time() - t0) * 1000)
        logger.info("Hipocampo search OK query=%r latency=%dms", query, latency_ms)

        results_count = 0
        top_score = 0.0
        avg_score = 0.0
        for line in result.stdout.split("\n"):
            if "📍" in line:
                results_count += 1
            if "Score promedio:" in line:
                parts = line.split(":")
                if len(parts) >= 2:
                    try:
                        avg_score = float(parts[1].strip())
                    except:
                        pass
            if "🏆 Mejor score:" in line:
                parts = line.split(":")
                if len(parts) >= 2:
                    try:
                        top_score = float(parts[1].strip())
                    except:
                        pass

        subprocess.run(
            [PYTHON_BIN, STATS_SCRIPT, "--record", query, str(latency_ms), str(results_count), "ssc", str(top_score), str(avg_score)],
            capture_output=True,
            timeout=10,
        )

        return result.stdout

    except subprocess.CalledProcessError as e:
        logger.error("Hipocampo search error: %s", e.stderr)
        return f"❌ Error en búsqueda Hipocampo:\n{e.stderr}"


@mcp.tool(annotations=ToolAnnotations(
    readOnlyHint=True,
))
def quick_hipocampo_search(query: str) -> str:
    """
    Búsqueda rápida en el Hipocampo (alias corto de search_hipocampo).

    Es solo lectura — no modifica datos, no tiene efectos secundarios.
    Comportamiento y salida idénticos a search_hipocampo.

    Útil cuando el cliente MCP prefiera nombres de herramienta más cortos.
    Para nombre descriptivo, usar search_hipocampo.

    Args:
        query: Texto de búsqueda en lenguaje natural. Igual que
               search_hipocampo. Ej: "API REST en Python", "presupuesto".

    Returns:
        Mismo formato que search_hipocampo: resultados como texto plano
        con scores de relevancia y metadatos.
    """


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

def _generar_embedding(texto: str) -> list[float]:
    load_dotenv(ENV_PATH)
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
    return resp.data[0].embedding


def _conn():
    return psycopg2.connect(host=DB_HOST, user=DB_USER, dbname=DB_NAME)


# ─── HERRAMIENTA: GUARDAR ────────────────────────────────────────────────────


@mcp.tool()
def save_hipocampo(
    content: str,
    memory_type: str = "event",
    code: str = "",
    categories: list[str] | None = None,
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

    Returns:
        Confirmación con el ID asignado.
    """
    try:
        logger.info("🧠 Guardando en Hipocampo: content=%r...", content[:80])
        embedding = _generar_embedding(content)
        metadatos = {
            "type": memory_type,
            "code": code or "",
            "categories": categories or [],
            "date": str(date.today()),
            "source": "mcp",
        }
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
        logger.info("✅ Guardado id=%s", row_id)
        return f"✅ Guardado en Hipocampo (id={row_id})"

    except Exception as e:
        logger.error("❌ Error al guardar: %s", e)
        return f"❌ Error al guardar en Hipocampo: {e}"


@mcp.tool()
def profile_hipocampo(
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
    try:
        logger.info("👤 Guardando perfil: %r...", summary[:80])
        embedding = _generar_embedding(summary)
        conn = _conn()
        cur = conn.cursor()
        cat_list = categories or ["personal_info"]
        row_id = str(uuid.uuid4())

        cur.execute(
            """INSERT INTO memory_items (id, summary, memory_type, extra, embedding, created_at, updated_at)
               VALUES (%s, %s, 'profile', %s, %s::vector(1024), NOW(), NOW())""",
            (row_id, summary, json.dumps({"extra": extra, "categories": cat_list, "date": str(date.today())}), embedding),
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

    except Exception as e:
        logger.error("❌ Error al guardar perfil: %s", e)
        return f"❌ Error al guardar perfil: {e}"


# ─── HERRAMIENTAS: CRUD (UPDATE / DELETE) ──────────────────────────────────────


@mcp.tool(annotations=ToolAnnotations(
    destructiveHint=True,
    idempotentHint=True,
))
def update_hipocampo(
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
        code: Nuevo código o etiqueta (opcional).
        categories: Nueva lista de categorías (opcional).

    Returns:
        Confirmación de la actualización.
    """
    try:
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
            embedding = _generar_embedding(content)
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
        logger.info("✅ Actualizado id=%s", id)
        return f"✅ Actualizado recuerdo id={id}"
    except Exception as e:
        logger.error("❌ Error al actualizar: %s", e)
        return f"❌ Error al actualizar recuerdo: {e}"


@mcp.tool(annotations=ToolAnnotations(
    destructiveHint=True,
))
def delete_hipocampo(id: int) -> str:
    """
    Elimina un recuerdo del Hipocampo (memoria_vectorial) por su ID.

    Esta operación es irreversible. Una vez eliminado, el recuerdo
    no podrá recuperarse ni aparecerá en búsquedas futuras.

    Args:
        id: ID numérico del recuerdo a eliminar.

    Returns:
        Confirmación de eliminación.
    """
    try:
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
        logger.info("🗑️ Eliminado id=%s", id)
        return f"🗑️ Eliminado recuerdo id={id}"
    except Exception as e:
        logger.error("❌ Error al eliminar: %s", e)
        return f"❌ Error al eliminar recuerdo: {e}"


# ─── HERRAMIENTA: HEALTH CHECK ───────────────────────────────────────────────


@mcp.tool()
def hipocampo_health() -> str:
    """
    Ejecuta un health check completo del sistema Hipocampo.

    Verifica: PostgreSQL, NVIDIA API, tablas, espacio en disco, extensiones.

    Returns:
        Reporte formateado del estado del sistema.
    """
    try:
        result = subprocess.run(
            [PYTHON_BIN, HEALTH_SCRIPT],
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result.stdout or "✅ Health check completado (sin salida)"
    except subprocess.TimeoutExpired:
        return "❌ Health check timed out (>30s)"
    except Exception as e:
        logger.error("Health check error: %s", e)
        return f"❌ Error en health check: {e}"


@mcp.tool()
def hipocampo_auto_repair() -> str:
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
        result = subprocess.run(
            [PYTHON_BIN, HEALTH_SCRIPT, "--repair"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        return result.stdout or "🔧 Auto-repair completado (sin salida)"
    except subprocess.TimeoutExpired:
        return "❌ Auto-repair timed out (>60s)"
    except Exception as e:
        logger.error("Auto-repair error: %s", e)
        return f"❌ Error en auto-repair: {e}"


# ─── HERRAMIENTAS: STATS Y AJUSTE DINÁMICO ────────────────────────────────────


@mcp.tool()
def hipocampo_stats() -> str:
    """
    Muestra estadísticas de rendimiento del sistema Hipocampo.

    Analiza latencia de queries, métodos usados, scores promedios
    y da recomendaciones de optimización.

    Returns:
        Reporte de métricas y recomendaciones.
    """
    try:
        result = subprocess.run(
            [PYTHON_BIN, STATS_SCRIPT, "--analyze"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result.stdout or "📊 Stats completados"
    except Exception as e:
        logger.error("Stats error: %s", e)
        return f"❌ Error en stats: {e}"


@mcp.tool(annotations=ToolAnnotations(
    destructiveHint=True,
    idempotentHint=True,
))
def hipocampo_tune() -> str:
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
        result = subprocess.run(
            [PYTHON_BIN, STATS_SCRIPT, "--tune"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result.stdout or "🔧 Tune completado"
    except Exception as e:
        logger.error("Tune error: %s", e)
        return f"❌ Error en tune: {e}"


# ─── HERRAMIENTAS: MANTENIMIENTO (FASE 3) ─────────────────────────────────────


@mcp.tool(annotations=ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=True,
    idempotentHint=True,
))
def hipocampo_dedup(merge: bool = False) -> str:
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
        args = [PYTHON_BIN, DEDUP_SCRIPT]
        if merge:
            args.append("--merge")
        result = subprocess.run(args, capture_output=True, text=True, timeout=120)
        return result.stdout or "✅ Dedup completado"
    except Exception as e:
        logger.error("Dedup error: %s", e)
        return f"❌ Error en dedup: {e}"


@mcp.tool(annotations=ToolAnnotations(
    destructiveHint=True,
    idempotentHint=True,
))
def hipocampo_checkpoint(dry_run: bool = True) -> str:
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
        args = [PYTHON_BIN, CHECKPOINT_SCRIPT]
        if dry_run:
            args.append("--dry-run")
        else:
            args.append("--force")
        result = subprocess.run(args, capture_output=True, text=True, timeout=60)
        return result.stdout or "✅ Checkpoint completado"
    except Exception as e:
        logger.error("Checkpoint error: %s", e)
        return f"❌ Error en checkpoint: {e}"


@mcp.tool()
def hipocampo_maintenance() -> str:
    """
    Ejecuta el ciclo completo de mantenimiento:
    1. Health check → auto-repair si es necesario
    2. Dedup → fusiona duplicados
    3. Checkpoint → comprime memorias antiguas
    4. Tune → ajusta thresholds según métricas

    Returns:
        Reporte consolidado del mantenimiento.
    """
    report_parts = []
    try:
        r = subprocess.run([PYTHON_BIN, HEALTH_SCRIPT, "--repair"], capture_output=True, text=True, timeout=60)
        report_parts.append(f"🔧 Repair: {'✅' if 'repaired' in r.stdout else '⏭️'}")
    except:
        report_parts.append("🔧 Repair: ❌")

    try:
        r = subprocess.run([PYTHON_BIN, DEDUP_SCRIPT, "--merge"], capture_output=True, text=True, timeout=120)
        report_parts.append(f"🧹 Dedup: ✅ ({sum(1 for c in r.stdout if c=='✅')} ops)")
    except:
        report_parts.append("🧹 Dedup: ❌")

    try:
        r = subprocess.run([PYTHON_BIN, CHECKPOINT_SCRIPT, "--force"], capture_output=True, text=True, timeout=60)
        report_parts.append(f"📦 Checkpoint: ✅")
    except:
        report_parts.append("📦 Checkpoint: ❌")

    try:
        r = subprocess.run([PYTHON_BIN, STATS_SCRIPT, "--tune"], capture_output=True, text=True, timeout=30)
        report_parts.append(f"⚙️ Tune: ✅")
    except:
        report_parts.append("⚙️ Tune: ❌")

    return "📋 Mantenimiento completo:\n" + "\n".join(report_parts)


DEMO_HTML = """<!DOCTYPE html>
<html lang="es">
<head><meta charset="utf-8"><title>Hipocampo — Memoria Dual para IA</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;700&family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
:root{--bg:#0a0a0f;--surface:#12121a;--border:#1e1e2e;--text:#c4c4cf;--text-dim:#6b6b7e;--accent:#7c5cfc;--accent-glow:rgba(124,92,252,.25);--accent-light:#a78bfa;--green:#34d399;--radius:16px;--radius-sm:10px}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:Inter,system-ui,sans-serif;background:var(--bg);color:var(--text);min-height:100vh}
a{color:var(--accent-light);text-decoration:none}
nav{display:flex;align-items:center;justify-content:space-between;padding:16px 32px;border-bottom:1px solid var(--border);background:var(--surface)}
nav .logo{display:flex;align-items:center;gap:10px;font-weight:700;font-size:1.15rem;color:#fff}
nav .logo span{background:var(--accent);color:#fff;border-radius:8px;padding:2px 8px;font-size:.7rem;font-weight:600;margin-left:6px}
nav .links{display:flex;gap:20px;font-size:.85rem;font-weight:500}
nav .links a{color:var(--text-dim);transition:color .2s}
nav .links a:hover{color:#fff}
.hero{text-align:center;padding:60px 20px 40px;border-bottom:1px solid var(--border)}
.hero h1{font-size:2.8rem;font-weight:800;color:#fff;letter-spacing:-.03em;line-height:1.1}
.hero h1 em{font-style:normal;background:linear-gradient(135deg,var(--accent),var(--accent-light));-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.hero p{color:var(--text-dim);font-size:1.05rem;margin-top:12px;max-width:480px;margin:12px auto 0;line-height:1.5}
.hero .badges{display:flex;gap:8px;justify-content:center;margin-top:16px;flex-wrap:wrap}
.hero .badge{font-size:.75rem;padding:4px 12px;border-radius:999px;border:1px solid var(--border);color:var(--text-dim);font-weight:500}
.hero .badge.active{border-color:var(--accent);color:var(--accent-light);background:var(--accent-glow)}
.container{max-width:880px;margin:0 auto;padding:32px 20px}
.tabs{display:flex;gap:4px;background:var(--surface);border-radius:10px;padding:4px;border:1px solid var(--border);margin-bottom:24px}
.tab{padding:10px 20px;border-radius:8px;font-size:.85rem;font-weight:500;cursor:pointer;color:var(--text-dim);transition:all .2s;border:none;background:none;font-family:inherit}
.tab:hover{color:var(--text)}
.tab.active{background:var(--accent);color:#fff;box-shadow:0 0 20px var(--accent-glow)}
.panel{display:none}
.panel.active{display:block}
.card{background:var(--surface);border-radius:16px;padding:24px;border:1px solid var(--border)}
.card .label{font-size:.75rem;font-weight:600;text-transform:uppercase;letter-spacing:.06em;color:var(--text-dim);margin-bottom:12px}
input,textarea,select{width:100%;padding:12px 14px;border-radius:10px;border:1px solid var(--border);background:var(--bg);color:var(--text);font-size:.9rem;font-family:inherit;transition:border-color .2s;outline:none}
input:focus,textarea:focus,select:focus{border-color:var(--accent);box-shadow:0 0 0 3px var(--accent-glow)}
textarea{resize:vertical;min-height:70px;font-family:JetBrains Mono,monospace;font-size:.85rem}
select{appearance:none;cursor:pointer}
.btn{display:inline-flex;align-items:center;gap:6px;padding:10px 20px;border-radius:10px;font-weight:600;font-size:.85rem;cursor:pointer;border:none;font-family:inherit;transition:all .2s}
.btn-primary{background:var(--accent);color:#fff}
.btn-primary:hover{box-shadow:0 0 24px var(--accent-glow);transform:translateY(-1px)}
.btn-ghost{background:transparent;color:var(--text-dim);padding:8px 12px}
.btn-ghost:hover{color:var(--text);background:var(--bg)}
.btn-sm{padding:6px 14px;font-size:.8rem}
.flex{display:flex;gap:8px;flex-wrap:wrap}
.grid-2{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.output{background:var(--bg);border-radius:10px;padding:16px;overflow:auto;font-size:.82rem;max-height:360px;border:1px solid var(--border);margin-top:12px;white-space:pre-wrap;line-height:1.5;font-family:JetBrains Mono,monospace;color:var(--text-dim)}
.output:empty{display:none}
.output .ok{color:var(--green)}
.status-bar{position:fixed;bottom:0;left:0;right:0;background:var(--surface);border-top:1px solid var(--border);padding:10px 32px;display:flex;align-items:center;justify-content:space-between;font-size:.8rem;color:var(--text-dim)}
.status-bar .dot{width:8px;height:8px;border-radius:50%;display:inline-block;margin-right:6px;background:var(--green);box-shadow:0 0 8px rgba(52,211,153,.4)}
@media(max-width:640px){.hero h1{font-size:1.8rem}.grid-2{grid-template-columns:1fr}nav{padding:12px 16px}}
</style>
</head>
<body>
<nav>
  <div class="logo">
    <svg width="28" height="28" viewBox="0 0 32 32" fill="none"><rect width="32" height="32" rx="8" fill="#7c5cfc"/><path d="M16 6c-4 0-7 2.5-7 7 0 3.5 2 5.5 7 9 5-3.5 7-5.5 7-9 0-4.5-3-7-7-7zm0 9a2 2 0 110-4 2 2 0 010 4z" fill="#fff"/></svg>
    Hipocampo <span>v3.8</span>
  </div>
  <div class="links">
    <a href="https://github.com/carrasquelalex1/hipocampo" target="_blank">GitHub</a>
    <a href="https://glama.ai/mcp/servers/carrasquelalex1/hipocampo" target="_blank">Glama</a>
    <a href="https://registry.modelcontextprotocol.io" target="_blank">MCP Registry</a>
  </div>
</nav>

<section class="hero">
  <h1><em>Hipocampo</em> es la memoria de tu agente</h1>
  <p>Busca, guarda y gestiona recuerdos con búsqueda semántica + decaimiento temporal.</p>
  <div class="badges">
    <span class="badge active">🧠 Memoria Dual</span>
    <span class="badge">⚡ BIRE v3.7</span>
    <span class="badge">🔍 Embeddings 1024d</span>
    <span class="badge">📡 16 Tools MCP</span>
  </div>
</section>

<div class="container">
  <div class="tabs">
    <button class="tab active" data-tab="search">🔍 Buscar</button>
    <button class="tab" data-tab="save">💾 Guardar</button>
    <button class="tab" data-tab="health">❤️ Salud</button>
  </div>

  <div class="panel active" id="panel-search">
    <div class="card">
      <div class="label">Consulta semántica</div>
      <div class="flex" style="margin-bottom:10px">
        <input id="query" placeholder="Ej: proyecto contable, planta medicinal, API REST en Python" style="flex:1;margin-bottom:0">
        <button class="btn btn-primary" onclick="search()">Buscar</button>
        <button class="btn btn-ghost btn-sm" onclick="clean('query','results')">✕</button>
      </div>
      <div class="output" id="results"></div>
    </div>
  </div>

  <div class="panel" id="panel-save">
    <div class="card">
      <div class="label">Nuevo recuerdo</div>
      <textarea id="content" placeholder="¿Qué quieres que Hipocampo recuerde?"></textarea>
      <div class="grid-2">
        <div><label style="font-size:.75rem;color:var(--text-dim);margin-bottom:4px;display:block">Tipo</label><select id="type"><option value="event">event</option><option value="decision">decision</option><option value="profile">profile</option></select></div>
        <div><label style="font-size:.75rem;color:var(--text-dim);margin-bottom:4px;display:block">Código</label><input id="code" placeholder="opcional: bugfix, feature"></div>
      </div>
      <div class="flex" style="margin-top:4px">
        <button class="btn btn-primary" onclick="save()">Guardar</button>
        <button class="btn btn-ghost btn-sm" onclick="clean('content','saveResult')">✕</button>
      </div>
      <div class="output" id="saveResult"></div>
    </div>
  </div>

  <div class="panel" id="panel-health">
    <div class="card">
      <div class="label">Diagnóstico del sistema</div>
      <p style="color:var(--text-dim);font-size:.85rem;margin-bottom:14px">Verifica PostgreSQL, API de embeddings, disco y extensiones.</p>
      <button class="btn btn-primary" onclick="health()">Ejecutar health check</button>
      <div class="output" id="healthResult"></div>
    </div>
  </div>
</div>

<div class="status-bar">
  <span><span class="dot"></span>Hipocampo activo</span>
  <span id="status">Listo para consultas</span>
</div>

<script>
function st(m){document.getElementById('status').textContent=m}
function tab(n){document.querySelectorAll('.tab').forEach(t=>t.classList.toggle('active',t.dataset.tab===n));document.querySelectorAll('.panel').forEach(p=>p.classList.toggle('active',p.id==='panel-'+n))}
document.querySelectorAll('.tab').forEach(t=>t.onclick=()=>tab(t.dataset.tab))
function clean(...a){a.forEach(i=>{const e=document.getElementById(i);if(e)e.value='';const o=document.getElementById(i+'Result');if(o)o.innerHTML=''})}
async function search(){const q=document.getElementById('query').value.trim();if(!q)return st('✕ Escribe una consulta');st('🔍 Buscando...');try{const r=await fetch('/api/search?q='+encodeURIComponent(q)),d=await r.json();document.getElementById('results').textContent=d.ok?d.results:'✕ '+d.error;st(d.ok?'✅ Busqueda completada ('+d.latency_ms+'ms)':'✕ Error')}catch(e){st('✕ '+e.message)}}
async function save(){const c=document.getElementById('content').value.trim();if(!c)return st('✕ Escribe contenido');st('💾 Guardando...');try{const r=await fetch('/api/save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({content:c,type:document.getElementById('type').value,code:document.getElementById('code').value})}),d=await r.json();document.getElementById('saveResult').innerHTML=d.ok?'<span class="ok">✅ Guardado</span> id <span style="color:var(--accent-light)">'+d.id+'</span>':'✕ '+d.error;st(d.ok?'✅ Guardado exitoso':'✕ Error')}catch(e){st('✕ '+e.message)}}
async function health(){st('❤️ Ejecutando...');try{const r=await fetch('/api/health'),d=await r.json();document.getElementById('healthResult').textContent=d.ok?d.output:'✕ '+d.error;st(d.ok?'✅ Health check completado':'✕ Error')}catch(e){st('✕ '+e.message)}}
</script>
</body></html>"""

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] in ("--http", "--streamable-http"):
        port = int(sys.argv[2]) if len(sys.argv) > 2 else 8001
        host = "127.0.0.1"
        if "--host" in sys.argv:
            idx = sys.argv.index("--host")
            if idx + 1 < len(sys.argv):
                host = sys.argv[idx + 1]
        import uvicorn
        from starlette.routing import Route
        from starlette.responses import JSONResponse
        logger.info("🔌 Iniciando Hipocampo MCP Server (Streamable HTTP) en %s:%d", host, port)
        mcp.settings.port = port
        mcp.settings.host = host
        mcp.settings.transport_security.enable_dns_rebinding_protection = False

        async def demo_page(request):
            return HTMLResponse(DEMO_HTML)

        async def api_search(request):
            q = request.query_params.get("q", "")
            if not q:
                return JSONResponse({"ok": False, "error": "query param 'q' required"})
            try:
                import time, subprocess
                t0 = time.time()
                r = subprocess.run([PYTHON_BIN, SEARCH_SCRIPT, q], capture_output=True, text=True, timeout=15)
                return JSONResponse({"ok": True, "results": r.stdout, "latency_ms": int((time.time() - t0) * 1000)})
            except Exception as e:
                return JSONResponse({"ok": False, "error": str(e)})

        async def api_save(request):
            try:
                body = await request.json()
                content = body.get("content", "")
                if not content:
                    return JSONResponse({"ok": False, "error": "content required"})
                import json as j
                from datetime import date as d
                embedding = _generar_embedding(content)
                metadatos = {"type": body.get("type", "event"), "code": body.get("code", ""), "categories": body.get("categories", []), "date": str(d.today()), "source": "web_demo"}
                sid = body.get("session_id", "")
                if sid:
                    metadatos["session_id"] = sid
                conn = _conn()
                cur = conn.cursor()
                cur.execute("INSERT INTO memoria_vectorial (contenido, metadatos, embedding) VALUES (%s, %s, %s::vector(1024)) RETURNING id", (content, j.dumps(metadatos), embedding))
                row_id = cur.fetchone()[0]
                conn.commit()
                cur.close()
                conn.close()
                return JSONResponse({"ok": True, "id": row_id})
            except Exception as e:
                return JSONResponse({"ok": False, "error": str(e)})

        async def api_health(request):
            try:
                r = subprocess.run([PYTHON_BIN, HEALTH_SCRIPT], capture_output=True, text=True, timeout=15)
                return JSONResponse({"ok": True, "output": r.stdout})
            except Exception as e:
                return JSONResponse({"ok": False, "error": str(e)})

        starlette_app = mcp.streamable_http_app()
        starlette_app.router.routes.insert(0, Route("/", endpoint=demo_page, methods=["GET"]))
        starlette_app.router.routes.insert(0, Route("/api/search", endpoint=api_search, methods=["GET"]))
        starlette_app.router.routes.insert(0, Route("/api/save", endpoint=api_save, methods=["POST"]))
        starlette_app.router.routes.insert(0, Route("/api/health", endpoint=api_health, methods=["GET"]))
        config = uvicorn.Config(starlette_app, host=host, port=port, log_level=mcp.settings.log_level.lower())
        uvicorn.Server(config).run()
    elif len(sys.argv) > 1 and sys.argv[1] == "--sse":
        logger.warning("⚠️  --sse está deprecado desde spec MCP 2025-03-26. Usa --http en su lugar.")
        port = int(sys.argv[2]) if len(sys.argv) > 2 else 8001
        logger.info("🔌 Iniciando Hipocampo MCP Server (SSE) en puerto %d", port)
        mcp.settings.port = port
        mcp.run(transport="sse")
    else:
        logger.info("🔌 Iniciando Hipocampo MCP Server (stdio)")
        mcp.run()
