"""Capa de fuente (2026-10-17): procedencia (autor) + huella de lectura + madurez.

Unitarios sin BD + integración contra hipocampo_db real (deja la BD limpia).
Los de integración corren EXPLÍCITO (política pytest.ini):
    pytest -m integration tests/test_capa_fuente.py -v
"""

import asyncio
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone

import pytest

REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER_DIR = os.path.join(REPO_DIR, "scripts")

skip_no_db = pytest.mark.skipif("CI" in os.environ, reason="DB no disponible en CI")


@pytest.fixture(scope="module")
def hs():
    sys.path.insert(0, SERVER_DIR)
    sys.path.insert(0, REPO_DIR)
    import hipocampo_search as mod

    yield mod
    sys.path.pop(0)
    sys.path.pop(0)


def _r_mv(**kw):
    """Resultado MV mínimo que formatear_resultados puede procesar."""
    base = {
        "id": "v1",
        "contenido": "cuerpo del recuerdo ZZTEST capa fuente",
        "metadatos": {},
        "code_snippet": None,
        "score": 42.0,
        "tabla": "memoria_vectorial",
        "method": "vectorial",
        "source": "memoria_vectorial",
    }
    base.update(kw)
    return base


# ─── Unitarios (sin BD) ──────────────────────────────────────────────────────


def test_linea_sin_procedencia(hs):
    linea = hs._linea_fuente(_r_mv())
    assert "🔖 fuente:" in linea
    assert "sin procedencia registrada (pre-capa)" in linea


def test_linea_agente_reencontrar(hs):
    ahora = datetime.now(timezone.utc)
    r = _r_mv(
        metadatos={"autor": "agente", "date": "2026-10-17", "nivel": "episodica"},
        acc_total=2,
        acc_ultima=ahora - timedelta(seconds=40),
    )
    linea = hs._linea_fuente(r)
    assert "lo escribí yo (agente) (2026-10-17)" in linea
    assert "ya traído hace 40s (2 lecturas)" in linea
    assert "episodio" in linea


def test_linea_usuario_dictado(hs):
    r = _r_mv(metadatos={"autor": "usuario", "date": "2026-10-16"})
    assert "me lo dictaste tú (usuario)" in hs._linea_fuente(r)


def test_linea_catalogo_consultar(hs):
    ahora = datetime.now(timezone.utc)
    r = _r_mv(
        metadatos={"autor": "catalogo", "date": "2026-09-01", "nivel": "semantica"},
        acc_total=5,
        acc_ultima=ahora - timedelta(hours=3),
    )
    linea = hs._linea_fuente(r)
    assert "catalogado de archivo (catálogo) (2026-09-01)" in linea
    assert "ya traído" not in linea  # 3 h > 30 min: no es reencuentro reciente
    assert "5 lecturas, última hace 3 h" in linea
    assert "consolidado" in linea


def test_linea_automatica_regla(hs):
    r = _r_mv(metadatos={"autor": "agente", "date": "2026-08-01", "nivel": "automatica"})
    assert "regla permanente" in hs._linea_fuente(r)


def test_linea_consolidado_xn(hs):
    r = _r_mv(metadatos={"nivel": "semantica", "consolidated_count": 3})
    assert "consolidado ×3" in hs._linea_fuente(r)


def test_linea_mi_por_extra(hs):
    """memory_items sintetiza metadatos: nivel/autor/fecha viven en extra."""
    r = {
        "id": "vmiabc-1",
        "tabla": "memory_items",
        "metadatos": {"memory_type": "profile", "categoria": "x"},
        "extra": {"autor": "usuario", "date": "2026-10-17", "nivel": "semantica"},
    }
    linea = hs._linea_fuente(r)
    assert "me lo dictaste tú (usuario)" in linea
    assert "consolidado" in linea


def test_frescura_humana(hs):
    ahora = datetime.now(timezone.utc)
    assert hs._frescura_humana(ahora - timedelta(seconds=10)) == "hace 10s"
    assert hs._frescura_humana(ahora - timedelta(seconds=90)) == "hace 1 min"
    assert hs._frescura_humana(ahora - timedelta(minutes=40)) == "hace 40 min"
    assert hs._frescura_humana(ahora - timedelta(hours=5)) == "hace 5 h"
    assert hs._frescura_humana(ahora - timedelta(days=3)) == "hace 3 d"
    assert hs._frescura_humana("basura") == ""
    assert hs._frescura_humana(None) == ""
    # ISO string válido se parsea (string → datetime → edad no vacía)
    iso = (ahora - timedelta(hours=2)).isoformat()
    assert hs._frescura_humana(iso) == "hace 2 h"


def test_canonico_ids(hs):
    # MV: prefijos alias → misma fila física bajo v<N>
    assert hs._memory_id_canonico({"tabla": "memoria_vectorial", "id": "v123"}) == "v123"
    assert hs._memory_id_canonico({"tabla": "memoria_vectorial", "id": "t123"}) == "v123"
    assert hs._memory_id_canonico({"tabla": "memoria_vectorial", "id": "tv123"}) == "v123"
    assert hs._memory_id_canonico({"tabla": "memoria_vectorial", "id": "l123"}) == "v123"
    # MI: prefijos alias → vmi<uid>
    assert hs._memory_id_canonico({"tabla": "memory_items", "id": "vmiabc-1"}) == "vmiabc-1"
    assert hs._memory_id_canonico({"tabla": "memory_items", "id": "mabc-1"}) == "vmiabc-1"
    assert hs._memory_id_canonico({"tabla": "memory_items", "id": "tmabc"}) == "vmiabc"
    assert hs._memory_id_canonico({"tabla": "memory_items", "id": "mtabc"}) == "vmiabc"
    # desconocido → tal cual; vacío → ""
    assert hs._memory_id_canonico({"tabla": "?", "id": "x1"}) == "x1"
    assert hs._memory_id_canonico({"tabla": "memoria_vectorial", "id": ""}) == ""
    assert hs._memory_id_canonico({"tabla": "memory_items", "id": ""}) == ""


def test_formatear_incluye_capa_fuente(hs):
    r = _r_mv(metadatos={"autor": "agente", "date": "2026-10-17"})
    out = hs.formatear_resultados([r], "zztest consulta")
    assert "🔖 fuente:" in out
    assert "lo escribí yo (agente)" in out


# ─── Integración (BD real, deja limpia) ─────────────────────────────────────


@pytest.mark.integration
@skip_no_db
def test_huella_roundtrip(hs):
    """Recordar→anotar→alias-invisible→repetir→limpiar, con query_hash único."""
    import hashlib

    from hipocampo.db import get_conn

    qruta = f"ZZTEST capa fuente {uuid.uuid4()}"
    qh = hashlib.sha256(qruta.encode()).hexdigest()[:12]

    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("SELECT id FROM memoria_vectorial ORDER BY id DESC LIMIT 1")
        fila = cur.fetchone()
        vid = int(fila[0]) if fila else None
        assert vid, "BD sin memorias MV para probar la huella"
        cur.execute("SELECT id FROM memory_items ORDER BY created_at DESC LIMIT 1")
        fila_mi = cur.fetchone()
        _mime = fila_mi[0] if fila_mi else None
        MIME = f"vmi{_mime}" if _mime else None

        canon_id = f"v{vid}"
        ids_limpieza = [canon_id] + ([MIME] if MIME else [])
        cur.execute(
            "DELETE FROM memory_access WHERE memory_id = ANY(%s) AND query_hash = %s",
            (ids_limpieza, qh),
        )
        conn.commit()

        # Escrituras por ALIAS deben caer en el namespace canónico de la fila:
        # t{N} (trigger MV) y m{uid} (léxico MI)
        escritos = [_r_mv(id=f"t{vid}")]
        if MIME:
            escritos.append(
                {
                    "id": f"m{_mime}",
                    "contenido": "c",
                    "metadatos": {},
                    "code_snippet": None,
                    "score": 42.0,
                    "tabla": "memory_items",
                    "method": "lexico_expansivo",
                    "source": "memory_items",
                }
            )
        hs._record_access_batch(cur, escritos, qruta)
        conn.commit()

        # Lectura anotada por id canónico y por alias — ambos ven la misma huella
        res = [_r_mv(id=canon_id), _r_mv(id=f"l{vid}")]
        if MIME:
            res.append(
                {
                    "id": MIME,
                    "contenido": "c",
                    "metadatos": {},
                    "code_snippet": None,
                    "score": 42.0,
                    "tabla": "memory_items",
                    "method": "vectorial",
                    "source": "memory_items",
                }
            )
        hs._anotar_accesos(cur, res)
        acc = {r["id"]: (r.get("acc_total"), r.get("acc_ultima")) for r in res}
        assert acc[canon_id][0] >= 1 and acc[canon_id][1] is not None
        assert acc[f"l{vid}"][0] == acc[canon_id][0]  # alias comparte huella
        if MIME:
            assert acc[MIME][0] >= 1
        assert acc.get(f"t{vid}") is None  # sin t-namespace: canónico absorbó

        # Segunda lectura suma y la anotación la ve como lectura previa
        hs._record_access_batch(cur, [_r_mv(id=canon_id)], qruta)
        conn.commit()
        res2 = [_r_mv(id=canon_id)]
        hs._anotar_accesos(cur, res2)
        assert res2[0]["acc_total"] == acc[canon_id][0] + 1
    finally:
        try:
            cur.execute(
                "DELETE FROM memory_access WHERE source = 'search_bire' AND query_hash = %s",
                (qh,),
            )
            conn.commit()
        except Exception:
            conn.rollback()
        cur.close()
        conn.close()


@pytest.mark.integration
@skip_no_db
def test_save_autor_param():
    """save_hipocampo rechaza autor inválido y sella metadatos.autor (default agente)."""
    import hipocampo_mcp_server as server
    from hipocampo.db import get_conn

    out = asyncio.run(server.save_hipocampo(content="ZZTEST capa fuente", autor="pepe", force=True))
    assert "Autor inválido" in out

    content = f"ZZTEST capa de fuente — sello de autor {uuid.uuid4()}"
    out2 = asyncio.run(server.save_hipocampo(content=content, code="zztest_fuente", force=True))
    assert out2.startswith("✅")
    import re

    rid = int(re.search(r"id=(\d+)", out2).group(1))
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("SELECT metadatos->>'autor' FROM memoria_vectorial WHERE id = %s", (rid,))
        assert cur.fetchone()[0] == "agente"
    finally:
        try:
            cur.execute(
                "DELETE FROM memoria_vectorial WHERE id = %s AND metadatos->>'code' = 'zztest_fuente'",
                (rid,),
            )
            conn.commit()
        except Exception:
            conn.rollback()
        cur.close()
        conn.close()
