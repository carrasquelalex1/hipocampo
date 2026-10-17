"""Shared database connection, embedding generation, and config loading.

Replaces the duplicated boilerplate previously found in 11+ scripts.
Usage:
    from hipocampo.db import get_conn, get_embedding, load_config
"""

import hashlib
import os
import time
import functools
import logging
from dotenv import load_dotenv
from openai import OpenAI

logger = logging.getLogger("hipocampo.db")

# === Embeddings locales (Ollama) ===
EMBED_BASE_URL = os.getenv("EMBED_BASE_URL", "http://127.0.0.1:11434/v1")
EMBED_MODEL = os.getenv("EMBED_MODEL", "qwen3-embedding:0.6b")

# Límite del modelo (~8192 tokens ≈ 4 chars/token) con margen. Único lugar de
# verdad: get_embedding trunca con esto y la firma (embedding_src_md5) se
# calcula sobre el mismo texto truncado — el barredor compara peras con peras.
MAX_EMBED_CHARS = 28_000


def contenido_firma(text: str) -> str:
    """MD5 del texto que realmente se embebe (aplicando el mismo truncado).

    Se guarda en `metadatos.embedding_src_md5` junto al embedding. El barredor
    marca como pendiente toda fila donde md5(left(contenido, MAX_EMBED_CHARS))
    no coincida con esta firma (corte de luz, red caída, edición directa, ...).
    """
    return hashlib.md5(text[:MAX_EMBED_CHARS].encode("utf-8")).hexdigest()


def get_embedding_with_retries(text, timeout_s=None, delays=(5.0, 30.0, 120.0)):
    """get_embedding con reintentos y esperas crecientes (jobs de background).

    1 intento + len(delays) reintentos; devuelve None si se agotan todos. No
    depende del estado en memoria: si igual falla, la fila queda desincronizada
    y la repara el barredor (hipocampo_embed_sweeper.py) leyendo la BD.
    """
    try:
        emb = get_embedding(text, timeout_s=timeout_s)
    except Exception as e:  # get_embedding normalmente devuelve None; blindaje extra
        logger.warning("Embedding lanzó excepción: %s", e)
        emb = None
    if emb is not None:
        return emb
    for i, delay in enumerate(delays):
        logger.warning("Embedding no disponible — reintento %d/%d en %.0fs", i + 1, len(delays), delay)
        time.sleep(delay)
        try:
            emb = get_embedding(text, timeout_s=timeout_s)
        except Exception as e:
            logger.warning("Reintento %d/%d falló: %s", i + 1, len(delays), e)
            continue
        if emb is not None:
            return emb
    return None


def _project_root():
    """Return absolute path to the project root (one level above scripts/)."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_config(env_path=None):
    """Load .env and return a dict with standard config keys.

    Resolution order:
      1. Explicit *env_path* argument
      2. ``ENV_PATH`` environment variable
      3. ``<project_root>/.env``
    """
    if env_path is None:
        env_path = os.getenv("ENV_PATH")
    if env_path is None or not os.path.exists(env_path):
        candidate = os.path.join(_project_root(), ".env")
        if os.path.exists(candidate):
            env_path = candidate
    if env_path:
        load_dotenv(env_path)

    return {
        "DB_NAME": os.getenv("DB_NAME", "hipocampo_db"),
        "DB_USER": os.getenv("DB_USER", "alex"),
        "DB_PASSWORD": os.getenv("DB_PASSWORD", ""),
        "DB_HOST": os.getenv("DB_HOST", "/var/run/postgresql"),
        "NVIDIA_API_KEY": os.getenv("NVIDIA_API_KEY", ""),
    }


_pool = None


def validate_config(config=None):
    """Validate DB config and return list of missing/empty fields."""
    if config is None:
        config = load_config()
    missing = []
    db_keys = ["DB_HOST", "DB_USER", "DB_NAME"]
    empty_db = [k for k in db_keys if not config.get(k)]
    if empty_db:
        missing.append(f"PostgreSQL config missing: {', '.join(empty_db)}")
    if "nvidia.com" in EMBED_BASE_URL and not config.get("NVIDIA_API_KEY"):
        missing.append("NVIDIA_API_KEY missing")
    return missing


def init_pool(minconn=1, maxconn=10):
    """Pre-warm connection pool. Called once at server startup."""
    import psycopg2.pool

    global _pool
    if _pool is None:
        cfg = load_config()
        try:
            _pool = psycopg2.pool.ThreadedConnectionPool(
                minconn,
                maxconn,
                host=cfg["DB_HOST"],
                user=cfg["DB_USER"],
                dbname=cfg["DB_NAME"],
                password=cfg["DB_PASSWORD"],
                client_encoding="UTF8",
            )
        except psycopg2.Error as e:
            import logging

            logging.getLogger("hipocampo").warning(
                "No se pudo crear pool de conexiones (DB no disponible). "
                "Las herramientas de BD fallarán hasta que esté accesible: %s",
                e,
            )


def get_conn_from_pool():
    """Get a connection from the pool (falls back to direct connect)."""
    if _pool is not None:
        try:
            return _pool.getconn()
        except Exception:
            pass
    return get_conn()


def get_conn(config=None):
    """Return a psycopg2 connection.

    If *config* is ``None`` it is loaded from the environment via
    :func:`load_config`.
    """
    import psycopg2

    if config is None:
        config = load_config()
    return psycopg2.connect(
        host=config["DB_HOST"],
        user=config["DB_USER"],
        dbname=config["DB_NAME"],
        password=config["DB_PASSWORD"],
        client_encoding="UTF8",
    )


def _get_active_embed_model() -> str:
    """Return the active embedding model (local Ollama by default)."""
    return EMBED_MODEL


@functools.lru_cache(maxsize=128)
def _cached_embedding(text: str, api_key: str, model: str, timeout_s: float | None = None) -> tuple:
    """LRU-cached embedding: same text + api_key + model (+ timeout) skip API call."""
    client = _get_client(api_key, timeout_s)
    resp = client.embeddings.create(
        input=text,
        model=model,
        encoding_format="float",
    )
    return tuple(resp.data[0].embedding)


_embedding_last_error = None


def get_embedding_last_error():
    """Return the last error message from get_embedding, or None."""
    return _embedding_last_error


_client_cache = {}


def _get_client(api_key=None, timeout_s=None):
    if api_key is None:
        api_key = os.getenv("NVIDIA_API_KEY") or "ollama"
    if timeout_s is None:
        # Timeout configurable: en Ollama CPU lento (i3, ~7-45s/embedding) conviene
        # fallar temprano y degradar a búsqueda léxica (GIN) en vez de colgar la
        # búsqueda completa. Default 90s para NIM; 25s para Ollama local.
        base_local = EMBED_BASE_URL
        is_local = "127.0.0.1" in base_local or "localhost" in base_local
        timeout_s = float(os.getenv("EMBED_TIMEOUT_S", "25" if is_local else "90"))
    cache_key = (api_key, timeout_s)
    if cache_key not in _client_cache:
        _client_cache[cache_key] = OpenAI(
            base_url=EMBED_BASE_URL,
            api_key=api_key,
            timeout=timeout_s,
        )
    return _client_cache[cache_key]


def get_embedding(text, dims=1024, api_key=None, timeout_s=None):
    """Generate a 1024-dim embedding via Ollama local (qwen3-embedding:0.6b).

    Uses LRU cache (128 entries) — repeated queries for the same text
    skip the API call entirely. Returns ``None`` on failure.

    timeout_s: override opcional del timeout del cliente HTTP (None = default
    del entorno: 25s local / 90s remoto). Los jobs en BACKGROUND (backfill de
    saves/updates grandes) pasan p.ej. 900s para no abortar embeddings lentos
    sin afectar al path interactivo.
    """
    global _embedding_last_error
    if api_key is None:
        api_key = os.getenv("NVIDIA_API_KEY") or "ollama"
    if not api_key:
        _embedding_last_error = "API key no está configurada"
        return None
    # Guard: truncar en MAX_EMBED_CHARS (constante del módulo) — contenido_firma
    # usa exactamente el mismo recorte para que la firma sea comparable en SQL.
    if len(text) > MAX_EMBED_CHARS:
        text = text[:MAX_EMBED_CHARS]
    try:
        model = _get_active_embed_model()
        _t0 = time.monotonic()
        result = _cached_embedding(text, api_key, model, timeout_s)
        _latency = time.monotonic() - _t0
        if _latency > 1.0:
            logger.info("embedding %s generado en %.2fs (chars=%d)", model, _latency, len(text))
        if _latency > 5.0:
            logger.warning(
                "ALTA LATENCIA de embedding: %.2fs (modelo=%s) — Ollama puede estar sobrecargido", _latency, model
            )
        _embedding_last_error = None
        return list(result)
    except Exception as e:
        err_str = str(e)

        # On model-level errors, try failover
        try:
            from hipocampo.model_failover import is_model_error, get_embedding_with_failover

            if is_model_error(e):
                logger.warning("Embedding model %s failed, trying failover...", model)
                result = get_embedding_with_failover(text, dims=dims, api_key=api_key, timeout_s=timeout_s)
                if result is not None:
                    _embedding_last_error = None
                    # list(): el failover puede devolver tuple y psycopg2 no
                    # adapta tuple a ::vector (CannotCoerce record → vector).
                    return list(result)
        except ImportError:
            pass

        import re as _re

        status_code = ""
        m = _re.search(r"\b(40[13]|429)\b", err_str)
        if m:
            status_code = m.group(1)
        if status_code in ("401", "403") or "Unauthorized" in err_str or "Forbidden" in err_str:
            _embedding_last_error = f"API key inválida o revocada (HTTP {status_code or err_str[:20]})"
        elif "400" in err_str or "input_type" in err_str:
            _embedding_last_error = f"Error de formato en petición: {err_str[:120]}"
        elif "429" in err_str or "Too Many Requests" in err_str:
            _embedding_last_error = "Límite de tasa excedido (429)"
        elif "Connection" in err_str or "timeout" in err_str.lower():
            _embedding_last_error = f"Error de conexión con API: {err_str[:120]}"
        else:
            _embedding_last_error = err_str[:200]
        return None
