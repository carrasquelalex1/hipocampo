"""Sliding-window rate limiter for MCP server operations.

Protects against runaway clients that could:
  - Saturate the NVIDIA API budget (embedding generation ≈ $/call)
  - Overload the free-tier PostgreSQL database
  - Degrade service for other concurrent users

Usage:
    from hipocampo.rate_limit import RateLimiter, embedding_limiter

    if not embedding_limiter.acquire():
        return "⏳ Demasiadas solicitudes. Intenta en N segundos."
"""
import time
import logging
import threading

logger = logging.getLogger(__name__)


class RateLimiter:
    """Thread-safe sliding-window rate limiter.

    Args:
        max_calls: Maximum number of calls allowed within the window.
        window_seconds: Length of the sliding window in seconds.
        name: Human-readable name for log messages.

    Example:
        limiter = RateLimiter(max_calls=30, window_seconds=60, name="embedding")
        if limiter.acquire():
            # do expensive operation
            pass
        else:
            wait = limiter.wait_time()
            # reject with "try again in {wait:.0f}s"
    """

    def __init__(self, max_calls: int, window_seconds: int = 60, name: str = ""):
        self.max_calls = max_calls
        self.window = window_seconds
        self.name = name
        self._calls: list[float] = []
        self._lock = threading.Lock()

    def _prune(self):
        now = time.monotonic()
        cutoff = now - self.window
        self._calls = [t for t in self._calls if t > cutoff]

    def acquire(self) -> bool:
        """Try to acquire a slot. Returns True if under the limit."""
        with self._lock:
            self._prune()
            if len(self._calls) < self.max_calls:
                self._calls.append(time.monotonic())
                return True
            return False

    def wait_time(self) -> float:
        """Seconds until the next slot frees up (0 if available now)."""
        with self._lock:
            self._prune()
            if len(self._calls) < self.max_calls:
                return 0.0
            return max(0.0, self._calls[0] + self.window - time.monotonic())

    def release(self):
        """Manually release a slot (removes the oldest entry)."""
        with self._lock:
            if self._calls:
                self._calls.pop(0)

    @property
    def remaining(self) -> int:
        """Number of available slots right now."""
        with self._lock:
            self._prune()
            return max(0, self.max_calls - len(self._calls))

    @property
    def stats(self) -> dict:
        """Current state for instrumentation."""
        with self._lock:
            self._prune()
            return {
                "name": self.name,
                "active": len(self._calls),
                "remaining": max(0, self.max_calls - len(self._calls)),
                "max_calls": self.max_calls,
                "window_seconds": self.window,
            }


# ─── DEFAULT LIMITERS ──────────────────────────────────────────────────────────

# Embedding generation calls the NVIDIA API (cost per token).
# Conservative: 30 embeddings/minute.
embedding_limiter = RateLimiter(max_calls=30, window_seconds=60, name="embedding")

# General MCP tool calls (DB queries, etc.).
# 60 tool calls/minute = ~1/second, safe for free-tier PostgreSQL.
tool_limiter = RateLimiter(max_calls=60, window_seconds=60, name="tool")

# Webhook POST requests to external URLs.
# Lower limit to avoid flooding third-party services.
watch_limiter = RateLimiter(max_calls=20, window_seconds=60, name="watch")
