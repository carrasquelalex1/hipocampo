"""Integración: firma embedding_src_md5 + barredor de embeddings.

Requiere BD viva (los embeddings se inyectan con stubs, sin Ollama):
    pytest tests/test_embed_sweeper.py -m integration -v
"""

import os
import sys

import pytest

pytestmark = pytest.mark.integration

REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER_DIR = os.path.join(REPO_DIR, "scripts")

skip_no_db = pytest.mark.skipif("CI" in os.environ, reason="DB no disponible en CI")


def _modules():
    sys.path.insert(0, SERVER_DIR)
    sys.path.insert(0, REPO_DIR)
    try:
        import hipocampo_embed_sweeper as sweeper
        import hipocampo_mcp_server as server
        from hipocampo.db import contenido_firma

        return sweeper, server, contenido_firma
    finally:
        sys.path.pop(0)
        sys.path.pop(0)


def _q(sql, args=None):
    from hipocampo.db import get_conn

    conn = get_conn()
    cur = conn.cursor()
    cur.execute(sql, args)
    out = cur.fetchall() if cur.description is not None else None
    conn.commit()
    cur.close()
    conn.close()
    return out


def _vector_stub(valor):
    return [valor] * 1024


@pytest.fixture(autouse=True)
def _limpiar_residuos_de_corridas_anteriores():
    """Borra restos ZZTEST de esta suite (corre contra la BD real, sin residuos)."""
    _q("DELETE FROM memoria_vectorial WHERE contenido LIKE 'ZZTEST sweep%' OR contenido LIKE 'ZZTEST firma%'")


@skip_no_db
def test_finalize_update_escribe_firma(monkeypatch):
    """Al completar un update en background se guarda embedding + firma."""
    sweeper, server, contenido_firma = _modules()

    contenido = "ZZTEST firma update 20261017"
    (rid,) = _q(
        "INSERT INTO memoria_vectorial (contenido, metadatos) VALUES (%s, '{}'::jsonb) RETURNING id",
        (contenido,),
    )[0]
    try:
        monkeypatch.setattr(server, "get_embedding_with_retries", lambda text, timeout_s=None: _vector_stub(0.01))
        server._finalize_update_bg(rid, contenido)

        emb_ok, firma = _q(
            "SELECT embedding IS NOT NULL, metadatos->>'embedding_src_md5' FROM memoria_vectorial WHERE id=%s",
            (rid,),
        )[0]
        assert emb_ok, "el embedding no se escribió"
        assert firma == contenido_firma(contenido), "la firma no coincide con el contenido"
    finally:
        _q("DELETE FROM memoria_vectorial WHERE id=%s", (rid,))


@skip_no_db
def test_sweeper_repara_solo_los_pendientes_de_sus_ids():
    """Repara NULL y firma desactualizada; no toca filas al día (filtro ids)."""
    sweeper, _, contenido_firma = _modules()

    c_null = "ZZTEST sweep null embedding"
    c_mala = "ZZTEST sweep firma desactualizada"
    c_ok = "ZZTEST sweep al dia"

    ids = []
    (rid_null,) = _q(
        "INSERT INTO memoria_vectorial (contenido, metadatos) VALUES (%s, '{}'::jsonb) RETURNING id",
        (c_null,),
    )[0]
    ids.append(rid_null)
    (rid_mala,) = _q(
        "INSERT INTO memoria_vectorial (contenido, embedding, metadatos) "
        "VALUES (%s, %s::vector(1024), jsonb_build_object('embedding_src_md5', 'firma-vieja')) RETURNING id",
        (c_mala, str(_vector_stub(0.02))),
    )[0]
    ids.append(rid_mala)
    (rid_ok,) = _q(
        "INSERT INTO memoria_vectorial (contenido, embedding, metadatos) "
        "VALUES (%s, %s::vector(1024), jsonb_build_object('embedding_src_md5', %s)) RETURNING id",
        (c_ok, str(_vector_stub(0.03)), contenido_firma(c_ok)),
    )[0]
    ids.append(rid_ok)

    llamadas = []

    def embed_fn(contenido, timeout_s=None):
        llamadas.append(contenido)
        return _vector_stub(0.04)

    try:
        resumen = sweeper.barrer(max_rows=50, pause_s=0, timeout_s=5, ids=ids, embed_fn=embed_fn, log=lambda m: None)
        assert resumen["reparados"] == 2, resumen
        assert resumen["errores"] == 0, resumen

        filas = dict(
            (rid, firma)
            for rid, firma in _q(
                "SELECT id, metadatos->>'embedding_src_md5' FROM memoria_vectorial WHERE id = ANY(%s)",
                (ids,),
            )
        )
        assert filas[rid_null] == contenido_firma(c_null)
        assert filas[rid_mala] == contenido_firma(c_mala)
        assert filas[rid_ok] == contenido_firma(c_ok), "la fila al día no debe re-firmarse"

        # La fila al día no se re-embebió (no aparece en las llamadas al embedder)
        assert c_ok not in llamadas
        assert c_null in llamadas and c_mala in llamadas
    finally:
        _q("DELETE FROM memoria_vectorial WHERE id = ANY(%s)", (ids,))


@skip_no_db
def test_sweeper_salta_si_el_contenido_cambia_durante_el_barrido():
    """Guarda anti-carrera: si el contenido cambia entre SELECT y UPDATE, salta."""
    sweeper, _, contenido_firma = _modules()

    c1 = "ZZTEST sweep carrera v1"
    c2 = "ZZTEST sweep carrera v2"
    (rid,) = _q(
        "INSERT INTO memoria_vectorial (contenido, metadatos) VALUES (%s, '{}'::jsonb) RETURNING id",
        (c1,),
    )[0]

    def embed_fn(contenido, timeout_s=None):
        # Simula un update concurrente: cambia el contenido de la fila ANTES
        # de que el barredor intente escribir su resultado.
        _q("UPDATE memoria_vectorial SET contenido=%s WHERE id=%s", (c2, rid))
        return _vector_stub(0.05)

    try:
        resumen = sweeper.barrer(max_rows=50, pause_s=0, timeout_s=5, ids=[rid], embed_fn=embed_fn, log=lambda m: None)
        assert resumen["saltados"] == 1, resumen
        assert resumen["reparados"] == 0, resumen

        (contenido,) = _q("SELECT contenido FROM memoria_vectorial WHERE id=%s", (rid,))[0]
        assert contenido == c2
    finally:
        _q("DELETE FROM memoria_vectorial WHERE id=%s", (rid,))


@skip_no_db
def test_sweeper_rama_sin_ids_no_rompe_con_limite_cero():
    """La rama sin ids (SQL de producción) funciona con LIMIT 0 (ejercita el SQL completo)."""
    sweeper, _, _ = _modules()
    resumen = sweeper.barrer(
        max_rows=0, pause_s=0, timeout_s=5, embed_fn=lambda c, timeout_s=None: None, log=lambda m: None
    )
    assert resumen["revisados"] == 0, resumen
    assert isinstance(resumen["pendientes"], int)


@skip_no_db
def test_sweeper_respeta_warm_since():
    """Una fila WARM de hipocampo_budget no se re-embebe mientras su firma siga al día."""
    sweeper, _, contenido_firma = _modules()

    c = "ZZTEST sweep warm intacto"
    (rid,) = _q(
        "INSERT INTO memoria_vectorial (contenido, metadatos) "
        "VALUES (%s, jsonb_build_object('warm_since', now()::text, 'embedding_src_md5', %s)) RETURNING id",
        (c, contenido_firma(c)),
    )[0]
    try:
        resumen = sweeper.barrer(
            max_rows=50,
            pause_s=0,
            timeout_s=5,
            ids=[rid],
            embed_fn=lambda x, timeout_s=None: _vector_stub(0.06),
            log=lambda m: None,
        )
        assert resumen["revisados"] == 0, resumen
        assert _q("SELECT embedding IS NULL FROM memoria_vectorial WHERE id=%s", (rid,))[0][0] is True
    finally:
        _q("DELETE FROM memoria_vectorial WHERE id=%s", (rid,))


@skip_no_db
def test_sweeper_repara_warm_si_el_contenido_cambio():
    """WARM + contenido editado → se re-embebe y se limpia warm_since (vuelve a HOT)."""
    sweeper, _, contenido_firma = _modules()

    c_viejo = "ZZTEST sweep warm v1"
    c_nuevo = "ZZTEST sweep warm v2"
    (rid,) = _q(
        "INSERT INTO memoria_vectorial (contenido, metadatos) "
        "VALUES (%s, jsonb_build_object('warm_since', now()::text, 'embedding_src_md5', %s)) RETURNING id",
        (c_viejo, contenido_firma(c_viejo)),
    )[0]
    _q("UPDATE memoria_vectorial SET contenido = %s WHERE id = %s", (c_nuevo, rid))
    try:
        resumen = sweeper.barrer(
            max_rows=50,
            pause_s=0,
            timeout_s=5,
            ids=[rid],
            embed_fn=lambda x, timeout_s=None: _vector_stub(0.07),
            log=lambda m: None,
        )
        assert resumen["reparados"] == 1, resumen
        warm, firma = _q(
            "SELECT metadatos->>'warm_since', metadatos->>'embedding_src_md5' FROM memoria_vectorial WHERE id=%s",
            (rid,),
        )[0]
        assert warm is None, "warm_since debe limpiarse al re-embeberse"
        assert firma == contenido_firma(c_nuevo)
    finally:
        _q("DELETE FROM memoria_vectorial WHERE id=%s", (rid,))


@skip_no_db
def test_sweeper_acepta_tuple_del_failover():
    """El failover puede devolver tuple; el barredor debe coercionar a list (psycopg2 no adapta tuple a vector)."""
    sweeper, _, _ = _modules()

    c = "ZZTEST sweep tupla failover"
    (rid,) = _q(
        "INSERT INTO memoria_vectorial (contenido, metadatos) VALUES (%s, '{}'::jsonb) RETURNING id",
        (c,),
    )[0]
    try:
        resumen = sweeper.barrer(
            max_rows=50,
            pause_s=0,
            timeout_s=5,
            ids=[rid],
            embed_fn=lambda x, timeout_s=None: tuple([0.08] * 1024),
            log=lambda m: None,
        )
        assert resumen["reparados"] == 1, resumen
        assert _q("SELECT embedding IS NOT NULL FROM memoria_vectorial WHERE id=%s", (rid,))[0][0] is True
    finally:
        _q("DELETE FROM memoria_vectorial WHERE id=%s", (rid,))
