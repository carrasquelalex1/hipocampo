"""Utilidades de texto para Hipocampo (resumen, chunks y pasajes).

Funciones puras y deterministas: no tocan la BD ni llaman modelos. Se usan
tanto en el path interactivo (save/search) como en los backfills.
"""

from __future__ import annotations

import re

_WS_RE = re.compile(r"[ \t\r\f\v]+")
_MULTI_NL_RE = re.compile(r"\n{3,}")
_SENTENCE_RE = re.compile(r"(?<=[.!?¡¿])\s+")


def normalizar_espacios(texto: str) -> str:
    """Colapsa espacios horizontales y deja como máximo un salto doble."""
    if not texto:
        return ""
    t = texto.replace("\r\n", "\n").replace("\r", "\n")
    t = _WS_RE.sub(" ", t)
    t = _MULTI_NL_RE.sub("\n\n", t)
    return t.strip()


def resumir_contenido(texto: str, max_chars: int = 600) -> str:
    """Resumen extractivo barato: título/primer párrafo/frases iniciales.

    No pretende ser un resumen semántico: sirve para que la búsqueda tenga una
    vista corta y estable de recuerdos largos. Para contenido corto devuelve el
    texto normalizado completo.
    """
    t = normalizar_espacios(texto)
    if not t:
        return ""
    if len(t) <= max_chars:
        return t

    # Primer bloque no vacío (párrafo o línea de título).
    bloques = [b.strip() for b in t.split("\n\n") if b.strip()]
    if not bloques:
        return t[:max_chars].rstrip()

    partes: list[str] = []
    usados = 0
    for bloque in bloques:
        if usados and usados + len(bloque) + 1 > max_chars:
            break
        if len(bloque) > max_chars - usados:
            # Recorta por frases dentro del bloque.
            for frase in _SENTENCE_RE.split(bloque):
                if usados + len(frase) + 1 > max_chars:
                    break
                partes.append(frase.strip())
                usados += len(frase) + 1
            break
        partes.append(bloque)
        usados += len(bloque) + 1
        if usados >= max_chars:
            break

    resumen = " ".join(p for p in partes if p).strip()
    if not resumen:
        resumen = t[:max_chars].rstrip()
    if len(resumen) > max_chars:
        resumen = resumen[: max_chars - 1].rstrip() + "…"
    return resumen


def _partir_por_frases(bloque: str, max_chars: int) -> list[str]:
    """Parte un bloque largo por frases y, si aún sobra, por corte duro."""
    if len(bloque) <= max_chars:
        return [bloque]
    piezas: list[str] = []
    actual = ""
    for frase in _SENTENCE_RE.split(bloque):
        frase = frase.strip()
        if not frase:
            continue
        if len(frase) > max_chars:
            if actual:
                piezas.append(actual.strip())
                actual = ""
            for i in range(0, len(frase), max_chars):
                piezas.append(frase[i : i + max_chars].strip())
            continue
        if actual and len(actual) + 1 + len(frase) > max_chars:
            piezas.append(actual.strip())
            actual = frase
        else:
            actual = f"{actual} {frase}".strip()
    if actual:
        piezas.append(actual.strip())
    return [p for p in piezas if p]


def dividir_en_chunks(
    texto: str,
    max_chars: int = 1800,
    overlap: int = 180,
    min_chars: int = 200,
) -> list[dict]:
    """Divide un recuerdo largo en chunks con solapamiento.

    Devuelve ``[{"index": 0, "contenido": "..."}]``. Los chunks cortos se
    fusionan con el anterior para no generar fragmentos inútiles. El
    solapamiento se toma del final del chunk anterior (texto literal), lo que
    ayuda a que una frase que cae en el corte siga siendo recuperable.
    """
    t = normalizar_espacios(texto)
    if not t:
        return []
    if len(t) <= max_chars:
        return [{"index": 0, "contenido": t}]

    max_chars = max(400, int(max_chars))
    overlap = max(0, min(int(overlap), max_chars // 2))

    piezas: list[str] = []
    for bloque in [b.strip() for b in t.split("\n\n") if b.strip()]:
        piezas.extend(_partir_por_frases(bloque, max_chars))

    # Fusiona piezas pequeñas con la anterior.
    fusionadas: list[str] = []
    for pieza in piezas:
        if fusionadas and len(pieza) < min_chars and len(fusionadas[-1]) + len(pieza) + 2 <= max_chars:
            fusionadas[-1] = f"{fusionadas[-1]}\n\n{pieza}"
        else:
            fusionadas.append(pieza)

    chunks: list[dict] = []
    anterior = ""
    for i, pieza in enumerate(fusionadas):
        contenido = pieza
        if anterior and overlap:
            cola = anterior[-overlap:]
            # Evita duplicar si la pieza ya empieza con esa cola.
            if not contenido.startswith(cola):
                contenido = f"{cola}\n{contenido}"
        chunks.append({"index": len(chunks), "contenido": contenido})
        anterior = pieza
    return chunks


def mejor_pasaje(texto: str, terminos: list[str], ventana: int = 700) -> tuple[float, str]:
    """Devuelve (cobertura, pasaje) del fragmento con más términos de la query.

    ``cobertura`` es la fracción de términos presentes (0..1). Se usa como
    señal léxica para recuerdos largos: un término enterrado en el medio de
    50k caracteres sigue contando aunque el vector completo lo diluya.
    """
    t = normalizar_espacios(texto)
    terms = [x.lower() for x in terminos if x and len(x) >= 2]
    if not t or not terms:
        return 0.0, t[:ventana]
    low = t.lower()
    if len(low) <= ventana:
        presentes = sum(1 for x in terms if x in low)
        return presentes / len(terms), t

    # Ventanas por párrafos, con un paso que garantiza cobertura.
    bloques = [b.strip() for b in t.split("\n\n") if b.strip()]
    candidatos: list[str] = []
    actual = ""
    for b in bloques:
        if len(actual) + len(b) + 2 <= ventana:
            actual = f"{actual}\n\n{b}".strip()
        else:
            if actual:
                candidatos.append(actual)
            if len(b) <= ventana:
                actual = b
            else:
                for i in range(0, len(b), max(1, ventana - 100)):
                    candidatos.append(b[i : i + ventana])
                actual = ""
    if actual:
        candidatos.append(actual)
    if not candidatos:
        candidatos = [t[i : i + ventana] for i in range(0, len(t), max(1, ventana - 100))]

    mejor_c = -1.0
    mejor_p = t[:ventana]
    for cand in candidatos:
        cl = cand.lower()
        presentes = sum(1 for x in terms if x in cl)
        # Desempata por densidad (términos por carácter) y por posición inicial.
        cobertura = presentes / len(terms)
        if cobertura > mejor_c:
            mejor_c = cobertura
            mejor_p = cand
    return max(0.0, mejor_c), mejor_p
