#!/usr/bin/env python3
"""hipocampo_semantic.py — Juicio semántico con dependencias inyectadas.

Extraído de hipocampo_mcp_server.py para que el server sea un cascarón
delgado: aquí vive la lógica (testeable sin BD ni red), allá solo los
wrappers que pasan los globales (_conn, get_embedding, _ts, _cl).

Cadena en ambas funciones: TypeSafe (Tier 1) → classifier.dev (Tier 2)
→ heurística local (Tier 3). Todo best-effort: cualquier fallo devuelve
el siguiente nivel, nunca excepciones al llamador.

Convenciones de inyección:
    conn_fn:  () -> conexión con .cursor() (paramstyle %s)
    embed_fn: (texto) -> list[float] | None
    ts / cl:  módulos con .enabled() y .contradicciones_batch / .mismo_hecho,
              o None si no están disponibles.
"""

from __future__ import annotations

import logging
import math as _m

logger = logging.getLogger("hipocampo_semantic")

CONTRADICTION_MARGIN = 0.05
SIM_MIN = 0.35
SIM_MAX = 0.70
UMBRAL_CONTRADICCION_DEFAULT = 0.7


def _via_batch(client, content, candidates) -> list[dict] | None:
    """Un POST batch vía un cliente semántico. None = sin veredicto."""
    pares = [(cid, ctext[:800]) for cid, ctext, _dist in candidates]
    nouls = client.contradicciones_batch(content, pares)
    if nouls is None:
        return None
    return [
        {
            "id": cand_id,
            "contenido": cand_content[:200],
            "sim_new_old": round(1.0 - cand_dist, 3),
            "sim_neg_old": round(noul, 3),
            "confidence": round(noul, 3),
        }
        for cand_id, cand_content, cand_dist in candidates
        if (noul := nouls.get(int(cand_id))) is not None
    ]


def detectar_contradicciones(
    content: str,
    new_emb: list,
    top_k: int = 5,
    max_probes: int | None = None,
    exclude_id: int | None = None,
    *,
    conn_fn,
    embed_fn,
    ts=None,
    cl=None,
) -> list[dict]:
    """Detecta contradicciones. Solo lee BD + APIs externas, nunca escribe."""
    ts_activo = ts is not None and ts.enabled()
    # Con juicio semántico la ventana se amplía a casi-duplicados (dist<0.35),
    # donde viven las contradicciones entre paráfrasis del mismo hecho.
    semantico = ts_activo or (cl is not None and cl.enabled())
    dist_min = 0.0 if semantico else SIM_MIN

    try:
        conn = conn_fn()
        cur = conn.cursor()
        excl_sql = " AND id != %s" if exclude_id is not None else ""
        params: list = [new_emb, new_emb, dist_min, SIM_MAX]
        if exclude_id is not None:
            params.append(exclude_id)
        params.append(top_k)
        cur.execute(
            f"""SELECT id, contenido,
                      (embedding <=> %s::vector(1024)) AS dist
                FROM memoria_vectorial
                WHERE embedding IS NOT NULL
                  AND (embedding <=> %s::vector(1024)) BETWEEN %s AND %s{excl_sql}
                ORDER BY dist ASC
                LIMIT %s""",
            tuple(params),
        )
        candidates = cur.fetchall()
        cur.close()
        conn.close()

        if not candidates:
            return []

        if max_probes is not None:
            candidates = candidates[:max_probes]

        if ts_activo:
            try:
                res = _via_batch(ts, content, candidates)
                if res is not None:
                    for d in res:
                        d["via"] = "typesafe"
                    return res
            except Exception as e:
                logger.warning("TypeSafe contradicciones falló (%s) — Tier 2 classifier", e)

        if cl is not None and cl.enabled():
            try:
                res = _via_batch(cl, content, candidates)
                if res is not None:
                    for d in res:
                        d["via"] = "classifier"
                    return res
            except Exception as e:
                logger.warning("classifier.dev contradicciones falló (%s) — fallback local", e)

            candidates = [c for c in candidates if SIM_MIN <= c[2] <= SIM_MAX]
            if not candidates:
                return []

        contradictions = []
        for cand_id, cand_content, cand_dist in candidates:
            cand_emb = embed_fn(cand_content[:2000])
            if cand_emb is None:
                continue
            neg_probe_text = f"AFIRMACIÓN: {cand_content[:300]} — ¿Esto es FALSO según: {content[:300]}?"
            neg_probe_emb = embed_fn(neg_probe_text[:2000])
            if neg_probe_emb is None:
                continue

            sim_new_old = 1.0 - cand_dist
            norm_a = _m.sqrt(sum(x * x for x in neg_probe_emb))
            norm_b = _m.sqrt(sum(x * x for x in cand_emb))
            if norm_a == 0 or norm_b == 0:
                continue
            sim_neg_old = sum(x * y for x, y in zip(neg_probe_emb, cand_emb)) / (norm_a * norm_b)

            if sim_neg_old > sim_new_old + CONTRADICTION_MARGIN:
                contradictions.append(
                    {
                        "id": cand_id,
                        "contenido": cand_content[:200],
                        "sim_new_old": round(sim_new_old, 3),
                        "sim_neg_old": round(sim_neg_old, 3),
                        "confidence": round(sim_neg_old - sim_new_old, 3),
                    }
                )

        return contradictions
    except Exception as e:
        logger.warning("Contradiction detection failed: %s", e)
        return []


def mismo_veredicto(content: str, dup_content: str, *, ts=None, cl=None):
    """Cadena mismo_hecho: True / False / None (sin veredicto → flujo normal)."""
    veredicto = None
    if ts is not None and ts.enabled():
        try:
            veredicto = ts.mismo_hecho(content, dup_content)
        except Exception as e:
            logger.warning("TypeSafe mismo_hecho falló (%s) — Tier 2 classifier", e)
            veredicto = None
    if veredicto is None and cl is not None and cl.enabled():
        try:
            veredicto = cl.mismo_hecho(content, dup_content)
        except Exception as e:
            logger.warning("classifier mismo_hecho falló (%s) — comportamiento original", e)
            veredicto = None
    return veredicto


def check_dedup_semantic(
    row_id: int,
    content: str,
    embedding: list,
    threshold: float = 0.9,
    *,
    conn_fn,
    ts=None,
    cl=None,
) -> int | None:
    """Dedup semántico best-effort. Solo lee BD + APIs, nunca escribe."""
    try:
        conn = conn_fn()
        cur = conn.cursor()
        cur.execute(
            """SELECT id, contenido FROM memoria_vectorial
               WHERE id != %s AND (embedding <=> %s::vector(1024)) < %s
               ORDER BY (embedding <=> %s::vector(1024))
               LIMIT 1""",
            (row_id, embedding, 1 - threshold, embedding),
        )
        row = cur.fetchone()
        cur.close()
        conn.close()
        if not row:
            return None
        dup_id, dup_content = row
        if mismo_veredicto(content, dup_content or "", ts=ts, cl=cl) is False:
            logger.info(
                "Dedup semántico: #%s y #%s no son el mismo hecho (semántico) — se omite la alerta",
                row_id,
                dup_id,
            )
            return None
        return dup_id
    except Exception as e:
        logger.warning("Dedup semántico bg falló: %s", e)
        return None
