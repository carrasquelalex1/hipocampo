"""Automatic model failover for Hipocampo.

When a configured model fails (410 Gone, 404 Not Found, EOL, etc.),
scans all available providers for a working alternative and persists
the choice for future sessions.

Providers (from environment variables):
  - NVIDIA NIM: embeddings + LLM (NVIDIA_API_KEY)
  - SambaNova: LLM only (SAMBANOVA_API_KEY)
  - Alibaba (Qwen): LLM only (ALIBABA_API_KEY)
"""

import json
import logging
import os
import time
from pathlib import Path

from openai import OpenAI

logger = logging.getLogger("hipocampo.failover")

CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / ".model_failover.json"
RESCAN_COOLDOWN = 300  # seconds between scans

# ─── PROVIDER REGISTRY ──────────────────────────────────────────────────────

PROVIDERS = {
    "nvidia": {
        "base_url": "https://integrate.api.nvidia.com/v1",
        "api_key_env": "NVIDIA_API_KEY",
        "types": ["embedding", "llm"],
    },
    "sambanova": {
        "base_url": "https://api.sambanova.ai/v1",
        "api_key_env": "SAMBANOVA_API_KEY",
        "types": ["llm"],
    },
    "alibaba": {
        "base_url": "https://token-plan.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1",
        "api_key_env": "ALIBABA_API_KEY",
        "types": ["llm"],
    },
}


def _get_provider_key(prov: dict) -> str:
    """Get API key from environment variable."""
    env_name = prov.get("api_key_env", "")
    return os.getenv(env_name, "")


# Preferred embedding models (ordered by reliability)
EMBED_PREFERENCE = [
    "nvidia/llama-nemotron-embed-vl-1b-v2",
    "nvidia/nv-embedqa-mistral-7b-v2",
    "nvidia/nv-embedqa-e5-v5",
    "nvidia/nemotron-3-embed-1b",
]

# Preferred LLM models per provider (ordered by capability)
LLM_PREFERENCE = {
    "nvidia": [
        "nvidia/nemotron-3-super-120b-a12b",
        "nvidia/nemotron-4-340b-instruct",
        "meta/llama-3.3-70b-instruct",
        "meta/llama-3.1-8b-instruct",
    ],
    "sambanova": [
        "Meta-Llama-3.1-8B-Instruct",
        "Meta-Llama-3.1-70B-Instruct",
        "DeepSeek-V3-0324",
        "QwQ-32B",
    ],
    "alibaba": [
        "qwen3-coder-plus",
        "qwen3-235b-a22b",
        "qwen3-30b-a3b",
        "qwen3-8b",
    ],
}

# Non-chat models to exclude from probing
_BANNED_PATTERNS = [
    "diffusion",
    "guard",
    "reward",
    "vision",
    "canvas",
    "stable-diffusion",
    "sdxl",
    "aura",
    "parakeet",
    "cattraction",
    "kosmos",
    "neva",
    "vila",
    "paligemma",
]


def is_model_error(e: Exception) -> bool:
    """Returns True only for model/EOL errors (not auth, rate-limit, network)."""
    msg = str(e).lower()
    code = getattr(e, "code", None) or getattr(e, "status_code", None)
    if isinstance(code, int):
        if code in (401, 403):
            return False
        if code == 429:
            return False
        if code in (404, 410):
            return True
    if any(
        kw in msg
        for kw in ("410", "404", "eol", "not found", "deprecated", "does not exist", "not supported", "decommissioned")
    ):
        return True
    if "rate" in msg or "limit" in msg or "429" in msg or "timeout" in msg:
        return False
    return False


def _list_nvidia_models(api_key: str) -> dict:
    """Get available models from NVIDIA NIM /models endpoint."""
    import httpx

    try:
        resp = httpx.get(
            "https://integrate.api.nvidia.com/v1/models",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        models = {}
        for m in data.get("data", []):
            mid = m.get("id", "")
            if not mid or mid.startswith("nvidia/"):
                continue
            if any(b in mid.lower() for b in _BANNED_PATTERNS):
                continue
            models[mid] = mid
        return models
    except Exception as e:
        logger.warning("NVIDIA model list failed: %s", e)
        return {}


def _load_config() -> dict:
    """Load persisted failover config."""
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text())
        except Exception:
            pass
    return {}


def _save_config(cfg: dict) -> None:
    """Persist failover config."""
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2))


def _is_cooldown() -> bool:
    """Check if we're still in cooldown after a recent scan."""
    cfg = _load_config()
    last_scan = cfg.get("last_scan_ts", 0)
    return (time.time() - last_scan) < RESCAN_COOLDOWN


def _probe_embed(model: str, api_key: str, base_url: str, dims: int) -> bool:
    """Test an embedding model: correct dims + non-empty result."""
    try:
        client = OpenAI(api_key=api_key, base_url=base_url)
        resp = client.embeddings.create(model=model, input="test", dimensions=dims)
        vec = resp.data[0].embedding
        return len(vec) == dims
    except Exception:
        return False


def _probe_llm(model: str, api_key: str, base_url: str) -> bool:
    """Test an LLM: returns non-empty text (>= 2 chars, no diffusion garbage)."""
    try:
        client = OpenAI(api_key=api_key, base_url=base_url)
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "Say exactly: hello"}],
            max_tokens=10,
        )
        text = (resp.choices[0].message.content or "").strip()
        return len(text) >= 2 and "diffusion" not in text.lower()
    except Exception:
        return False


def find_working_llm(api_key: str, exclude: str = "") -> str | None:
    """Scan all providers for a working LLM. Returns model ID (bare for non-NVIDIA)."""
    nvidia_models = _list_nvidia_models(api_key)
    for pref in LLM_PREFERENCE["nvidia"]:
        bare = pref.split("/", 1)[-1] if "/" in pref else pref
        if bare == exclude or pref == exclude:
            continue
        if bare not in nvidia_models and pref not in nvidia_models:
            continue
        if _probe_llm(pref, api_key, PROVIDERS["nvidia"]["base_url"]):
            return pref
    for prov_name in ("sambanova", "alibaba"):
        prov = PROVIDERS[prov_name]
        key = _get_provider_key(prov)
        if not key:
            continue
        for model in LLM_PREFERENCE.get(prov_name, []):
            if model == exclude:
                continue
            if _probe_llm(model, key, prov["base_url"]):
                return model
    return None


def find_working_embedding(api_key: str, dims: int = 1024, exclude: str = "") -> str | None:
    """Scan providers for a working embedding model. Only NVIDIA has embed models."""
    nvidia_models = _list_nvidia_models(api_key)
    for pref in EMBED_PREFERENCE:
        bare = pref.split("/", 1)[-1] if "/" in pref else pref
        if bare == exclude or pref == exclude:
            continue
        if bare not in nvidia_models and pref not in nvidia_models:
            continue
        full_id = f"nvidia/{bare}" if "/" not in pref else pref
        if _probe_embed(full_id, api_key, PROVIDERS["nvidia"]["base_url"], dims):
            return full_id
    return None


def get_embedding_with_failover(text: str, dims: int = 1024, api_key: str | None = None) -> list | None:
    """Try current embedding model; on failure, scan for a working one."""
    from hipocampo.db import _cached_embedding

    cfg = _load_config()
    current_model = cfg.get("embedding_model", "nvidia/llama-nemotron-embed-vl-1b-v2")

    if api_key is None:
        api_key = os.getenv("NVIDIA_API_KEY", "")
    if not api_key:
        return None

    try:
        return _cached_embedding(text, api_key, current_model)
    except Exception as e:
        if not is_model_error(e):
            raise
        logger.warning("Embedding model %s failed: %s — scanning alternatives", current_model, e)

    if _is_cooldown():
        logger.info("Cooldown active — skipping scan")
        return None

    new_model = find_working_embedding(api_key, dims, exclude=current_model)
    if new_model:
        cfg["embedding_model"] = new_model
        cfg["last_scan_ts"] = time.time()
        _save_config(cfg)
        logger.info("Failover: switched embedding to %s", new_model)
        return _cached_embedding(text, api_key, new_model)

    cfg["last_scan_ts"] = time.time()
    _save_config(cfg)
    return None


def get_llm_with_failover(
    prompt: str,
    api_key: str | None = None,
    max_tokens: int = 1024,
) -> tuple[str, str, str] | None:
    """Try current LLM; on failure, scan for a working one.

    Returns (text, model_id, provider_name) or None.
    """
    cfg = _load_config()
    current_model = cfg.get("llm_model", "nvidia/nemotron-3-super-120b-a12b")
    current_provider = cfg.get("llm_provider", "nvidia")

    if api_key is None:
        api_key = os.getenv("NVIDIA_API_KEY", "")
    if not api_key:
        return None

    try:
        prov = PROVIDERS[current_provider]
        if current_provider == "nvidia":
            key = api_key
        else:
            key = _get_provider_key(prov)
        if not key:
            raise ValueError("No API key for provider")
        client = OpenAI(api_key=key, base_url=prov["base_url"])
        resp = client.chat.completions.create(
            model=current_model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
        )
        text = (resp.choices[0].message.content or "").strip()
        if len(text) >= 2:
            return text, current_model, current_provider
    except Exception as e:
        if not is_model_error(e):
            raise
        logger.warning("LLM %s failed: %s — scanning alternatives", current_model, e)

    if _is_cooldown():
        logger.info("Cooldown active — skipping LLM scan")
        return None

    new_model = find_working_llm(api_key, exclude=current_model)
    if new_model:
        if "/" in new_model and new_model.startswith("nvidia/"):
            new_provider = "nvidia"
        else:
            new_provider = "sambanova" if new_model in LLM_PREFERENCE.get("sambanova", []) else "alibaba"
        cfg["llm_model"] = new_model
        cfg["llm_provider"] = new_provider
        cfg["last_scan_ts"] = time.time()
        _save_config(cfg)
        logger.info("Failover: switched LLM to %s (%s)", new_model, new_provider)
        prov = PROVIDERS[new_provider]
        key = api_key if new_provider == "nvidia" else _get_provider_key(prov)
        client = OpenAI(api_key=key, base_url=prov["base_url"])
        resp = client.chat.completions.create(
            model=new_model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
        )
        text = (resp.choices[0].message.content or "").strip()
        return text, new_model, new_provider

    cfg["last_scan_ts"] = time.time()
    _save_config(cfg)
    return None


def get_llm_client(provider: str | None = None) -> tuple[OpenAI, str, str]:
    """Get OpenAI client for the active LLM provider.

    Returns (client, model_id, provider_name).
    """
    cfg = _load_config()
    if provider is None:
        provider = cfg.get("llm_provider", "nvidia")
    prov = PROVIDERS[provider]
    if provider == "nvidia":
        key = os.getenv("NVIDIA_API_KEY", "")
    else:
        key = _get_provider_key(prov)
    model = cfg.get("llm_model", "nvidia/nemotron-3-super-120b-a12b")
    client = OpenAI(api_key=key, base_url=prov["base_url"])
    return client, model, provider


def get_active_embed_model() -> str:
    """Return the currently active embedding model ID."""
    cfg = _load_config()
    return cfg.get("embedding_model", "nvidia/llama-nemotron-embed-vl-1b-v2")


def get_active_llm_model() -> str:
    """Return the currently active LLM model ID."""
    cfg = _load_config()
    return cfg.get("llm_model", "nvidia/nemotron-3-super-120b-a12b")
