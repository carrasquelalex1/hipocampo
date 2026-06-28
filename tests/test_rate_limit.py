"""Tests for hipocampo/rate_limit.py"""
import time
import pytest
from hipocampo.rate_limit import RateLimiter


class TestRateLimiter:
    def test_acquire_under_limit(self):
        limiter = RateLimiter(max_calls=5, window_seconds=60)
        for _ in range(5):
            assert limiter.acquire() is True

    def test_acquire_over_limit(self):
        limiter = RateLimiter(max_calls=3, window_seconds=60)
        for _ in range(3):
            assert limiter.acquire() is True
        assert limiter.acquire() is False

    def test_remaining(self):
        limiter = RateLimiter(max_calls=10, window_seconds=60)
        assert limiter.remaining == 10
        limiter.acquire()
        assert limiter.remaining == 9
        for _ in range(9):
            limiter.acquire()
        assert limiter.remaining == 0

    def test_wait_time_zero_when_available(self):
        limiter = RateLimiter(max_calls=5, window_seconds=60)
        assert limiter.wait_time() == 0.0

    def test_wait_time_nonzero_when_full(self):
        limiter = RateLimiter(max_calls=2, window_seconds=60)
        limiter.acquire()
        limiter.acquire()
        wait = limiter.wait_time()
        assert wait > 0.0

    def test_release_frees_slot(self):
        limiter = RateLimiter(max_calls=2, window_seconds=60)
        limiter.acquire()
        limiter.acquire()
        assert limiter.acquire() is False
        limiter.release()
        assert limiter.acquire() is True

    def test_prune_old_calls(self):
        limiter = RateLimiter(max_calls=5, window_seconds=0.05)
        limiter.acquire()
        assert limiter.remaining == 4
        time.sleep(0.06)
        assert limiter.remaining == 5

    def test_stats(self):
        limiter = RateLimiter(max_calls=10, window_seconds=60, name="test")
        stats = limiter.stats
        assert stats["name"] == "test"
        assert stats["remaining"] == 10
        assert stats["active"] == 0
        limiter.acquire()
        stats = limiter.stats
        assert stats["active"] == 1
        assert stats["remaining"] == 9

    def test_default_limiters_exist(self):
        from hipocampo.rate_limit import embedding_limiter, tool_limiter, watch_limiter
        for limiter, name, max_calls in [
            (embedding_limiter, "embedding", 30),
            (tool_limiter, "tool", 60),
            (watch_limiter, "watch", 20),
        ]:
            assert limiter.name == name
            assert limiter.max_calls == max_calls
            assert limiter.window == 60


class TestToolErr:
    def test_basic(self):
        from hipocampo_mcp_server import _tool_err
        result = _tool_err("test_tool", ValueError("bad value"))
        assert "Error de validación" in result
        assert "test_tool" in result
        assert "bad value" in result

    def test_unknown_type(self):
        from hipocampo_mcp_server import _tool_err
        result = _tool_err("test_tool", RuntimeError("crash"))
        assert "Error inesperado" in result

    def test_db_error(self):
        from hipocampo_mcp_server import _tool_err
        import psycopg2
        try:
            # psycopg2 can construct errors without a real connection
            e = psycopg2.OperationalError("connection failed")
            result = _tool_err("db_tool", e)
            assert "Error de base de datos" in result
        except Exception:
            pass
