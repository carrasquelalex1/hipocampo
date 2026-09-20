"""Cadena de juicio semántico: TypeSafe → classifier.dev → local.

Todo mockeado: sin red, sin BD. Verifica el contrato de fallback
(None = sin veredicto → siguiente nivel) y el mapeo de respuestas.
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import classifier_client as cl


def _res(label, scores, conf=None):
    return {
        "label": label,
        "confidence": conf if conf is not None else max(scores.values()),
        "scores": scores,
        "model": "jev-1.13.0",
    }


class TestContradicciones:
    def test_detecta_sobre_umbral(self, monkeypatch):
        monkeypatch.setattr(
            cl,
            "_post",
            lambda *a, **k: [
                _res("contradiction", {"contradiction": 0.95, "no contradiction": 0.05}),
                _res("no contradiction", {"contradiction": 0.1, "no contradiction": 0.9}),
            ],
        )
        out = cl.contradicciones_batch("nuevo", [(1, "a"), (2, "b")])
        assert out == {1: 0.95}

    def test_fallo_red_devuelve_none(self, monkeypatch):
        monkeypatch.setattr(cl, "_post", lambda *a, **k: None)
        assert cl.contradicciones_batch("nuevo", [(1, "a")]) is None

    def test_vacio_sin_candidatos(self):
        assert cl.contradicciones_batch("nuevo", []) == {}


class TestRelacion:
    def test_mismo_hecho_confirmado(self, monkeypatch):
        monkeypatch.setattr(
            cl, "_post", lambda *a, **k: [_res("mismo", {"mismo": 0.9, "relacionado": 0.08, "distinto": 0.02})]
        )
        assert cl.mismo_hecho("a", "a") is True

    def test_distinto_no_fusiona(self, monkeypatch):
        monkeypatch.setattr(
            cl, "_post", lambda *a, **k: [_res("distinto", {"mismo": 0.01, "relacionado": 0.05, "distinto": 0.94})]
        )
        assert cl.mismo_hecho("a", "b") is False

    def test_sin_veredicto(self, monkeypatch):
        monkeypatch.setattr(cl, "_post", lambda *a, **k: None)
        assert cl.mismo_hecho("a", "b") is None


class TestRelevancia:
    def test_probabilidad_relevante(self, monkeypatch):
        monkeypatch.setattr(
            cl,
            "_post",
            lambda *a, **k: [
                _res("relevant", {"relevant": 0.94, "not relevant": 0.06}),
                _res("not relevant", {"relevant": 0.2, "not relevant": 0.8}),
            ],
        )
        out = cl.relevancia_batch("q", [(0, "a"), (1, "b")])
        assert out[0] == 0.94
        assert out[1] == 0.2


class TestRerankSearch:
    def _fakes(self):
        return [
            {"contenido": "receta de cocina", "score": 48.0},
            {"contenido": "caso de malaria", "score": 47.0},
            {"contenido": "tratamiento malaria", "score": 46.0},
        ]

    def test_classifier_reordena(self, monkeypatch):
        import hipocampo_search as s

        monkeypatch.setenv("HIPOCAMPO_TYPESAFE", "0")
        monkeypatch.setenv("HIPOCAMPO_CLASSIFIER", "1")
        monkeypatch.setattr(cl, "relevancia_batch", lambda q, items: {0: 0.0, 1: 1.0, 2: 1.0})
        out = s._rerank_typesafe(self._fakes(), "malaria", top_n=3)
        assert out[0]["contenido"] == "caso de malaria"
        assert out[-1]["contenido"] == "receta de cocina"
        assert out[-1]["score"] == 24.0  # 48 * (0.5 + 0.5*0)

    def test_sin_tiers_devuelve_intacto(self, monkeypatch):
        import hipocampo_search as s

        monkeypatch.setenv("HIPOCAMPO_TYPESAFE", "0")
        monkeypatch.setenv("HIPOCAMPO_CLASSIFIER", "0")
        fakes = self._fakes()
        out = s._rerank_typesafe(fakes, "malaria", top_n=3)
        assert [r["contenido"] for r in out] == [r["contenido"] for r in fakes]


class TestDedupGate:
    def test_sin_tiers_flujo_normal(self, monkeypatch):
        import hipocampo_dedup as d

        monkeypatch.setenv("HIPOCAMPO_TYPESAFE", "0")
        monkeypatch.setenv("HIPOCAMPO_CLASSIFIER", "0")
        g = [{"id": 1, "text": "a"}, {"id": 2, "text": "a"}]
        assert d._typesafe_confirma_grupo(g) is None
