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
SEARCH_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hipocampo_search.py")
DB_HOST = os.getenv("DB_HOST", "/var/run/postgresql")
DB_USER = os.getenv("DB_USER", "alex")
DB_NAME = os.getenv("DB_NAME", "hipocampo_db")
ENV_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")

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
    try:
        result = subprocess.run(
            [PYTHON_BIN, SEARCH_SCRIPT, query],
            capture_output=True,
            text=True,
            check=True,
        )
        logger.info("Hipocampo search OK query=%r", query)
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


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--sse":
        port = int(sys.argv[2]) if len(sys.argv) > 2 else 8001
        logger.info("🔌 Iniciando Hipocampo MCP Server (SSE) en puerto %d", port)
        mcp.settings.port = port
        mcp.run(transport="sse")
    else:
        logger.info("🔌 Iniciando Hipocampo MCP Server (stdio)")
        mcp.run()
