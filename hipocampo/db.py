"""Shared database connection, embedding generation, and config loading.

Replaces the duplicated boilerplate previously found in 11+ scripts.
Usage:
    from hipocampo.db import get_conn, get_embedding, load_config
"""
import os
import sys
import functools
from dotenv import load_dotenv
from openai import OpenAI


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
        env_path = os.getenv('ENV_PATH')
    if env_path is None or not os.path.exists(env_path):
        candidate = os.path.join(_project_root(), '.env')
        if os.path.exists(candidate):
            env_path = candidate
    if env_path:
        load_dotenv(env_path)

    return {
        'DB_NAME': os.getenv('DB_NAME', 'hipocampo_db'),
        'DB_USER': os.getenv('DB_USER', 'alex'),
        'DB_PASSWORD': os.getenv('DB_PASSWORD', ''),
        'DB_HOST': os.getenv('DB_HOST', '/var/run/postgresql'),
        'NVIDIA_API_KEY': os.getenv('NVIDIA_API_KEY', ''),
    }


_pool = None


def init_pool(minconn=1, maxconn=10):
    """Pre-warm connection pool. Called once at server startup."""
    import psycopg2.pool
    global _pool
    if _pool is None:
        cfg = load_config()
        _pool = psycopg2.pool.ThreadedConnectionPool(
            minconn, maxconn,
            host=cfg['DB_HOST'],
            user=cfg['DB_USER'],
            dbname=cfg['DB_NAME'],
            password=cfg['DB_PASSWORD'],
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
        host=config['DB_HOST'],
        user=config['DB_USER'],
        dbname=config['DB_NAME'],
        password=config['DB_PASSWORD'],
    )


@functools.lru_cache(maxsize=128)
def _cached_embedding(text: str, api_key: str) -> tuple:
    """LRU-cached embedding: same text + api_key skip API call."""
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
    return tuple(resp.data[0].embedding)


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
    """
    if api_key is None:
        api_key = os.getenv("NVIDIA_API_KEY") or ""
    try:
        result = _cached_embedding(text, api_key)
        return list(result)
    except Exception:
        return None
