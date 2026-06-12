#!/usr/bin/env python3
"""Hipocampo MCP Server v2 — MCP Native con FastMCP

Expone el motor de búsqueda BIRE v3.6 como herramientas (tools) del
Model Context Protocol. Compatible con Claude Desktop, OpenCode y cualquier
cliente MCP.

Transportes soportados:
  stdio (por defecto)   → Para clientes locales (Claude Desktop, etc.)
  sse (--sse)           → Para clientes remotos por HTTP

Ejemplos:
    python hipocampo_mcp_server.py
    python hipocampo_mcp_server.py --sse 8001
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
ENV_PATH = os.path.join(BASE_DIR, "scripts", ".env")

# ─── INICIALIZACIÓN MCP ─────────────────────────────────────────────────────
mcp = FastMCP("hipocampo")


@mcp.tool()
def search_hipocampo(query: str) -> str:
    """
    Busca en el Hipocampo (memoria dual con SSC / BIRE v3.6).

    Realiza búsqueda semántica + léxica híbrida en las bases de datos de
    memoria del usuario, incluyendo memoria técnica (*memoria_vectorial*) y
    de perfil (*memory_items*).

    Args:
        query: Texto de búsqueda. Ejemplos:
               "proyecto contable", "perro", "planta medicinal",
               "API REST en Python", "gusta del té".

    Returns:
        Resultados formateados del BIRE como texto plano.
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


@mcp.tool()
def quick_hipocampo_search(query: str) -> str:
    """
    Búsqueda rápida en el Hipocampo (alias corto de search_hipocampo).

    Útil cuando el cliente MCP prefiera nombres de herramienta más cortos.
    """
    return search_hipocampo(query)


@mcp.resource("hipocampo://info")
def hipocampo_info() -> str:
    """Información general sobre el sistema Hipocampo."""
    return (
        "🧠 Hipocampo Protocol v3.6\n"
        "Sistema de memoria dual con SSC (Sparse-Semantic Clusters)\n"
        "· Búsqueda vectorial 768d (nvidia/nv-embedqa-e5-v5)\n"
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
    return resp.data[0].embedding[:768]


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
               VALUES (%s, %s, %s::vector) RETURNING id""",
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
               VALUES (%s, %s, 'profile', %s, %s::vector, NOW(), NOW())""",
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


@mcp.tool()
def hipocampo_tune() -> str:
    """
    Ajusta automáticamente los thresholds y pesos del SSC
    basado en las métricas de rendimiento acumuladas.

    Returns:
        Reporte de ajustes aplicados.
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


@mcp.tool()
def hipocampo_dedup(merge: bool = False) -> str:
    """
    Detecta y opcionalmente fusiona duplicados en las tablas de memoria.

    Args:
        merge: Si es True, fusiona los duplicados encontrados.
               Si es False (default), solo muestra análisis.

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


@mcp.tool()
def hipocampo_checkpoint(dry_run: bool = True) -> str:
    """
    Comprime memorias antiguas usando checkpointing logarítmico.

    Args:
        dry_run: Si es True (default), solo muestra qué se comprimiría.
                 Si es False, ejecuta la compresión.

    Returns:
        Reporte del checkpointing ejecutado.
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


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--sse":
        port = int(sys.argv[2]) if len(sys.argv) > 2 else 8001
        logger.info("🔌 Iniciando Hipocampo MCP Server (SSE) en puerto %d", port)
        mcp.settings.port = port
        mcp.run(transport="sse")
    else:
        logger.info("🔌 Iniciando Hipocampo MCP Server (stdio)")
        mcp.run()
