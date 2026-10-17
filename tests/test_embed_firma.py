"""Unit: firma de contenido (embedding_src_md5), reintentos de embedding y failover."""

import hashlib
import os
import sys

REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_DIR)

from hipocampo import db  # noqa: E402


def test_contenido_firma_es_md5_del_texto():
    texto = "hola mundo"
    assert db.contenido_firma(texto) == hashlib.md5(texto.encode("utf-8")).hexdigest()


def test_contenido_firma_trunca_igual_que_embedding():
    largo = "x" * (db.MAX_EMBED_CHARS + 123)
    assert db.contenido_firma(largo) == db.contenido_firma(largo[: db.MAX_EMBED_CHARS])
    assert db.contenido_firma(largo) == hashlib.md5(largo[: db.MAX_EMBED_CHARS].encode("utf-8")).hexdigest()


def test_get_embedding_with_retries_exito_del_primero(monkeypatch):
    llamadas = []

    def fake(text, timeout_s=None):
        llamadas.append(timeout_s)
        return [0.1]

    monkeypatch.setattr(db, "get_embedding", fake)
    assert db.get_embedding_with_retries("t", delays=(0, 0)) == [0.1]
    assert len(llamadas) == 1


def test_get_embedding_with_retries_reintenta_y_logra(monkeypatch):
    intentos = {"n": 0}

    def fake(text, timeout_s=None):
        intentos["n"] += 1
        return None if intentos["n"] < 3 else [0.2]

    monkeypatch.setattr(db, "get_embedding", fake)
    assert db.get_embedding_with_retries("t", delays=(0, 0, 0)) == [0.2]
    assert intentos["n"] == 3


def test_get_embedding_with_retries_agota(monkeypatch):
    monkeypatch.setattr(db, "get_embedding", lambda text, timeout_s=None: None)
    assert db.get_embedding_with_retries("t", delays=(0, 0)) is None


def test_get_embedding_with_retries_blindado_ante_excepciones(monkeypatch):
    def boom(text, timeout_s=None):
        raise RuntimeError("ollama down")

    monkeypatch.setattr(db, "get_embedding", boom)
    assert db.get_embedding_with_retries("t", delays=(0,)) is None


def test_failover_propaga_timeout_s(monkeypatch):
    from hipocampo import model_failover

    visto = {}

    def fake_cached(text, api_key, model, timeout_s=None):
        visto["timeout_s"] = timeout_s
        return [0.5] * 8

    monkeypatch.setattr(db, "_cached_embedding", fake_cached)
    out = model_failover.get_embedding_with_failover("texto", api_key="k", timeout_s=123)
    assert visto["timeout_s"] == 123
    assert out == [0.5] * 8


def test_contenido_firma_multibyte_y_borde_exacto():
    """Tildes, emoji y el borde exacto de MAX_EMBED_CHARS (consistencia con md5(left) en SQL)."""
    caso = "Memoria con tildes áéíóú ñ ¿¡ — 中文 🧠✨"
    assert db.contenido_firma(caso) == hashlib.md5(caso.encode("utf-8")).hexdigest()

    justo = "a" * db.MAX_EMBED_CHARS
    assert db.contenido_firma(justo) == hashlib.md5(justo.encode("utf-8")).hexdigest()
    # Un carácter de más no cambia la firma (se trunca en el mismo punto que el embedding)
    assert db.contenido_firma(justo + "b") == db.contenido_firma(justo)
