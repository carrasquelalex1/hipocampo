"""Integración: update_hipocampo asíncrono (embedding en background) + meta_patch.

Requiere BD viva y Ollama. Excluido del suite por defecto (marker integration):
    pytest tests/test_update_hipocampo.py -m integration -v
"""

import asyncio
import os
import sys
import time

import pytest

pytestmark = pytest.mark.integration

REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER_DIR = os.path.join(REPO_DIR, "scripts")

skip_no_db = pytest.mark.skipif("CI" in os.environ, reason="DB no disponible en CI")


def _server_module():
    sys.path.insert(0, SERVER_DIR)
    sys.path.insert(0, REPO_DIR)
    try:
        import hipocampo_mcp_server as mod

        return mod
    finally:
        sys.path.pop(0)
        sys.path.pop(0)


def _q(sql, args=None, fetch=True):
    from hipocampo.db import get_conn

    conn = get_conn()
    cur = conn.cursor()
    cur.execute(sql, args)
    out = cur.fetchall() if fetch else None
    conn.commit()
    cur.close()
    conn.close()
    return out


@skip_no_db
def test_update_async_y_meta_patch():
    """update devuelve rápido, aplica meta_patch y embebe en background."""
    mod = _server_module()

    (rid,) = _q(
        "INSERT INTO memoria_vectorial (contenido, metadatos) VALUES (%s, %s) RETURNING id",
        ("ZZTEST update async scratch", '{"zztest": true}'),
    )[0]

    try:
        t0 = time.time()
        msg = asyncio.run(
            mod.update_hipocampo(
                id=rid,
                content="ZZTEST update async scratch v2",
                meta_patch={"md5": "zztest123", "bytes": 30},
            )
        )
        dt = time.time() - t0
        assert msg.startswith("✅"), f"update falló: {msg}"
        assert dt < 5.0, f"update bloqueante: {dt:.1f}s"

        # Prueba dura de asincronía: al volver el update, el embedding AÚN no
        # debe estar regenerado (un update síncrono ya lo habría dejado listo;
        # el embed real de este string tarda ~0.6s y este SELECT, milisegundos).
        (emb_inmediato,) = _q("SELECT embedding IS NOT NULL FROM memoria_vectorial WHERE id=%s", (rid,))[0]
        assert not emb_inmediato, "embedding listo al volver del update: ¿regresión a síncrono?"

        contenido, meta = _q("SELECT contenido, metadatos FROM memoria_vectorial WHERE id=%s", (rid,))[0]
        assert contenido == "ZZTEST update async scratch v2"
        assert meta.get("md5") == "zztest123" and meta.get("bytes") == 30
        assert meta.get("zztest") is True, "meta_patch no debe perder claves existentes"
        assert meta.get("updated_at")

        # El embedding llega en background (daemon thread del proceso de test).
        deadline = time.time() + 120
        emb_ok = False
        while time.time() < deadline:
            (emb_ok,) = _q("SELECT embedding IS NOT NULL FROM memoria_vectorial WHERE id=%s", (rid,))[0]
            if emb_ok:
                break
            time.sleep(3)
        assert emb_ok, "el embedding no se regeneró en background (120s)"
    finally:
        _q("DELETE FROM memoria_vectorial WHERE id=%s", (rid,), fetch=False)


@skip_no_db
def test_update_solo_meta_patch_no_toca_contenido():
    """meta_patch sin content: actualiza metadatos y deja el contenido igual."""
    mod = _server_module()

    (rid,) = _q(
        "INSERT INTO memoria_vectorial (contenido, metadatos) VALUES (%s, %s) RETURNING id",
        ("ZZTEST meta only scratch", '{"zztest2": true}'),
    )[0]
    try:
        msg = asyncio.run(mod.update_hipocampo(id=rid, meta_patch={"sello": "x"}))
        assert msg.startswith("✅"), f"update falló: {msg}"
        contenido, meta = _q("SELECT contenido, metadatos FROM memoria_vectorial WHERE id=%s", (rid,))[0]
        assert contenido == "ZZTEST meta only scratch"
        assert meta.get("sello") == "x"
    finally:
        _q("DELETE FROM memoria_vectorial WHERE id=%s", (rid,), fetch=False)
