"""Compress retrieved memories using a hybrid approach (extractive + LLM).

Provides the backend for the ``compress_hipocampo`` MCP tool.
"""

import os
import sys
import re
import logging
from collections import Counter

import openai

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from hipocampo.db import load_config

logger = logging.getLogger(__name__)
config = load_config()

NVIDIA_BASE = "https://integrate.api.nvidia.com/v1"
MODEL = "nvidia/llama-3.1-nemotron-70b-instruct"


def _extractive_summarize(text: str, target_sentences: int = 5) -> str:
    """Simple extractive compression: select most relevant sentences by keyword scoring."""
    sentences = re.split(r"(?<=[.!?])\s+", text)
    if len(sentences) <= target_sentences:
        return text

    words = re.findall(r"\w+", text.lower())
    freq = Counter(words)
    scored = []
    for s in sentences:
        score = sum(freq.get(w, 0) for w in re.findall(r"\w+", s.lower()))
        scored.append((score / max(len(s.split()), 1), s))
    scored.sort(key=lambda x: x[0], reverse=True)
    top = [s for _, s in scored[:target_sentences]]
    return " ".join(top)


def _llm_summarize(text: str, target_tokens: int = 500) -> str | None:
    """Compress via NVIDIA NIM. Returns None on transient API errors."""
    api_key = config.get("NVIDIA_API_KEY") or os.getenv("NVIDIA_API_KEY")
    if not api_key:
        logger.warning("NVIDIA_API_KEY no configurada — fallback extractive")
        return None

    client = openai.OpenAI(base_url=NVIDIA_BASE, api_key=api_key)
    try:
        resp = client.chat.completions.create(
            model=MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Eres un compresor de texto. Conserva nombres propios, cifras, "
                        "fechas, relaciones causales y tecnicismos. Omite redundancias, "
                        "adjetivos y ejemplos secundarios. Responde únicamente con el "
                        "texto comprimido, sin introducción ni explicación."
                    ),
                },
                {"role": "user", "content": f"Comprime manteniendo precisión técnica:\n\n{text}"},
            ],
            max_tokens=target_tokens,
            temperature=0.1,
        )
        return resp.choices[0].message.content.strip()
    except openai.RateLimitError:
        logger.warning("NVIDIA API rate limit — fallback extractive")
        return None
    except openai.APITimeoutError:
        logger.warning("NVIDIA API timeout — fallback extractive")
        return None
    except openai.APIConnectionError:
        logger.warning("NVIDIA API connection error — fallback extractive")
        return None
    except openai.APIStatusError as e:
        logger.warning("NVIDIA API status error %s — fallback extractive", e)
        return None
    except Exception as e:
        logger.warning("Unexpected error in LLM summarize: %s — fallback extractive", e)
        return None


def compress_memories(query: str, k: int = 5, method: str = "hybrid", target_token: int = -1) -> str:
    """Search Hipocampo and return a compressed summary.

    Uses extractive compression as universal fallback.
    """
    import hipocampo_search as _search

    raw = _search.search(query)
    if not raw or raw.startswith("❌"):
        return raw or "No se encontraron resultados."

    if method == "extractive":
        compressed = _extractive_summarize(raw)
    elif method == "llm":
        compressed = _llm_summarize(raw)
        if compressed is None:
            compressed = _extractive_summarize(raw)
    else:
        compressed = _llm_summarize(raw)
        if compressed is None:
            compressed = _extractive_summarize(raw)

    stats = (
        f"\n---\nCompresión: original {len(raw)} chars → {len(compressed)} chars "
        f"({method}, ratio {len(compressed) / max(len(raw), 1):.0%})"
    )
    return compressed + stats
