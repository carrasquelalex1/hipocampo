import sys
import os
import json
from datetime import timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

# Import pure functions before module-level side effects
from hipocampo_checkpoint import (
    ESCALAS,
    agrupar_por_proyecto,
    generar_resumen,
)


class TestEscalas:
    def test_escalas_tienen_nombre_y_timedelta(self):
        for nombre, delta in ESCALAS:
            assert isinstance(nombre, str)
            if delta is not None:
                assert isinstance(delta, timedelta)


class TestAgruparPorProyecto:
    def test_agrupa_por_proyecto(self):
        entries = [
            ((1, "item1", json.dumps({"proyecto": "alpha"})), False),
            ((2, "item2", json.dumps({"proyecto": "beta"})), False),
            ((3, "item3", json.dumps({"proyecto": "alpha"})), False),
        ]
        grupos = agrupar_por_proyecto(entries)
        assert "alpha" in grupos
        assert "beta" in grupos
        assert len(grupos["alpha"]) == 2
        assert len(grupos["beta"]) == 1

    def test_sin_proyecto_usar_general(self):
        entries = [
            ((1, "item", json.dumps({"tags": ["test"]})), False),
        ]
        grupos = agrupar_por_proyecto(entries)
        assert "general" in grupos

    def test_usar_path_si_no_hay_proyecto(self):
        entries = [
            ((1, "item", json.dumps({"path": "mi_ruta"})), False),
        ]
        grupos = agrupar_por_proyecto(entries)
        assert "mi_ruta" in grupos

    def test_vacio(self):
        assert agrupar_por_proyecto([]) == {}


class TestGenerarResumen:
    def test_resumen_simple(self):
        grupo = [
            ((1, "Este es un contenido de prueba para el resumen", json.dumps({"tags": ["test"]})), False),
        ]
        result = generar_resumen(grupo, max_chars=300)
        assert result is not None
        assert "contenido de prueba" in result["resumen"]
        assert result["total_items"] == 1
        assert "test" in result["tags"]

    def test_resumen_truncado(self):
        grupo = [
            ((1, "A" * 500, json.dumps({"tags": []})), False),
        ]
        result = generar_resumen(grupo, max_chars=100)
        assert len(result["resumen"]) <= 103  # 100 + "..."
        assert "..." in result["resumen"]

    def test_grupo_vacio(self):
        assert generar_resumen([]) is None

    def test_multiples_items(self):
        grupo = [
            ((1, "Primer item", json.dumps({"tags": ["tag1"]})), False),
            ((2, "Segundo item", json.dumps({"tags": ["tag2"]})), False),
            ((3, "Tercer item", json.dumps({"tags": ["tag1", "tag3"]})), False),
        ]
        result = generar_resumen(grupo, max_chars=500)
        assert result["total_items"] == 3
        assert "tag1" in result["tags"]
        assert "tag2" in result["tags"]
        assert "tag3" in result["tags"]
        assert "Primer item" in result["resumen"]

    def test_muestra_solo_primeros_5(self):
        grupo = [((i, f"Item {i}", json.dumps({"tags": []})), False) for i in range(10)]
        result = generar_resumen(grupo, max_chars=1000)
        assert "Item 0" in result["resumen"]
        assert "Item 4" in result["resumen"]
        assert result["total_items"] == 10
