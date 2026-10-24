"""Tests del ciclo glinfático (pasada nocturna ligera).

Unitario (sin BD): el gate de actividad debe omitir la pasada cuando no hay
actividad. Integración (BD viva): las métricas de aclaramiento deben devolver
las cuatro claves con valores numéricos.

    pytest tests/test_glymphatic.py -v
    pytest tests/test_glymphatic.py -m integration -v
"""

import json
import os
import sys

import pytest

REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS_DIR = os.path.join(REPO_DIR, "scripts")
sys.path.insert(0, SCRIPTS_DIR)
sys.path.insert(0, REPO_DIR)

import hipocampo_glymphatic as gly  # noqa: E402


class _FakeCur:
    def execute(self, *args, **kwargs):
        return None

    def fetchone(self):
        return (0,)

    def close(self):
        return None


class _FakeConn:
    def cursor(self):
        return _FakeCur()

    def close(self):
        return None


def test_gate_dormido_omite_pasada(monkeypatch, tmp_path):
    """Sin actividad y sin --force: no mide, no aplica y deja estado 'dormido'."""
    monkeypatch.setattr(gly, "get_conn", lambda: _FakeConn())
    monkeypatch.setattr(
        gly,
        "actividad",
        lambda cur, horas: {"consultas": 0, "accesos": 0, "memorias_nuevas": 0, "total": 0},
    )
    monkeypatch.setattr(gly, "STATE_DIR", str(tmp_path))
    monkeypatch.setattr(gly, "STATE_PATH", str(tmp_path / "glymphatic_last.json"))
    monkeypatch.setattr(sys, "argv", ["hipocampo_glymphatic.py", "--json"])

    assert gly.main() == 0

    estado = json.loads((tmp_path / "glymphatic_last.json").read_text())
    assert estado["gate"] == "dormido"
    assert estado["acciones"] == {}
    assert estado["metricas"] == {}


@pytest.mark.integration
def test_metricas_clearance_bd_viva():
    """Las 4 métricas deben existir y ser coherentes sobre la BD real."""
    from hipocampo.db import get_conn, load_config

    load_config()
    conn = get_conn()
    cur = conn.cursor()
    try:
        m = gly.metricas(cur)
    finally:
        cur.close()
        conn.close()

    for clave in (
        "duplicados_exactos",
        "duplicados_pct",
        "episodicos_frios_90d",
        "enlaces_huerfanos",
        "contradicciones_fuertes",
        "judgment_cache_expirada",
        "revisar",
    ):
        assert clave in m, f"falta {clave}"

    assert m["duplicados_exactos"] >= 0
    assert 0 <= m["duplicados_pct"] <= 100
    assert m["enlaces_huerfanos"] >= 0
    assert isinstance(m["revisar"], bool)
