#!/usr/bin/env python3
"""hipocampo_jcache.py — Cache persistente de juicios (pieza 4).

Guarda el resultado de un juicio externo (payload → resultado JSONB) en la
tabla ``judgment_cache`` para no re-consultar las APIs cuando el mismo texto
se vuelve a juzgar (reintentos, re-saves, juez de cambios corrido dos veces,
scans repetidos). TTL: 30 días.

Contrato de seguridad:
    - Nunca rompe al llamador: cualquier fallo (sin psycopg2, sin BD, tabla
      ausente) ⇒ ``enabled()`` False / ``get`` None, y el flujo normal sigue.
    - La clave es el sha256 del payload YA scrubbed (nunca guarda texto crudo).
    - El resultado guardado son solo etiquetas/números, nunca el texto.
    - Desactivable con ``HIPOCAMPO_JCACHE=0``.

Uso típico (dentro de un cliente HTTP de juicio, tras el scrub y antes del
POST)::

    if _jcache is not None:
        cached = _jcache.get("typesafe", payload)
        if cached is not None:
            return cached["answers"]
    ...
    if _jcache is not None:
        _jcache.put("typesafe", payload, {"answers": respuestas})
"""

from __future__ import annotations

import hashlib
import json
import logging
import os

logger = logging.getLogger("hipocampo_jcache")

__all__ = ["enabled", "get", "put"]

_TTL_DIAS = 30
_tabla_verificada = False


def _off(valor) -> bool:
    return str(valor).strip().lower() in {"0", "false", "no", "off", "disabled"}


def _get_conn():
    """Devuelve ``hipocampo.db.get_conn`` o None (best-effort).

    Primer intento: import normal (servicio MCP). Fallback: agrega
    ``~/.hipocampo/repo`` al sys.path (interprete suelto, ej. juez_cambios).
    """
    try:
        from hipocampo.db import get_conn

        return get_conn
    except Exception:
        pass
    try:
        import sys
        from pathlib import Path

        repo = str(Path.home() / ".hipocampo" / "repo")
        if repo not in sys.path:
            sys.path.insert(0, repo)
        from hipocampo.db import get_conn

        return get_conn
    except Exception:
        return None


def enabled() -> bool:
    """True si el cache está activo y hay acceso a la BD."""
    if _off(os.environ.get("HIPOCAMPO_JCACHE", "1")):
        return False
    return _get_conn() is not None


def _clave(kind: str, payload: dict) -> str:
    canon = json.dumps({"k": kind, "p": payload}, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def _asegurar_tabla(cur) -> None:
    """CREATE TABLE IF NOT EXISTS (una vez por proceso; para entornos nuevos)."""
    if _tabla_verificada:
        return
    cur.execute(
        """CREATE TABLE IF NOT EXISTS judgment_cache (
               cache_key  TEXT PRIMARY KEY,
               kind       TEXT NOT NULL,
               resultado  JSONB NOT NULL,
               created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
               hits       INTEGER NOT NULL DEFAULT 0
           )"""
    )
    cur.execute("CREATE INDEX IF NOT EXISTS idx_judgment_cache_created ON judgment_cache (created_at DESC)")


def get(kind: str, payload: dict):
    """Devuelve el resultado cacheado (dict) o None. Nunca lanza."""
    if _off(os.environ.get("HIPOCAMPO_JCACHE", "1")):
        return None
    conn_fn = _get_conn()
    if conn_fn is None:
        return None
    conn = None
    cur = None
    try:
        key = _clave(kind, payload)
        conn = conn_fn()
        cur = conn.cursor()
        cur.execute(
            "SELECT resultado FROM judgment_cache "
            "WHERE cache_key = %s AND created_at > now() - make_interval(days => %s)",
            (key, _TTL_DIAS),
        )
        row = cur.fetchone()
        if row is None:
            return None
        cur.execute("UPDATE judgment_cache SET hits = hits + 1 WHERE cache_key = %s", (key,))
        conn.commit()
        resultado = row[0]
        if isinstance(resultado, str):
            resultado = json.loads(resultado)
        if isinstance(resultado, dict):
            logger.info("jcache: HIT (%s)", kind)
            return resultado
        return None
    except Exception:
        return None
    finally:
        try:
            if cur is not None:
                cur.close()
            if conn is not None:
                conn.close()
        except Exception:
            pass


def put(kind: str, payload: dict, resultado) -> None:
    """Guarda un resultado (upsert, best-effort). Nunca lanza."""
    global _tabla_verificada
    if resultado is None or _off(os.environ.get("HIPOCAMPO_JCACHE", "1")):
        return
    conn_fn = _get_conn()
    if conn_fn is None:
        return
    conn = None
    cur = None
    try:
        key = _clave(kind, payload)
        conn = conn_fn()
        cur = conn.cursor()
        _asegurar_tabla(cur)
        cur.execute(
            """INSERT INTO judgment_cache (cache_key, kind, resultado)
               VALUES (%s, %s, %s::jsonb)
               ON CONFLICT (cache_key)
               DO UPDATE SET resultado = EXCLUDED.resultado, created_at = now()""",
            (key, kind, json.dumps(resultado, ensure_ascii=False, default=str)),
        )
        conn.commit()
        _tabla_verificada = True
    except Exception:
        try:
            if conn is not None:
                conn.rollback()
        except Exception:
            pass
    finally:
        try:
            if cur is not None:
                cur.close()
            if conn is not None:
                conn.close()
        except Exception:
            pass
