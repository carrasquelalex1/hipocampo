#!/usr/bin/env python3
"""hipocampo_scrub.py — Redacción de secretos antes de la salida HTTP a APIs externas.

El juicio semántico (TypeSafe Tier 1 / classifier.dev Tier 2) envía contenido de
recuerdos y candidatos a servicios de terceros. Este módulo reemplaza
credenciales y secretos detectables por ``[REDACTADO:<tipo>]`` antes de la
salida, en los únicos dos puntos por donde todo juicio sale al exterior:

    - ``typesafe_client.ask()``  (state + questions)
    - ``classifier_client._post()``  (inputs + instructions)

Diseño:
    - ``redactar(texto)`` -> ``(texto_redactado, n_redacciones)``. Nunca lanza.
    - ``redactar_estructura(obj)`` recorre dicts/listas/strings (bodies JSON).
    - Desactivable con ``HIPOCAMPO_SCRUB=0/false/no/off/disabled``.
    - No loguea contenido: solo el llamador reporta el CONTEO de redacciones.

Los patrones son deliberadamente conservadores (mejor sobre-redactar un
comentario que filtrar una credencial real a un tercero).
"""

from __future__ import annotations

import os
import re

__all__ = ["enabled", "redactar", "redactar_estructura"]


def _off(valor) -> bool:
    return str(valor).strip().lower() in {"0", "false", "no", "off", "disabled"}


def enabled() -> bool:
    """True salvo desactivación explícita (default: ACTIVO)."""
    return not _off(os.environ.get("HIPOCAMPO_SCRUB", "1"))


# Orden importa: patrones específicos antes que genéricos (sk-ant- antes de sk-).
_PATRONES: list[tuple[str, re.Pattern]] = [
    (
        "private_key",
        re.compile(r"-----\s*BEGIN[^-]{0,40}PRIVATE KEY-----[\s\S]*?-----\s*END[^-]{0,40}PRIVATE KEY-----"),
    ),
    ("anthropic_key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{16,}\b")),
    ("openai_key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("hf_token", re.compile(r"\bhf_[A-Za-z0-9]{24,}\b")),
    ("github_token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}\b")),
    ("aws_key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("slack_token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("nvapi_key", re.compile(r"\bnvapi-[A-Za-z0-9_=-]{20,}\b")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b")),
    ("bearer", re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{16,}")),
]

# Claves sensibles. "Fuertes": su valor SIN comillas se redacta hasta fin de
# línea (un secreto multi-palabra no debe quedar a medias).
_KV_CLAVES_FUERTES = r"(?:password|passwd|contraseña|token|api[_-]?key|apikey|secret|client[_-]?secret|access[_-]?key)"
_KV_CLAVES = r"(?:" + _KV_CLAVES_FUERTES + r"|clave|pass)"
_NEG = r"(?!\[REDACTADO)"

# 1) Valor entrecomillado (soporta espacios; cubre JSON "clave": "valor"): conserva comillas.
_KV_QUOTED = re.compile(rf"(?ix)\b{_KV_CLAVES}\b\s*['\"]?\s*[:=]\s*{_NEG}(?P<q>[\"']){_NEG}(?P<v>[^\"'\n]*)(?P=q)")
# 2) Valor sin comillas de clave fuerte: redacta hasta fin de línea.
_KV_FUERTE_LINEA = re.compile(rf"(?ixm)\b{_KV_CLAVES_FUERTES}\b\s*['\"]?\s*[:=]\s*{_NEG}(?P<v>[^\[\s'\"][^\n]*?)\s*$")
# 3) Valor sin comillas genérico: token simple.
_KV_TOKEN = re.compile(rf"(?ix)\b{_KV_CLAVES}\b\s*['\"]?\s*[:=]\s*{_NEG}(?P<v>[^\s'\";,]{{6,}})")

_KV_PATRONES = (_KV_QUOTED, _KV_FUERTE_LINEA, _KV_TOKEN)


def _redactar_kv(m: re.Match) -> str:
    """Reemplaza el valor de un par clave=sensible conservando el resto."""
    inicio = m.start("v") - m.start(0)
    fin = m.end("v") - m.start(0)
    return m.group(0)[:inicio] + "[REDACTADO:credencial]" + m.group(0)[fin:]


def redactar(texto: str) -> tuple[str, int]:
    """Redacta secretos en un texto. Devuelve (texto, n_redacciones). Nunca lanza."""
    if not isinstance(texto, str) or not texto or not enabled():
        return texto, 0
    n = 0
    try:
        for tipo, pat in _PATRONES:
            texto, k = pat.subn(f"[REDACTADO:{tipo}]", texto)
            n += k
        for pat_kv in _KV_PATRONES:
            texto, k = pat_kv.subn(_redactar_kv, texto)
            n += k
    except Exception:  # pragma: no cover — jamás romper el juicio por el scrub
        return texto, n
    return texto, n


def redactar_estructura(obj):
    """Aplica ``redactar`` recursivamente a dicts/listas/strings.

    Devuelve (estructura_nueva, n_redacciones). Otros tipos pasan intactos.
    """
    if not enabled():
        return obj, 0
    if isinstance(obj, str):
        return redactar(obj)
    if isinstance(obj, dict):
        total = 0
        nuevo: dict = {}
        for k, v in obj.items():
            nv, n = redactar_estructura(v)
            nuevo[k] = nv
            total += n
        return nuevo, total
    if isinstance(obj, (list, tuple)):
        total = 0
        nueva: list = []
        for v in obj:
            nv, n = redactar_estructura(v)
            nueva.append(nv)
            total += n
        return (nueva if isinstance(obj, list) else tuple(nueva)), total
    return obj, 0
