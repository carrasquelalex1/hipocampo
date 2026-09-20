"""hipocampo_semantic con dependencias falsas: sin BD, sin red."""

import sys
import os
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import hipocampo_semantic as sem


def _conn_con(candidatos):
    class Cur:
        def execute(self, *a, **k):
            pass

        def fetchone(self):
            return None

        def fetchall(self):
            return list(candidatos)

        def close(self):
            pass

    class Conn:
        def cursor(self):
            return Cur()

        def close(self):
            pass

    return Conn()


def _no_embed(texto):
    return None


class TestDetectar:
    CANDS = [(7, "el agua hierve a 50C", 0.4), (8, "me gusta el te", 0.5)]

    def test_tier1_gana(self):
        ts = SimpleNamespace(enabled=lambda: True, contradicciones_batch=lambda n, p: {7: 0.9})
        out = sem.detectar_contradicciones(
            "nuevo", [0.1] * 4, conn_fn=lambda: _conn_con(self.CANDS), embed_fn=_no_embed, ts=ts, cl=None
        )
        assert out == [
            {
                "id": 7,
                "contenido": "el agua hierve a 50C",
                "sim_new_old": 0.6,
                "sim_neg_old": 0.9,
                "confidence": 0.9,
                "via": "typesafe",
            }
        ]

    def test_tier1_sin_veredicto_tier2(self):
        ts = SimpleNamespace(enabled=lambda: True, contradicciones_batch=lambda n, p: None)
        cl = SimpleNamespace(enabled=lambda: True, contradicciones_batch=lambda n, p: {8: 0.8})
        out = sem.detectar_contradicciones(
            "nuevo", [0.1] * 4, conn_fn=lambda: _conn_con(self.CANDS), embed_fn=_no_embed, ts=ts, cl=cl
        )
        assert len(out) == 1 and out[0]["via"] == "classifier"

    def test_todo_falla_vacio_sin_embeddings(self):
        out = sem.detectar_contradicciones(
            "nuevo", [0.1] * 4, conn_fn=lambda: _conn_con(self.CANDS), embed_fn=_no_embed, ts=None, cl=None
        )
        assert out == []

    def test_sin_candidatos(self):
        out = sem.detectar_contradicciones(
            "nuevo", [0.1] * 4, conn_fn=lambda: _conn_con([]), embed_fn=_no_embed, ts=None, cl=None
        )
        assert out == []


class TestDedup:
    def test_confirma_distinto_omite(self):
        class Cur:
            def execute(self, *a, **k):
                pass

            def fetchone(self):
                return (9, "otro texto")

            def close(self):
                pass

        class Conn:
            def cursor(self):
                return Cur()

            def close(self):
                pass

        cl = SimpleNamespace(enabled=lambda: True, mismo_hecho=lambda a, b: False)
        out = sem.check_dedup_semantic(1, "nuevo", [0.1] * 4, conn_fn=Conn, ts=None, cl=cl)
        assert out is None

    def test_sin_veredicto_devuelve_dup(self):
        class Cur:
            def execute(self, *a, **k):
                pass

            def fetchone(self):
                return (9, "otro texto")

            def close(self):
                pass

        class Conn:
            def cursor(self):
                return Cur()

            def close(self):
                pass

        assert sem.check_dedup_semantic(1, "nuevo", [0.1] * 4, conn_fn=Conn, ts=None, cl=None) == 9
