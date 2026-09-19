#!/usr/bin/env python3
"""typesafe_client.py — Cliente mínimo para la API TypeSafe (System One / Jev).

Convierte decisiones semánticas del Hipocampo (¿contradicción? ¿mismo hecho?)
en preguntas tipadas con probabilidad calibrada. Integración OPCIONAL:

    HIPOCAMPO_TYPESAFE=1            # activa (p. ej. en ~/.hipocampo/.env)
    TYPESAFE_API_KEY=...            # o archivo de key (recomendado)

Variables de entorno:
    TYPESAFE_API_KEY     API key (si falta, se lee el archivo)
    TYPESAFE_KEY_FILE    ruta del archivo con la key
                         (default ~/.config/typesafe/api_key)
    TYPESAFE_API_URL     endpoint (default https://api.typesafe.ai/v1/systemone)
    TYPESAFE_MODEL       modelo (default jev-latest)
    TYPESAFE_TIMEOUT     timeout en segundos (default 10)
    HIPOCAMPO_TYPESAFE   "1"/"true"/"yes"/"on" para activar

Diseño: nunca lanza excepciones de cara al llamador. Si la API falla, no hay
key o la integración está apagada, devuelve None y el llamador usa su método
local (embeddings) como fallback.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from pathlib import Path

logger = logging.getLogger("typesafe_client")

API_URL = os.environ.get("TYPESAFE_API_URL", "https://api.typesafe.ai/v1/systemone")
MODEL = os.environ.get("TYPESAFE_MODEL", "jev-latest")
DEFAULT_KEY_FILE = "~/.config/typesafe/api_key"
DEFAULT_TIMEOUT = 10.0
UMBRAL_CONTRADICCION = 0.7
MIN_CONF_MISMO_HECHO = 0.6
MAX_TEXTO = 1500


def _flag(valor) -> bool:
    return str(valor).strip().lower() in {"1", "true", "yes", "on"}


def _get_key() -> str | None:
    key = os.environ.get("TYPESAFE_API_KEY", "").strip()
    if key:
        return key
    ruta = Path(os.path.expanduser(os.environ.get("TYPESAFE_KEY_FILE", DEFAULT_KEY_FILE)))
    try:
        if ruta.is_file():
            key = ruta.read_text().strip()
            return key or None
    except OSError:
        pass
    return None


def enabled() -> bool:
    """True si la integración está activada y hay key disponible."""
    return _flag(os.environ.get("HIPOCAMPO_TYPESAFE", "")) and _get_key() is not None


def ask(state: str, questions: dict, timeout: float | None = None) -> dict | None:
    """POST /v1/systemone. Devuelve el dict de respuestas o None si falla."""
    key = _get_key()
    if not key:
        return None
    if timeout is None:
        try:
            timeout = float(os.environ.get("TYPESAFE_TIMEOUT", DEFAULT_TIMEOUT))
        except ValueError:
            timeout = DEFAULT_TIMEOUT
    cuerpo = json.dumps({"state": state, "model": MODEL, "questions": questions}).encode("utf-8")
    req = urllib.request.Request(
        API_URL,
        data=cuerpo,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data.get("answers") or {}
    except urllib.error.HTTPError as e:
        detalle = e.read().decode(errors="replace")[:200]
        logger.warning("TypeSafe HTTP %s: %s", e.code, detalle)
    except Exception as e:
        logger.warning("TypeSafe no disponible: %s", e)
    return None


def contradicciones_batch(
    nuevo: str, candidatos: list[tuple[int, str]], umbral: float | None = None
) -> dict[int, float] | None:
    """Evalúa si cada candidato contradice al hecho nuevo, en UNA sola llamada.

    Args:
        nuevo: contenido del recuerdo recién guardado.
        candidatos: [(id, texto), ...] recuerdos existentes a evaluar.
        umbral: probabilidad mínima (noul) para reportar contradicción.

    Returns:
        {id: noul} solo con los candidatos que superan el umbral,
        {} si ninguno, o None si la API falló (usar fallback local).
    """
    if not candidatos:
        return {}
    umbral = UMBRAL_CONTRADICCION if umbral is None else umbral

    bloques = [f"HECHO NUEVO:\n{nuevo[:MAX_TEXTO]}"]
    preguntas: dict = {}
    for cid, texto in candidatos:
        bloques.append(f"[C{cid}] {texto[:MAX_TEXTO]}")
        preguntas[f"c{cid}"] = {
            "type": "noul",
            "instructions": (
                f"El hecho [C{cid}] contradice al HECHO NUEVO: no pueden ser "
                "verdaderos a la vez porque afirman lo contrario sobre lo mismo. "
                "Compartir tema o ser más específico NO es contradecir."
            ),
        }

    answers = ask("\n\n".join(bloques), preguntas)
    if answers is None:
        return None

    resultado: dict[int, float] = {}
    for cid, _texto in candidatos:
        ans = answers.get(f"c{cid}") or {}
        noul = ans.get("noul")
        if isinstance(noul, (int, float)):
            if noul >= umbral:
                resultado[int(cid)] = float(noul)
            else:
                logger.debug("TypeSafe: C%s sin contradicción (noul=%.3f)", cid, noul)
    return resultado


def relacion(a: str, b: str) -> dict | None:
    """¿Qué relación hay entre dos hechos? Choice: mismo / relacionado / distinto.

    Returns: {"choice", "confidence", "probabilities"} o None si falla.
    """
    state = f"HECHO A:\n{a[:MAX_TEXTO]}\n\nHECHO B:\n{b[:MAX_TEXTO]}"
    questions = {
        "relacion": {
            "type": "choice",
            "instructions": "¿Qué relación hay entre HECHO A y HECHO B?",
            "criteria": {
                "mismo": "Describen exactamente el mismo hecho o dato (fusionables)",
                "relacionado": "Tratan lo mismo pero aportan datos distintos (no fusionar)",
                "distinto": "No tienen relación sustantiva",
            },
        }
    }
    answers = ask(state, questions)
    if answers is None:
        return None
    ans = answers.get("relacion")
    if not ans or ans.get("choice") is None:
        return None
    return {
        "choice": ans.get("choice"),
        "confidence": ans.get("confidence"),
        "probabilities": ans.get("probabilities"),
    }


def mismo_hecho(a: str, b: str, min_conf: float | None = None) -> bool | None:
    """True si TypeSafe confirma que A y B son el mismo hecho (con confianza).

    Returns: True / False / None (sin veredicto → fallback local).
    """
    min_conf = MIN_CONF_MISMO_HECHO if min_conf is None else min_conf
    r = relacion(a, b)
    if r is None:
        return None
    if r["choice"] == "mismo" and (r.get("confidence") or 0) >= min_conf:
        return True
    return False
