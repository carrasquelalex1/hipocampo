#!/usr/bin/env python3
"""hipocampo_ssc_search.py — Sparse Selective Caching (SSC) v1.0

Inspirado en "Memory Caching: RNNs with Growing Memory" (Google, 2025).

Arquitectura SSC aplicada a Hipocampo:
  - Fase 1 — TAG ROUTER: Clasifica la consulta en dominios. Asigna pesos
              a cada tabla (memoria_vectorial / memory_items) según relevancia.
  - Fase 2 — PGVECTOR SPARSE: Búsqueda semántica en AMBAS tablas, pero
              limitando a top-K con corte temprano si hay alta confianza.
  - Fase 3 — GIN TRIGRAM: Si confianza baja, expande usando índices GIN.
  - Fase 4 — ILIKE FALLBACK: Solo si las fases anteriores no alcanzan el umbral.

Uso:
    python3 scripts/hipocampo_ssc_search.py "consulta" [umbral]
"""

import os
import json
import sys
import re
import math
import time
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from hipocampo.db import get_conn, get_embedding, load_config

config = load_config()

HYBRID_CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hipocampo_hybrid_config.json")

CONFIANZA_ALTA = 60.0
CONFIANZA_MEDIA = 35.0
SSC_TOP_K = 15
SSC_EF_SEARCH = 20  # perf: embedding LRU cache, SSC early exit, lower ef_search; fix: health check pgvector/PG17 compat, reset thresholds, cap tune bounds

PERFIL_KEYWORDS = [
    "nombre",
    "llama",
    "gusta",
    "gustan",
    "esposa",
    "hijo",
    "hija",
    "familia",
    "color",
    "edad",
    "vive",
    "prefiere",
    "favorito",
    "casado",
    "hermano",
    "madre",
    "padre",
    "trabaja",
    "estudia",
    "cumple",
    "años",
    "mascota",
    "tiene",
    "quiere",
    "sueña",
]
TECNICO_KEYWORDS = [
    "proyecto",
    "código",
    "codigo",
    "sistema",
    "servidor",
    "api",
    "bot",
    "mcp",
    "python",
    "docker",
    "linux",
    "base de datos",
    "postgres",
    "sql",
    "programa",
    "desarrollo",
    "config",
]


# get_embedding is imported from hipocampo.db


# ─── FASE 1: TAG ROUTER ──────────────────────────────────────────────────────


def tag_router(query):
    q = query.lower()
    tokens = set(re.findall(r"\w+", q))

    peso_perfil = sum(1 for kw in PERFIL_KEYWORDS if kw in q) / len(PERFIL_KEYWORDS)
    peso_tecnico = sum(1 for kw in TECNICO_KEYWORDS if kw in q) / len(TECNICO_KEYWORDS)

    peso_perfil = min(peso_perfil * 20, 1.0)
    peso_tecnico = min(peso_tecnico * 20, 1.0)

    return {
        "peso_perfil": peso_perfil,
        "peso_tecnico": peso_tecnico,
        "tokens": tokens,
        "modo": "perfil" if peso_perfil > peso_tecnico else "tecnico" if peso_tecnico > 0 else "mixto",
    }


# ─── FASE 2: PGVECTOR SPARSE (ambas tablas) ─────────────────────────────────


def ssc_vectorial(cur, query, router):
    """Búsqueda pgvector en AMBAS tablas. Sin filtro de tags."""
    query_embed = get_embedding(query[:3000])
    if query_embed is None:
        return [], 0.0

    max_score = 0.0
    todos = []

    # memoria_vectorial
    cur.execute(
        """
        SELECT id, contenido, metadatos::text, code_snippet,
                1 - (embedding <=> %s::vector(1024)) as similitud
        FROM memoria_vectorial
        WHERE embedding IS NOT NULL
        ORDER BY embedding <=> %s::vector(1024)
        LIMIT %s
    """,
        (query_embed, query_embed, SSC_TOP_K),
    )

    for row in cur.fetchall():
        score = round(float(row[4]) * 100, 1)
        max_score = max(max_score, score)
        meta = json.loads(row[2])
        todos.append(
            {
                "id": f"v{row[0]}",
                "contenido": row[1],
                "metadatos": meta,
                "code_snippet": row[3],
                "score": score,
                "method": "vectorial",
                "tabla": "memoria_vectorial",
            }
        )

    # memory_items (siempre, pero con boost si es perfil)
    cur.execute(
        """
        SELECT mi.id::text, mi.summary, mi.memory_type,
               mc.name as categoria,
                1 - (mi.embedding <=> %s::vector(1024)) as similitud
        FROM memory_items mi
        LEFT JOIN category_items ci ON ci.item_id = mi.id
        LEFT JOIN memory_categories mc ON mc.id = ci.category_id
        WHERE mi.embedding IS NOT NULL
        ORDER BY mi.embedding <=> %s::vector(1024)
        LIMIT %s
    """,
        (query_embed, query_embed, SSC_TOP_K),
    )

    for row in cur.fetchall():
        score_raw = float(row[4])
        profile_boost = 15 if (row[2] == "profile" and router["peso_perfil"] > 0.3) else 5
        score = round(min(100, (score_raw * 100) + profile_boost), 1)
        max_score = max(max_score, score)
        todos.append(
            {
                "id": f"p{row[0]}",
                "contenido": row[1],
                "metadatos": {"memory_type": row[2], "categoria": row[3]},
                "code_snippet": None,
                "score": score,
                "method": "vectorial",
                "tabla": "memory_items",
            }
        )

    return todos, max_score


# ─── FASE 3: GIN TRIGRAM EXPANSION ──────────────────────────────────────────


def ssc_trigram(cur, query, router):
    tokens = re.findall(r"\w+", query.lower().strip())
    if not tokens:
        return [], 0.0

    cur.execute("SET pg_trgm.similarity_threshold = 0.2")
    cur.execute(
        """
        SELECT id, contenido, metadatos::text, code_snippet,
               similarity(contenido, %s) AS trgm_sim
        FROM memoria_vectorial
        WHERE contenido %% %s
        ORDER BY trgm_sim DESC
        LIMIT 25
    """,
        (query, query),
    )

    max_score = 0.0
    todos = []
    total_terms = len(tokens)

    for row in cur.fetchall():
        content_lower = (row[1] or "").lower()
        match_count = sum(1 for t in tokens if t in content_lower)
        trgm_sim = float(row[4]) if row[4] is not None else 0.0
        score = round(min(100, (match_count / total_terms) * 60 + trgm_sim * 25 + 10), 1)
        max_score = max(max_score, score)
        meta = json.loads(row[2])
        todos.append(
            {
                "id": f"g{row[0]}",
                "contenido": row[1],
                "metadatos": meta,
                "code_snippet": row[3],
                "score": score,
                "method": "trigram",
                "tabla": "memoria_vectorial",
            }
        )

    return todos, max_score


# ─── FASE 4: ILIKE FALLBACK ──────────────────────────────────────────────────


def ssc_ilike(cur, query, router):
    tokens = re.findall(r"\w+", query.lower().strip())
    if not tokens:
        return [], 0.0

    patterns = ",".join([f"'%{t}%'" for t in tokens])
    cur.execute(f"""
        SELECT id, contenido, metadatos::text, code_snippet
        FROM memoria_vectorial
        WHERE contenido ILIKE ANY (ARRAY[{patterns}])
        ORDER BY LENGTH(contenido) ASC
        LIMIT 25
    """)

    max_score = 0.0
    todos = []
    total_terms = len(tokens)
    for row in cur.fetchall():
        content_lower = (row[1] or "").lower()
        match_count = sum(1 for t in tokens if t in content_lower)
        score = round(min(100, (match_count / total_terms) * 70 + 10), 1)
        max_score = max(max_score, score)
        meta = json.loads(row[2])
        todos.append(
            {
                "id": f"i{row[0]}",
                "contenido": row[1],
                "metadatos": meta,
                "code_snippet": row[3],
                "score": score,
                "method": "ilike",
                "tabla": "memoria_vectorial",
            }
        )

    return todos, max_score


def _cargar_lambda():
    try:
        with open(HYBRID_CONFIG_PATH) as f:
            return json.load(f).get("time_decay_lambda", 0.05)
    except (FileNotFoundError, json.JSONDecodeError):
        return 0.05


def _time_decay(dias, lmbda=None):
    if lmbda is None:
        lmbda = _cargar_lambda()
    if dias <= 7:
        return 1.0
    return max(0.2, math.exp(-lmbda * dias))


def _aplicar_decaimiento_ssc(resultados):
    hoy = date.today()
    lmbda = _cargar_lambda()
    for r in resultados:
        fecha_str = r.get("metadatos", {}).get("date", "")
        if fecha_str:
            try:
                partes = fecha_str.split("-")
                fecha = date(int(partes[0]), int(partes[1]), int(partes[2]))
                dias = (hoy - fecha).days
                decay = _time_decay(dias, lmbda)
                if decay < 1.0:
                    r["score"] = round(r["score"] * decay, 1)
                    r["time_decay"] = decay
            except (ValueError, IndexError):
                pass
    return resultados


# ─── FUSIÓN SSC ───────────────────────────────────────────────────────────────

_register_vector_cache = {}

def _ensure_vector_registration(conn):
    conn_id = id(conn)
    if conn_id not in _register_vector_cache:
        register_vector(conn)
        _register_vector_cache[conn_id] = True


def ssc_search(query, umbral_minimo=10.0):
    conn = get_conn()
    _ensure_vector_registration(conn)
    cur = conn.cursor()
    start = time.time()

    # HNSW: ef_search bajo = más rápido, menos preciso
    cur.execute(f"SET hnsw.ef_search = {SSC_EF_SEARCH}")

    router = tag_router(query)
    todos = {}
    confianza_max = 0.0
    fase = 2

    # Fase 2: pgvector en ambas tablas
    vec_results, confianza = ssc_vectorial(cur, query, router)
    confianza_max = max(confianza_max, confianza)
    for r in vec_results:
        todos[r["id"]] = r

    tags_msg = router["modo"].upper()

    # Fase 3: trigram si confianza baja O pocos resultados
    ya_tengo_buenos = len([r for r in todos.values() if r['score'] >= umbral_minimo]) >= 3
    if (confianza_max < CONFIANZA_ALTA or len(todos) < 3) and not ya_tengo_buenos:
        tri_results, confianza = ssc_trigram(cur, query, router)
        confianza_max = max(confianza_max, confianza)
        fase = 3
        for r in tri_results:
            if r["id"] not in todos:
                todos[r["id"]] = r

    ya_tengo_suficientes = len([r for r in todos.values() if r['score'] >= umbral_minimo]) >= 5
    if (confianza_max < CONFIANZA_MEDIA or len([r for r in todos.values() if r['score'] >= umbral_minimo]) < 2) and not ya_tengo_suficientes:
        ili_results, confianza = ssc_ilike(cur, query, router)
        fase = 4
        for r in ili_results:
            if r["id"] not in todos:
                todos[r["id"]] = r

    fusionados = sorted(todos.values(), key=lambda x: x["score"], reverse=True)
    fusionados = _aplicar_decaimiento_ssc(fusionados)
    fusionados.sort(key=lambda x: x["score"], reverse=True)
    filtrados = [r for r in fusionados if r["score"] >= umbral_minimo]

    elapsed = time.time() - start
    cur.close()
    conn.close()

    return filtrados, tags_msg, fase, elapsed


# ─── OUTPUT ────────────────────────────────────────────────────────────────────


def formatear_resultados(resultados, query, modo, fase, elapsed):
    if not resultados:
        return f"\nSSC: '{query}' → 0 resultados ({elapsed:.2f}s)"

    lines = [
        f"\n{'=' * 60}",
        "SSC v1.0 — Sparse Selective Caching",
        f'  Consulta: "{query}"',
        f"  Router modo: {modo} | Fase: {fase}/4 | {elapsed:.2f}s",
        f"  Resultados: {len(resultados)}",
        f"{'=' * 60}",
    ]

    for i, r in enumerate(resultados, 1):
        score = r["score"]
        met = r["method"].upper()
        tabla = "MV" if r["tabla"] == "memoria_vectorial" else "MI"
        if r.get("metadatos", {}).get("tags"):
            tags = r["metadatos"]["tags"]
            if isinstance(tags, list) and len(tags) > 0:
                met += f" [{tags[0]}]"
        barra = "█" * int(score / 5) + "░" * (20 - int(score / 5))
        lines.append(f"  {i:2d}. [{score:5.1f}] {barra} [{tabla}|{met}]")
        texto = r["contenido"][:200]
        lines.append(f"      {texto}")
        lines.append("")

    lines.append(f"{'=' * 60}")
    lines.append(f"Promedio: {sum(r['score'] for r in resultados) / len(resultados):.1f}")
    lines.append(f"Mejor: {resultados[0]['score']} | Peor: {resultados[-1]['score']}")
    return "\n".join(lines)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="SSC v1.0 — Búsqueda con Sparse Selective Caching (experimental)")
    parser.add_argument("query", help="Consulta en lenguaje natural")
    parser.add_argument("--threshold", type=float, default=10.0, help="Umbral mínimo de score (0-100, default 10)")
    args = parser.parse_args()

    resultados, modo, fase, elapsed = ssc_search(args.query, umbral_minimo=args.threshold)
    output = formatear_resultados(resultados, args.query, modo, fase, elapsed)
    print(output)
