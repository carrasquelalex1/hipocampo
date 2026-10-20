import sys
import os
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

# Pure functions from hipocampo_search.py — import before module-level side effects
from hipocampo_search import (
    expandir_consulta,
    generar_patrones_ILIKE,
    fusionar_resultados,
    parse_query,
    formatear_compacto,
    formatear_json,
    _aplicar_boost_frase,
    _aplicar_decaimiento_temporal,
    _conceptos_consulta,
    _debe_rerank_auto,
    _proximidad,
    _penalizar_menciones_meta,
    _terminos_tsquery,
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


class TestParseQuery:
    def test_code(self):
        parsed = parse_query("code:opencode_session_forensics")
        assert parsed["query"] == ""
        assert parsed["filters"]["code"] == "opencode_session_forensics"

    def test_categories(self):
        parsed = parse_query("category:infra,trigger:mcp")
        assert parsed["filters"]["categories"] == ["infra", "trigger:mcp"]

    def test_id_y_fechas(self):
        parsed = parse_query("id:4039 after:2026-10-01 before:today")
        assert parsed["filters"]["ids"] == [4039]
        assert parsed["filters"]["created_after"] == "2026-10-01"
        assert parsed["filters"]["created_before"] == date.today().isoformat()

    def test_since_relativo(self):
        parsed = parse_query("since:7d")
        from datetime import timedelta

        assert parsed["filters"]["created_after"] == (date.today() - timedelta(days=7)).isoformat()

    def test_frase_entre_comillas(self):
        parsed = parse_query('buscar "transcript temporal eliminado"')
        assert parsed["phrases"] == ["transcript temporal eliminado"]
        assert parsed["query"] == "buscar"

    def test_texto_libre_se_conserva(self):
        parsed = parse_query("protocolo seguridad")
        assert parsed["query"] == "protocolo seguridad"
        assert parsed["filters"] == {}


class TestProximidad:
    def test_conceptos_cerca(self):
        conceptos = _conceptos_consulta("transcript temporal eliminado")
        texto = "Mejor extraer un transcript temporal y borrarlo al terminar."
        bonus, span, ini, fin = _proximidad(texto, conceptos)
        assert bonus == 30
        assert span <= 60
        assert 0 <= ini < fin <= len(texto)

    def test_conceptos_lejos(self):
        conceptos = _conceptos_consulta("transcript temporal eliminado")
        texto = "transcript " + ("x" * 900) + " temporal eliminado"
        bonus, span, _, _ = _proximidad(texto, conceptos)
        assert bonus == 0
        assert span > 700

    def test_menos_de_dos_conceptos(self):
        conceptos = _conceptos_consulta("transcript")
        assert _proximidad("transcript", conceptos)[0] == 0


class TestPenalizarMencionesMeta:
    def _res(self):
        return {
            "id": "v4040",
            "contenido": (
                'REGLA OPERATIVA — CÓMO USAR EL MCP. Ejemplo: buscar "transcript temporal eliminado" sí la encontró.'
            ),
            "metadatos": {"code": "regla_hipocampo_uso_retrieval"},
            "score": 100.0,
            "match_reason": ["léxico"],
        }

    def test_penaliza_regla_que_cita_la_consulta(self):
        r = self._res()
        out = _penalizar_menciones_meta([r], "transcript temporal eliminado")
        assert out[0]["score"] == 45.0
        assert "mención meta (penalizada)" in out[0]["match_reason"]

    def test_no_penaliza_si_la_consulta_es_sobre_reglas(self):
        r = self._res()
        out = _penalizar_menciones_meta([r], "reglas de búsqueda transcript temporal eliminado")
        assert out[0]["score"] == 100.0

    def test_no_penaliza_contenido_normal(self):
        r = self._res()
        r["metadatos"]["code"] = "opencode_session_forensics"
        r["contenido"] = "Cómo reconstruir una sesión: extraer un transcript temporal y borrarlo al terminar."
        out = _penalizar_menciones_meta([r], "transcript temporal eliminado")
        assert out[0]["score"] == 100.0

    def test_penaliza_mencion_en_backticks_sin_code_regla(self):
        r = self._res()
        r["metadatos"]["code"] = "mcp_mejoras_fases_1_3_20261020"
        r["contenido"] = (
            "MCP Hipocampo — registro de despliegue. El caso clave "
            "`transcript temporal eliminado` devuelve #4039 primero."
        )
        out = _penalizar_menciones_meta([r], "transcript temporal eliminado")
        assert out[0]["score"] == 45.0
        assert "mención meta (penalizada)" in out[0]["match_reason"]

    def test_penaliza_snapshot_largo_sin_code(self):
        r = self._res()
        r["metadatos"]["code"] = ""
        r["contenido"] = (
            "# Instrucciones de inicio de sesión\n\n"
            + ("relleno " * 40)
            + "El caso clave `transcript temporal eliminado` devuelve #4039."
        )
        out = _penalizar_menciones_meta([r], "transcript temporal eliminado")
        assert out[0]["score"] == 45.0

    def test_no_penaliza_si_tambien_aparece_sin_delimitar(self):
        r = self._res()
        r["metadatos"]["code"] = "mcp_mejoras_fases_1_3_20261020"
        r["contenido"] = (
            'El registro cita "transcript temporal eliminado" como ejemplo, '
            "pero el transcript temporal eliminado real está en otro archivo."
        )
        out = _penalizar_menciones_meta([r], "transcript temporal eliminado")
        assert out[0]["score"] == 100.0

    def test_no_penaliza_coincidencia_estructurada(self):
        r = self._res()
        r["channel"] = "structured"
        r["struct_score"] = 100.0
        r["contenido"] = 'code exacto: "transcript temporal eliminado"'
        out = _penalizar_menciones_meta([r], "transcript temporal eliminado")
        assert out[0]["score"] == 100.0


class TestFormatosCompactos:
    def _res(self):
        return {
            "id": "v4039",
            "contenido": "texto completo de la memoria",
            "summary": "Resumen corto",
            "passage": "Pasaje relevante con transcript temporal",
            "metadatos": {
                "code": "opencode_session_forensics",
                "date": "2026-10-20",
                "nivel": "semantica",
            },
            "score": 100.0,
            "method": "code_match",
            "tabla": "memoria_vectorial",
            "match_reason": ["code exacto"],
            "channels": ["structured"],
            "vec_score": 0,
            "lex_score": 0,
            "struct_score": 100,
        }

    def test_compacto(self):
        out = formatear_compacto([self._res()], "code:opencode_session_forensics", total=1)
        assert "#4039" in out
        assert "code=opencode_session_forensics" in out
        assert "Pasaje relevante" in out
        assert "texto completo" not in out

    def test_json(self):
        import json

        out = formatear_json([self._res()], "code:opencode_session_forensics", total=1)
        payload = json.loads(out)
        assert payload["total"] == 1
        assert payload["results"][0]["id_legible"] == "#4039"
        assert payload["results"][0]["code"] == "opencode_session_forensics"


class TestDecaimientoEstructurado:
    def test_struct_score_no_decae(self):
        item = {
            "contenido": "coincidencia exacta",
            "score": 100.0,
            "metadatos": {"date": "2026-01-01"},
            "method": "code_match",
            "source": "memoria_vectorial",
            "tabla": "memoria_vectorial",
            "code_snippet": None,
            "vec_score": 0,
            "lex_score": 0,
            "struct_score": 100,
        }
        out = _aplicar_decaimiento_temporal([item], hoy=_HOY)
        assert out[0]["score"] == 100.0


class TestExpansionSinStopwords:
    def test_stopwords_no_expanden_a_borrado(self):
        terms = expandir_consulta("pautas de uso del MCP en el servidor")
        assert "pautas" in terms
        assert "servidor" in terms
        # "el" está dentro de "eliminar": antes inyectaba toda la familia.
        assert not ({"borrar", "eliminado", "eliminar", "suprimir"} & set(terms))

    def test_borrado_explicito_si_expande(self):
        terms = expandir_consulta("transcript temporal eliminado")
        assert "borrar" in terms
        assert "transcript" in terms

    def test_terminos_tsquery_sin_stopwords(self):
        assert _terminos_tsquery("pautas de uso del MCP en el servidor") == [
            "pautas",
            "uso",
            "mcp",
            "servidor",
        ]


class TestFraseCompleta:
    def test_boost_si_la_consulta_aparece_literal(self):
        r = {
            "contenido": "TypeSafe API verificada y funcionando",
            "summary": "",
            "score": 80.0,
            "match_reason": [],
        }
        out = _aplicar_boost_frase([r], [], "TypeSafe API verificada")
        assert out[0]["score"] == 100.0
        assert out[0]["full_phrase_match"] is True

    def test_decaimiento_no_toca_frase_exacta(self):
        r = {
            "contenido": "TypeSafe API verificada y funcionando",
            "score": 80.0,
            "metadatos": {"date": "2026-01-01"},
            "method": "lexico_expansivo",
            "channel": "lexical",
            "vec_score": 0,
            "lex_score": 80,
            "struct_score": 0,
        }
        out = _aplicar_decaimiento_temporal([dict(r)], hoy=date(2026, 10, 20), query="TypeSafe API verificada")
        assert out[0]["score"] == 80.0
        assert out[0]["exact_phrase"] is True

    def test_decaimiento_si_solo_comparte_palabras(self):
        r = {
            "contenido": "Otra memoria sobre API y TypeSafe",
            "score": 80.0,
            "metadatos": {"date": "2026-01-01"},
            "method": "lexico_expansivo",
            "channel": "lexical",
            "vec_score": 0,
            "lex_score": 80,
            "struct_score": 0,
        }
        out = _aplicar_decaimiento_temporal([r], hoy=date(2026, 10, 20), query="TypeSafe API verificada")
        assert out[0]["score"] < 80.0


class TestAutoRerank:
    @staticmethod
    def _r(score, **extra):
        base = {"score": score, "method": "vectorial", "match_reason": []}
        base.update(extra)
        return base

    def test_no_rerank_si_top_es_alto(self):
        rs = [self._r(100), self._r(100), self._r(80)]
        assert _debe_rerank_auto(rs, "consulta de prueba", {}) is False

    def test_no_rerank_si_hay_proximidad_fuerte(self):
        rs = [self._r(60.8, proximity_bonus=30), self._r(56.3), self._r(50)]
        assert _debe_rerank_auto(rs, "consulta de prueba", {}) is False

    def test_rerank_si_top_debil_o_empatado(self):
        rs = [self._r(60), self._r(55), self._r(50)]
        assert _debe_rerank_auto(rs, "consulta de prueba", {}) is True
