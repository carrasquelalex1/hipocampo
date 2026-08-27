"""Shared database connection, embedding generation, and config loading.

Replaces the duplicated boilerplate previously found in 11+ scripts.
Usage:
    from hipocampo.db import get_conn, get_embedding, load_config
"""

import os
import functools
import logging
from dotenv import load_dotenv
from openai import OpenAI

logger = logging.getLogger("hipocampo.db")


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
    if not config.get("NVIDIA_API_KEY"):
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
    )


def _get_active_embed_model() -> str:
    """Return the active embedding model, checking failover config first."""
    try:
        from hipocampo.model_failover import get_active_model

        m = get_active_model("embedding")
        if m:
            return m
    except ImportError:
        pass
    return "nvidia/llama-nemotron-embed-vl-1b-v2"


@functools.lru_cache(maxsize=128)
def _cached_embedding(text: str, api_key: str, model: str) -> tuple:
    """LRU-cached embedding: same text + api_key + model skip API call."""
    client = _get_client(api_key)
    resp = client.embeddings.create(
        input=text,
        model=model,
        encoding_format="float",
        extra_body={"input_type": "query", "dimensions": 1024},
    )
    return tuple(resp.data[0].embedding)


_embedding_last_error = None


def get_embedding_last_error():
    """Return the last error message from get_embedding, or None."""
    return _embedding_last_error


_client_cache = {}


def _get_client(api_key=None):
    if api_key is None:
        api_key = os.getenv("NVIDIA_API_KEY")
    if api_key not in _client_cache:
        _client_cache[api_key] = OpenAI(
            base_url="https://integrate.api.nvidia.com/v1",
            api_key=api_key,
        )
    return _client_cache[api_key]


def get_embedding(text, dims=1024, api_key=None):
    """Generate a 1024-dim embedding via NVIDIA API.

    Uses LRU cache (128 entries) — repeated queries for the same text
    skip the API call entirely. Returns ``None`` on failure.

    On model errors (410/404/EOL), triggers automatic failover to find
    a working embedding model across all configured providers.
    """
    global _embedding_last_error
    if api_key is None:
        api_key = os.getenv("NVIDIA_API_KEY") or ""
    if not api_key:
        _embedding_last_error = "NVIDIA_API_KEY no está configurada"
        return None
    # Guard: límite del modelo es 8192 tokens (~4 chars/token). Truncar con margen.
    MAX_EMBED_CHARS = 28_000
    if len(text) > MAX_EMBED_CHARS:
        text = text[:MAX_EMBED_CHARS]
    try:
        model = _get_active_embed_model()
        result = _cached_embedding(text, api_key, model)
        _embedding_last_error = None
        return list(result)
    except Exception as e:
        err_str = str(e)

        # On model-level errors, try failover
        try:
            from hipocampo.model_failover import is_model_error, get_embedding_with_failover

            if is_model_error(e):
                logger.warning("Embedding model %s failed, trying failover...", model)
                result = get_embedding_with_failover(text, dims=dims, api_key=api_key)
                if result is not None:
                    _embedding_last_error = None
                    return result
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
