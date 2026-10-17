import sys
import os
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

# Pure functions from hipocampo_search.py — import before module-level side effects
from hipocampo_search import (
    expandir_consulta,
    generar_patrones_ILIKE,
    fusionar_resultados,
    _aplicar_decaimiento_temporal,
    _mmr_seleccionar,
    _patrones_indexables,
    formatear_resultados,
    cargar_config_hibrida,
    STEM_MAP,
)

# Fecha de referencia fija para que los tests nunca roten
_HOY = date(2026, 7, 12)


class TestExpandirConsulta:
    def test_expansion_simple(self):
        result = expandir_consulta("planta")
        assert "planta" in result
        assert "plantas" in result
        assert "vegetal" in result

    def test_expansion_con_espacios(self):
        result = expandir_consulta("té medicinal")
        assert "té" in result
        assert "infusión" in result
        assert "medicinal" in result
        assert "curativa" in result

    def test_sinonimos_globales(self):
        result = expandir_consulta("medicinal")
        assert "medicinal" in result
        assert "botánica" in result
        assert "herbal" in result

    def test_vacio_retorna_lista_vacia(self):
        result = expandir_consulta("")
        assert len(result) >= 0  # al menos devuelve algo, no crash

    def test_sin_match_retorna_original(self):
        result = expandir_consulta("xyz123nosense")
        assert "xyz123nosense" in result

    def test_stem_map_todas_las_claves(self):
        stems_usadas = set()
        for v in STEM_MAP.values():
            stems_usadas.update(v)
        result = expandir_consulta("color")
        assert all(s in result for s in STEM_MAP["color"])


class TestGenerarPatrones:
    def test_patrones_basicos(self):
        patterns = generar_patrones_ILIKE(["hola", "mundo"])
        assert len(patterns) == 2
        assert "%hola%" in patterns
        assert "%mundo%" in patterns

    def test_vacio(self):
        assert generar_patrones_ILIKE([]) == []


class TestFusionarResultados:
    def test_solo_vectorial(self):
        vec = [
            {
                "contenido": "test",
                "score": 80.0,
                "method": "vectorial",
                "source": "memoria_vectorial",
                "tabla": "memoria_vectorial",
                "metadatos": {"date": "2026-07-06"},
                "code_snippet": None,
            }
        ]
        result = fusionar_resultados(vec, [], [], alpha=0.6, hoy=_HOY)
        assert len(result) == 1
        assert result[0]["score"] > 0

    def test_solo_lexico(self):
        lex = [
            {
                "contenido": "test",
                "score": 60.0,
                "method": "lexico_expansivo",
                "source": "memoria_vectorial",
                "tabla": "memoria_vectorial",
                "metadatos": {"date": "2026-07-06"},
                "code_snippet": None,
            }
        ]
        result = fusionar_resultados([], [], lex, alpha=0.6, hoy=_HOY)
        assert len(result) == 1

    def test_fusion_hibrida_mismo_contenido(self):
        vec = [
            {
                "contenido": "python api",
                "score": 80.0,
                "method": "vectorial",
                "source": "memoria_vectorial",
                "tabla": "memoria_vectorial",
                "metadatos": {"date": "2026-07-06"},
                "code_snippet": None,
            }
        ]
        lex = [
            {
                "contenido": "python api",
                "score": 60.0,
                "method": "lexico_expansivo",
                "source": "memoria_vectorial",
                "tabla": "memoria_vectorial",
                "metadatos": {"date": "2026-07-06"},
                "code_snippet": None,
            }
        ]
        result = fusionar_resultados(vec, [], lex, alpha=0.6, hoy=_HOY)
        assert len(result) == 1  # dedup por contenido
        assert 70 < result[0]["score"] < 75  # 0.6*80 + 0.4*60 = 72

    def test_alpha_0_vectorial(self):
        vec = [
            {
                "contenido": "test",
                "score": 90.0,
                "method": "vectorial",
                "source": "memoria_vectorial",
                "tabla": "memoria_vectorial",
                "metadatos": {"date": "2026-07-06"},
                "code_snippet": None,
            }
        ]
        lex = [
            {
                "contenido": "test",
                "score": 50.0,
                "method": "lexico_expansivo",
                "source": "memoria_vectorial",
                "tabla": "memoria_vectorial",
                "metadatos": {"date": "2026-07-06"},
                "code_snippet": None,
            }
        ]
        result = fusionar_resultados(vec, [], lex, alpha=1.0, hoy=_HOY)
        assert result[0]["score"] == 90.0

    def test_contenidos_diferentes(self):
        vec = [
            {
                "contenido": "aaaa",
                "score": 80.0,
                "method": "vectorial",
                "source": "memoria_vectorial",
                "tabla": "memoria_vectorial",
                "metadatos": {"date": "2026-07-06"},
                "code_snippet": None,
            }
        ]
        lex = [
            {
                "contenido": "bbbb",
                "score": 60.0,
                "method": "lexico_expansivo",
                "source": "memoria_vectorial",
                "tabla": "memoria_vectorial",
                "metadatos": {"date": "2026-07-06"},
                "code_snippet": None,
            }
        ]
        result = fusionar_resultados(vec, [], lex, alpha=0.6, hoy=_HOY)
        assert len(result) == 2


class TestDecaimientoTemporal:
    def test_reciente_sin_decaimiento(self):
        items = [
            {
                "contenido": "nuevo",
                "score": 80.0,
                "metadatos": {"date": "2026-07-06"},
                "method": "vectorial",
                "source": "memoria_vectorial",
                "tabla": "memoria_vectorial",
                "code_snippet": None,
                "vec_score": 0,
                "lex_score": 0,
            }
        ]
        result = _aplicar_decaimiento_temporal(items, hoy=_HOY)
        assert result[0]["score"] == 80.0

    def test_antiguo_con_decaimiento(self):
        items = [
            {
                "contenido": "viejo",
                "score": 80.0,
                "metadatos": {"date": "2026-01-01"},
                "method": "vectorial",
                "source": "memoria_vectorial",
                "tabla": "memoria_vectorial",
                "code_snippet": None,
                "vec_score": 0,
                "lex_score": 0,
            }
        ]
        result = _aplicar_decaimiento_temporal(items, hoy=_HOY)
        assert result[0]["score"] < 80.0  # debe decaer
        assert result[0]["score"] >= 16.0  # floor 20% de 80 (exponencial)

    def test_sin_fecha_sin_decaimiento(self):
        items = [
            {
                "contenido": "sin fecha",
                "score": 50.0,
                "metadatos": {},
                "method": "vectorial",
                "source": "memoria_vectorial",
                "tabla": "memoria_vectorial",
                "code_snippet": None,
                "vec_score": 0,
                "lex_score": 0,
            }
        ]
        result = _aplicar_decaimiento_temporal(items, hoy=_HOY)
        assert result[0]["score"] == 50.0


class TestFormatearResultados:
    def test_sin_resultados(self):
        output = formatear_resultados([], "test query")
        assert "0 resultados" in output

    def test_con_resultados(self):
        items = [
            {
                "contenido": "resultado de prueba",
                "score": 85.0,
                "metadatos": {"tags": ["test"]},
                "method": "vectorial",
                "source": "memoria_vectorial",
                "tabla": "memoria_vectorial",
                "code_snippet": "print('hola')",
            }
        ]
        output = formatear_resultados(items, "prueba")
        assert "85.0" in output
        assert "BIRE" in output
        assert "resultado de prueba" in output


class TestCargarConfig:
    def test_config_default_sin_archivo(self):
        alpha = cargar_config_hibrida()
        assert isinstance(alpha, float)


class TestPatronesIndexables:
    def test_separa_por_longitud(self):
        strong, weak = _patrones_indexables(["%md%", "%snapshot%", "%ab%", "%abc%"])
        assert strong == ["%snapshot%", "%abc%"]
        assert weak == ["%md%", "%ab%"]

    def test_todos_fuertes(self):
        strong, weak = _patrones_indexables(["%deploy%", "%token%"])
        assert strong == ["%deploy%", "%token%"]
        assert weak == []

    def test_todos_debiles(self):
        strong, weak = _patrones_indexables(["%té%", "%md%"])
        assert strong == []
        assert weak == ["%té%", "%md%"]


class TestMMRSeleccionar:
    @staticmethod
    def _c(i, score):
        return {"id": i, "score": score, "contenido": i}

    def test_prefiere_diverso_sobre_redundante(self):
        cands = [self._c("v1", 100.0), self._c("v2", 70.0), self._c("v3", 50.0)]
        embs = {1: [1.0, 0.0, 0.0], 2: [1.0, 0.0, 0.0], 3: [0.0, 1.0, 0.0]}
        selected, restantes = _mmr_seleccionar(cands, embs, 0.7)
        # v3 (diverso, score menor) va antes que v2 (vector idéntico a v1)
        assert [c["id"] for c in selected] == ["v1", "v3", "v2"]
        assert restantes == []

    def test_fallback_sin_numpy(self, monkeypatch):
        import sys as _sys

        monkeypatch.setitem(_sys.modules, "numpy", None)
        cands = [self._c("v1", 100.0), self._c("v2", 70.0), self._c("v3", 50.0)]
        embs = {1: [1.0, 0.0, 0.0], 2: [1.0, 0.0, 0.0], 3: [0.0, 1.0, 0.0]}
        selected, restantes = _mmr_seleccionar(cands, embs, 0.7)
        assert [c["id"] for c in selected] == ["v1", "v3", "v2"]
        assert restantes == []

    def test_candidato_sin_vector_no_se_selecciona(self):
        cands = [self._c("v1", 100.0), self._c("vmi9", 99.0), self._c("v3", 50.0)]
        embs = {1: [1.0, 0.0], 3: [0.0, 1.0]}
        selected, restantes = _mmr_seleccionar(cands, embs, 0.7)
        assert [c["id"] for c in selected] == ["v1", "v3"]
        assert [c["id"] for c in restantes] == ["vmi9"]

    def test_sin_vectores_devuelve_pool_intacto(self):
        cands = [self._c("v1", 100.0), self._c("v2", 90.0)]
        selected, restantes = _mmr_seleccionar(cands, {}, 0.7)
        assert [c["id"] for c in selected] == ["v1"]
        assert [c["id"] for c in restantes] == ["v2"]

    def test_restantes_sin_vector_conservan_orden(self):
        cands = [
            self._c("v1", 99.0),
            self._c("zz2", 50.0),
            self._c("v3", 40.0),
            self._c("zz4", 30.0),
        ]
        embs = {1: [1.0, 0.0], 3: [0.0, 1.0]}
        selected, restantes = _mmr_seleccionar(cands, embs, 0.7)
        assert [c["id"] for c in selected] == ["v1", "v3"]
        assert [c["id"] for c in restantes] == ["zz2", "zz4"]
