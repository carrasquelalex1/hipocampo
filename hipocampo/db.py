"""Shared database connection, embedding generation, and config loading.

Replaces the duplicated boilerplate previously found in 11+ scripts.
Usage:
    from hipocampo.db import get_conn, get_embedding, load_config, validate_config
"""

import os
import logging
import threading
import hashlib
import openai
from dotenv import load_dotenv
from openai import OpenAI

logger = logging.getLogger(__name__)

_pool = None
_pool_lock = threading.Lock()


def _find_env():
    """Return the first existing .env path.

    Resolution order:
      1. ENV_PATH environment variable
      2. ~/.hipocampo/.env  (explicit user-level config)
      3. project_root/.env  (fallback for Docker/Fly deployments)
    """
    env_path = os.getenv("ENV_PATH")
    if env_path and os.path.exists(env_path):
        return env_path

    user_env = os.path.expanduser("~/.hipocampo/.env")
    if os.path.exists(user_env):
        return user_env

    project_env = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
    if os.path.exists(project_env):
        return project_env

    return ""


def load_config(env_path=None):
    if env_path is None:
        env_path = _find_env()
    if env_path:
        load_dotenv(env_path)

    return {
        "DB_NAME": os.getenv("DB_NAME", "hipocampo_db"),
        "DB_USER": os.getenv("DB_USER", "alex"),
        "DB_PASSWORD": os.getenv("DB_PASSWORD", ""),
        "DB_HOST": os.getenv("DB_HOST", "/var/run/postgresql"),
        "NVIDIA_API_KEY": os.getenv("NVIDIA_API_KEY", ""),
    }


def validate_config(config=None):
    """Validate critical config values and return a list of error messages.

    Returns an empty list if everything is fine.
    """
    if config is None:
        config = load_config()

    errors = []
    missing = []
    for key in ["DB_HOST", "DB_USER", "DB_NAME"]:
        if not config.get(key):
            missing.append(key)

    if missing:
        errors.append(
            f"PostgreSQL connection incomplete: {', '.join(missing)} no están "
            f"configurados en .env o variables de entorno."
        )

    if not config.get("NVIDIA_API_KEY"):
        errors.append(
            "NVIDIA_API_KEY no está configurada. Embeddings fallarán. Configúrala en .env: NVIDIA_API_KEY=tu_key"
        )

    return errors


def init_pool(minconn=1, maxconn=10):
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                import psycopg2.pool

                config = load_config()
                errs = validate_config(config)
                if errs:
                    raise RuntimeError(
                        "No se puede inicializar el pool de conexiones:\n" + "\n".join(f"  - {e}" for e in errs)
                    )
                _pool = psycopg2.pool.ThreadedConnectionPool(
                    minconn,
                    maxconn,
                    host=config["DB_HOST"],
                    user=config["DB_USER"],
                    dbname=config["DB_NAME"],
                    password=config["DB_PASSWORD"],
                )


def close_pool():
    global _pool
    if _pool is not None:
        _pool.closeall()
        _pool = None


class _PooledConnection:
    def __init__(self, conn, pool):
        object.__setattr__(self, "_conn", conn)
        object.__setattr__(self, "_pool", pool)

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def __setattr__(self, name, value):
        setattr(self._conn, name, value)

    def close(self):
        pool = object.__getattribute__(self, "_pool")
        conn = object.__getattribute__(self, "_conn")
        if pool is not None:
            pool.putconn(conn)
        else:
            conn.close()


def get_conn(config=None):
    if config is None:
        config = load_config()

    global _pool
    if _pool is not None:
        raw_conn = _pool.getconn()
    else:
        import psycopg2

        errs = validate_config(config)
        if errs:
            raise RuntimeError("No se puede conectar a PostgreSQL:\n" + "\n".join(f"  - {e}" for e in errs))
        raw_conn = psycopg2.connect(
            host=config["DB_HOST"],
            user=config["DB_USER"],
            dbname=config["DB_NAME"],
            password=config["DB_PASSWORD"],
        )

    from pgvector.psycopg2 import register_vector

    register_vector(raw_conn)

    return _PooledConnection(raw_conn, _pool)


from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

_EMBEDDING_CACHE: dict[str, list[float]] = {}
_EMBEDDING_CACHE_MAX = 512


def _embedding_cache_key(text: str, dims: int) -> str:
    return f"{hashlib.sha256(text.encode()).hexdigest()}:{dims}"


def _cached_embedding_lookup(text: str, dims: int = 1024) -> list[float] | None:
    key = _embedding_cache_key(text, dims)
    return _EMBEDDING_CACHE.get(key)


def _cached_embedding_store(text: str, dims: int, embedding: list[float]):
    key = _embedding_cache_key(text, dims)
    if len(_EMBEDDING_CACHE) >= _EMBEDDING_CACHE_MAX:
        _EMBEDDING_CACHE.clear()
    _EMBEDDING_CACHE[key] = embedding


def _is_retryable_openai_error(exc):
    """Return True for transient OpenAI errors that should be retried."""
    import openai

    return isinstance(
        exc,
        (
            openai.RateLimitError,
            openai.APITimeoutError,
            openai.APIConnectionError,
            openai.InternalServerError,
            openai.APIStatusError,
        ),
    ) and not isinstance(exc, (openai.AuthenticationError, openai.BadRequestError))


def get_embedding(text, dims=1024, api_key=None, use_cache=True):
    if api_key is None:
        api_key = os.getenv("NVIDIA_API_KEY")
    if not api_key:
        logger.warning("NVIDIA_API_KEY no configurada — no se puede generar embedding")
        return None

    if use_cache:
        cached = _cached_embedding_lookup(text, dims)
        if cached is not None:
            logger.debug("Embedding cache hit: %r...", text[:40])
            return cached

    @retry(
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=1, min=1, max=30),
        retry=retry_if_exception_type(
            (
                openai.RateLimitError,
                openai.APITimeoutError,
                openai.APIConnectionError,
                openai.InternalServerError,
                openai.APIStatusError,
            )
        ),
        reraise=False,
        before_sleep=lambda retry_state: logger.warning(
            "Embedding retry %d/%d tras %.1fs: %s",
            retry_state.attempt_number,
            5,
            retry_state.outcome_timestamp - retry_state.start_time if retry_state.outcome_timestamp else 0,
            retry_state.outcome.exception() if retry_state.outcome else "unknown",
        ),
    )
    def _do():
        client = OpenAI(
            base_url="https://integrate.api.nvidia.com/v1",
            api_key=api_key,
        )
        resp = client.embeddings.create(
            input=text,
            model="nvidia/nv-embedqa-e5-v5",
            encoding_format="float",
            extra_body={"input_type": "query"},
        )
        return resp.data[0].embedding

    try:
        result = _do()
        if result is not None and use_cache:
            _cached_embedding_store(text, dims, result)
        return result
    except openai.AuthenticationError:
        logger.warning("NVIDIA_API_KEY inválida o expirada — embedding falló")
        return None
    except openai.BadRequestError as e:
        logger.warning("Bad request a API NVIDIA: %s", e)
        return None
    except Exception as e:
        logger.warning("Embedding falló tras 5 intentos: %s", e)
        return None
