#!/usr/bin/env python3
"""hipocampo_compress.py — Prompt compression for Hipocampo SSC output

Two-phase hybrid compression:
  Phase A — EXTRACTIVE: sentence-level keyword relevance (generic text)
  Phase B — LLM: summarization via NVIDIA NIM for technical/code content

No heavy ML dependencies. Reuses the existing NVIDIA API endpoint.
"""

import logging
import os
import re
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from hipocampo.db import load_config

import hipocampo_ssc_search as _ssc

logger = logging.getLogger(__name__)

# ─── HEURISTICS ──────────────────────────────────────────────────────────────

CODE_KEYWORDS = [
    "def ",
    "class ",
    "import ",
    "from ",
    "return ",
    "if __name__",
    "```",
    "SELECT ",
    "INSERT ",
    "CREATE ",
    "DELETE ",
    "UPDATE ",
    "function",
    "const ",
    "let ",
    "var ",
    "=>",
    "::",
    "->",
    "#include",
    "package ",
    "impl ",
    "trait ",
    "fn ",
    "public ",
    "private ",
    "static ",
    "void ",
    "int ",
    "str ",
]

TECHNICAL_KEYWORDS = [
    "proyecto",
    "codigo",
    "código",
    "api",
    "servidor",
    "docker",
    "python",
    "javascript",
    "typescript",
    "base de datos",
    "sql",
    "algoritmo",
    "implementacion",
    "implementación",
    "config",
    "despliegue",
    "deploy",
    "migracion",
    "migración",
]


def _is_technical(text: str) -> bool:
    """Detect if text is technical/code-heavy (needs LLM summarization)."""
    text_lower = text.lower()
    code_score = sum(2 for kw in CODE_KEYWORDS if kw.lower() in text_lower)
    tech_score = sum(1 for kw in TECHNICAL_KEYWORDS if kw.lower() in text_lower)
    return (code_score + tech_score) >= 3


# ─── PHASE A: EXTRACTIVE COMPRESSION ────────────────────────────────────────


def _extractive_compress(text: str, query: str, ratio: float = 0.5) -> str:
    """Keep only sentences with highest keyword overlap with query.

    Args:
        text: Input text.
        query: User query (keywords to preserve).
        ratio: Target ratio (0.0-1.0). Default 0.5 = keep 50% of sentences.
    """
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    if not sentences:
        return ""

    query_tokens = set(re.findall(r"\w+", query.lower()))
    if not query_tokens:
        # No query tokens = keep first N sentences
        keep = max(1, int(len(sentences) * ratio))
        return " ".join(sentences[:keep])

    def _score(s: str) -> float:
        s_lower = s.lower()
        matches = sum(1 for t in query_tokens if t in s_lower)
        # Bonus for first sentence
        return matches + (0.5 if s is sentences[0] else 0.0)

    scored = [(s, _score(s)) for s in sentences]
    scored.sort(key=lambda x: x[1], reverse=True)

    keep = max(1, int(len(sentences) * ratio))
    kept = [s for s, _ in scored[:keep]]
    # Re-order to original position
    kept.sort(key=lambda s: sentences.index(s))
    return " ".join(kept)


# ─── PHASE B: LLM SUMMARIZATION (via NVIDIA NIM) ────────────────────────────


def _llm_summarize(text: str, query: str, api_key: str | None = None) -> str:
    """Summarize technical text using LLM with automatic failover.

    Tries the configured model first, then scans all providers (NVIDIA, SambaNova,
    Alibaba) for a working alternative if the primary fails.
    """
    if api_key is None:
        api_key = os.getenv("NVIDIA_API_KEY")
    if not api_key:
        logger.warning("NVIDIA_API_KEY not set — falling back to extractive compression")
        return _extractive_compress(text, query, ratio=0.4)

    prompt = (
        "Comprime el siguiente fragmento eliminando texto redundante. "
        "NO agregues código nuevo, NO generes ejemplos, NO expliques. "
        "Conserva TODO el código existente, nombres, sintaxis y datos concretos. "
        "Responde ÚNICAMENTE con el texto comprimido, sin introducción ni comentarios.\n\n"
        f"Contexto: {query}\n\n"
        f"Texto:\n{text}"
    )

    # Try failover-aware LLM call
    try:
        from hipocampo.model_failover import get_llm_with_failover

        result = get_llm_with_failover(prompt, api_key=api_key, max_tokens=min(1024, max(256, len(text) // 2)))
        if result:
            return result
    except ImportError:
        pass

    # Fallback: use configured model with correct provider client
    try:
        from hipocampo.model_failover import get_llm_client

        client, model = get_llm_client()

        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=min(1024, max(256, len(text) // 2)),
        )
        return resp.choices[0].message.content.strip()

    except Exception as e:
        logger.warning("LLM summarization failed: %s — falling back to extractive", e)
        return _extractive_compress(text, query, ratio=0.4)


# ─── MAIN COMPRESSION PIPELINE ──────────────────────────────────────────────


def compress_hipocampo(
    query: str,
    k: int = 5,
    method: str = "hybrid",
    target_token: int = -1,
    include_metadata: bool = False,
    budget_ratio: float = 1.0,
) -> dict:
    """Run SSC search + hybrid compression.

    Args:
        query: Natural language query.
        k: Number of memories to retrieve (default 5).
        method: "hybrid" (LLM for technical + extractive for generic),
                "extractive" (extractive only, fastest),
                "llm" (LLM summarization for all, highest quality).
        target_token: Target token count for compressed output (-1 = auto).
        include_metadata: Include metadata in output.

    Returns:
        dict with:
          - "compressed": str — the compressed context
          - "original_len": int — original total chars
          - "compressed_len": int — compressed total chars
          - "ratio": float — compression ratio (0-1)
          - "method": str — method used per memory
          - "memories": list[dict] — individual compressed memories (if include_metadata)
          - "error": str (if failed)
    """
    t0 = time.time()

    # 1. SSC Search
    try:
        results, modo, fase, elapsed = _ssc.ssc_search(query, umbral_minimo=5.0)
    except Exception as e:
        return {"error": f"SSC search failed: {e}"}

    if not results:
        return {
            "compressed": "",
            "original_len": 0,
            "compressed_len": 0,
            "ratio": 0.0,
            "memories": [],
            "method": "none",
        }

    # Auto-adjust k and target_token based on budget
    original_lens = [len(r.get("contenido", "")) for r in results]
    total_chars = sum(original_lens)
    est_tokens = total_chars / 4  # rough: ~4 chars per token

    if target_token <= 0:
        # Auto-estimate: 30% of total content, min 200, max 2000
        target_token = max(200, min(2000, int(est_tokens * 0.3 * budget_ratio)))

    # Shrink k if content would exceed budget
    max_chars_for_budget = target_token * 4
    running = 0
    adjusted_k = 0
    for length in original_lens:
        if running + length > max_chars_for_budget and adjusted_k >= 3:
            break
        running += length
        adjusted_k += 1
    k = min(k, max(adjusted_k, 1))

    # Take top-k
    results = results[:k]

    config = load_config()
    api_key = config.get("NVIDIA_API_KEY", "")

    compressed_memories = []
    original_total = 0
    compressed_total = 0

    for r in results:
        text = r.get("contenido", "")
        score = r.get("score", 0)
        original_total += len(text)

        if not text.strip():
            compressed_memories.append({"text": "", "method": "skip", "score": score})
            continue

        tech = _is_technical(text)

        # Decide compression method
        if method == "extractive":
            compressed = _extractive_compress(text, query)
            used_method = "extractive"
        elif method == "llm" or (method == "hybrid" and tech):
            compressed = _llm_summarize(text, query, api_key)
            used_method = "llm"
        else:
            compressed = _extractive_compress(text, query)
            used_method = "extractive"

        compressed_total += len(compressed)
        compressed_memories.append(
            {
                "text": compressed,
                "method": used_method,
                "score": score,
                "is_technical": tech,
            }
        )

    # Build final compressed context
    parts = []
    for i, m in enumerate(compressed_memories, 1):
        if m["text"]:
            parts.append(f"[{i}] {m['text']}")

    compressed_output = "\n\n".join(parts) if parts else ""

    result = {
        "compressed": compressed_output,
        "original_len": original_total,
        "compressed_len": compressed_total,
        "ratio": round(1 - (compressed_total / max(original_total, 1)), 3),
        "method": method,
        "total_latency_ms": int((time.time() - t0) * 1000),
        "ssc_phase": fase,
    }

    if include_metadata:
        result["memories"] = compressed_memories

    return result


# ─── CLI ─────────────────────────────────────────────────────────────────────


def _print_result(r: dict):
    if "error" in r:
        print(f"❌ {r['error']}")
        return

    print(f"{'=' * 60}")
    print("Hipocampo Compress v1.0 — Hybrid Prompt Compression")
    print(f'  Query: "{query}"')
    print(f"  Method: {r['method']}")
    print(f"  Original: {r['original_len']} chars")
    print(f"  Compressed: {r['compressed_len']} chars")
    print(f"  Compression ratio: {r['ratio'] * 100:.1f}%")
    print(f"  Latency: {r['total_latency_ms']}ms")
    print(f"{'=' * 60}")
    print()
    print(r["compressed"])
    print(f"\n{'=' * 60}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Compress Hipocampo memories")
    parser.add_argument("query", help="Search query")
    parser.add_argument("--k", type=int, default=5, help="Number of memories (default 5)")
    parser.add_argument(
        "--method",
        choices=["hybrid", "extractive", "llm"],
        default="hybrid",
        help="Compression method (default hybrid)",
    )
    parser.add_argument("--metadata", action="store_true", help="Show per-memory metadata")

    args = parser.parse_args()
    query = args.query

    result = compress_hipocampo(
        query=args.query,
        k=args.k,
        method=args.method,
        include_metadata=args.metadata,
    )
    _print_result(result)
