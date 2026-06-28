"""Shared database connection, embedding generation, and config loading.

Replaces the duplicated boilerplate previously found in 11+ scripts.
Usage:
    from hipocampo.db import get_conn, get_embedding, load_config
"""
import os
import sys
import threading
from dotenv import load_dotenv
from openai import OpenAI


_pool = None
_pool_lock = threading.Lock()


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


def init_pool(minconn=1, maxconn=10):
    """Initialize a ``ThreadedConnectionPool`` singleton.

    Safe to call multiple times — only the first call creates the pool.
    """
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                import psycopg2.pool
                config = load_config()
                _pool = psycopg2.pool.ThreadedConnectionPool(
                    minconn, maxconn,
                    host=config['DB_HOST'],
                    user=config['DB_USER'],
                    dbname=config['DB_NAME'],
                    password=config['DB_PASSWORD'],
                )


def close_pool():
    """Close all connections in the pool and reset the singleton."""
    global _pool
    if _pool is not None:
        _pool.closeall()
        _pool = None


class _PooledConnection:
    """Thin proxy over ``psycopg2.extensions.connection``.

    Delegates every attribute except ``close()`` to the raw connection.
    ``close()`` returns the connection to the pool instead of closing it.
    """

    def __init__(self, conn, pool):
        object.__setattr__(self, '_conn', conn)
        object.__setattr__(self, '_pool', pool)

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def __setattr__(self, name, value):
        setattr(self._conn, name, value)

    def close(self):
        pool = object.__getattribute__(self, '_pool')
        conn = object.__getattribute__(self, '_conn')
        if pool is not None:
            pool.putconn(conn)
        else:
            conn.close()


def get_conn(config=None):
    """Return a ``psycopg2`` connection, optionally from the pool.

    If :func:`init_pool` has been called the connection is drawn from the
    pool and ``.close()`` returns it to the pool.  Otherwise a fresh
    connection is created (existing callers are unaffected).

    *config* defaults to :func:`load_config`.
    """
    if config is None:
        config = load_config()

    global _pool
    if _pool is not None:
        raw_conn = _pool.getconn()
    else:
        import psycopg2
        raw_conn = psycopg2.connect(
            host=config['DB_HOST'],
            user=config['DB_USER'],
            dbname=config['DB_NAME'],
            password=config['DB_PASSWORD'],
        )

    from pgvector.psycopg2 import register_vector
    register_vector(raw_conn)

    return _PooledConnection(raw_conn, _pool)


def get_embedding(text, dims=1024, api_key=None):
    """Generate a 1024-dim embedding via NVIDIA API.

    Returns ``None`` on failure (API error, network issue, …).
    """
    if api_key is None:
        api_key = os.getenv("NVIDIA_API_KEY")
    try:
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
    except Exception:
        return None
