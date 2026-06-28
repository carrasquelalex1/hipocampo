#!/usr/bin/env python3
"""hipocampo_dedup.py v1.0 — Detector y fusionador de duplicados.

Encuentra y fusiona registros duplicados o casi-duplicados en las
tablas de memoria de Hipocampo. Usa similitud coseno de embeddings
para detectar duplicados semánticos y coincidencia exacta para duplicados literales.

Uso:
    python3 scripts/hipocampo_dedup.py                          # análisis seco
    python3 scripts/hipocampo_dedup.py --merge                  # fusiona duplicados
    python3 scripts/hipocampo_dedup.py --threshold 0.95          # umbral de similitud
"""

import os
import sys
import logging

logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
logger = logging.getLogger("hipocampo_dedup")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from hipocampo.db import get_conn, load_config

SIMILARITY_THRESHOLD = 0.92


def find_exact_duplicates(table, text_col):
    """Encuentra duplicados exactos por contenido."""
    conn = get_conn()
    cur = conn.cursor()
    if table == "memoria_vectorial":
        cur.execute(f"""
            SELECT {text_col}, COUNT(*), array_agg(id::text) as ids
            FROM {table}
            GROUP BY {text_col}
            HAVING COUNT(*) > 1
            ORDER BY COUNT(*) DESC
            LIMIT 50
        """)
    else:
        cur.execute(f"""
            SELECT {text_col}, COUNT(*), array_agg(id::text) as ids
            FROM {table}
            GROUP BY {text_col}
            HAVING COUNT(*) > 1
            ORDER BY COUNT(*) DESC
            LIMIT 50
        """)
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


def find_semantic_duplicates(table, text_col, threshold=SIMILARITY_THRESHOLD):
    """Encuentra duplicados semánticos usando similitud de embeddings."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(f"SELECT COUNT(*) FROM {table}")
    total = cur.fetchone()[0]
    if total > 500:
        cur.execute(f"SELECT id, {text_col}, embedding::text FROM {table} ORDER BY id DESC LIMIT 500")
    else:
        cur.execute(f"SELECT id, {text_col}, embedding::text FROM {table}")
    rows = cur.fetchall()
    cur.close()
    conn.close()

    import ast

    candidates = []
    for row in rows:
        try:
            emb = ast.literal_eval(row[2]) if isinstance(row[2], str) else row[2]
            candidates.append({"id": row[0], "text": row[1], "embedding": emb})
        except Exception:
            pass

    import math

    def cosine_sim(a, b):
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(x * x for x in b))
        return dot / (na * nb) if na * nb > 0 else 0

    duplicates = []
    checked = set()
    for i in range(len(candidates)):
        if candidates[i]["id"] in checked:
            continue
        group = [candidates[i]]
        for j in range(i + 1, len(candidates)):
            if candidates[j]["id"] in checked:
                continue
            sim = cosine_sim(candidates[i]["embedding"], candidates[j]["embedding"])
            if sim >= threshold:
                group.append(candidates[j])
                checked.add(candidates[j]["id"])
        if len(group) > 1:
            checked.add(candidates[i]["id"])
            duplicates.append(group)

    duplicates.sort(key=lambda g: len(g), reverse=True)
    return duplicates


def merge_exact_duplicates(table, text_col, groups, dry_run=True):
    """Fusiona duplicados exactos: conserva el más reciente, elimina el resto."""
    conn = get_conn()
    cur = conn.cursor()
    merged_count = 0
    removed_count = 0

    for text, count, ids in groups:
        id_list = ids[:count]
        keep_id = id_list[0]
        remove_ids = id_list[1:]

        if table == "memory_items":
            cur.execute("SELECT MAX(updated_at) FROM memory_items WHERE id = ANY(%s)", (remove_ids + [keep_id],))
            max_date = cur.fetchone()[0]
            if max_date:
                cur.execute("UPDATE memory_items SET updated_at = %s WHERE id = %s", (max_date, keep_id))

        if not dry_run:
            for rid in remove_ids:
                if table == "memoria_vectorial":
                    cur.execute("DELETE FROM memoria_vectorial WHERE id = %s", (rid,))
                elif table == "memory_items":
                    cur.execute("DELETE FROM category_items WHERE item_id = %s", (rid,))
                    cur.execute("DELETE FROM memory_items WHERE id = %s", (rid,))
            removed_count += len(remove_ids)
            merged_count += 1

    if not dry_run:
        conn.commit()
    cur.close()
    conn.close()
    return {"merged_groups": merged_count, "removed": removed_count}


def merge_semantic_duplicates(table, text_col, groups, dry_run=True):
    """Fusiona duplicados semánticos: conserva el texto más largo, elimina el resto."""
    conn = get_conn()
    cur = conn.cursor()
    merged_count = 0
    removed_count = 0

    for group in groups:
        best = max(group, key=lambda x: len(x["text"]))
        others = [x for x in group if x["id"] != best["id"]]

        if not dry_run:
            for other in others:
                if table == "memoria_vectorial":
                    cur.execute("DELETE FROM memoria_vectorial WHERE id = %s", (other["id"],))
                elif table == "memory_items":
                    cur.execute("DELETE FROM category_items WHERE item_id = %s", (other["id"],))
                    cur.execute("DELETE FROM memory_items WHERE id = %s", (other["id"],))
            merged_count += 1
            removed_count += len(others)

    if not dry_run:
        conn.commit()
    cur.close()
    conn.close()
    return {"merged_groups": merged_count, "removed": removed_count}


def full_dedup_analysis(threshold=SIMILARITY_THRESHOLD):
    """Ejecuta análisis completo de duplicados en todas las tablas."""
    load_config()
    results = {}

    for table, text_col in [("memoria_vectorial", "contenido"), ("memory_items", "summary")]:
        exact = find_exact_duplicates(table, text_col)
        semantic = find_semantic_duplicates(table, text_col, threshold)

        total_exact = sum(row[1] - 1 for row in exact)
        total_semantic = sum(len(g) - 1 for g in semantic)

        results[table] = {
            "exact_duplicates": len(exact),
            "exact_redundant_rows": total_exact,
            "semantic_groups": len(semantic),
            "semantic_redundant_rows": total_semantic,
            "total_recoverable": total_exact + total_semantic,
            "exact_details": [(r[0][:60], r[1], r[2][:3]) for r in exact[:5]],
            "semantic_details": [(g[0]["text"][:60], len(g), [x["id"] for x in g[:3]]) for g in semantic[:5]],
        }

    return results


def full_dedup_merge(threshold=SIMILARITY_THRESHOLD):
    """Ejecuta fusión completa de duplicados."""
    load_config()
    report = {"exact": {}, "semantic": {}}

    for table, text_col in [("memoria_vectorial", "contenido"), ("memory_items", "summary")]:
        exact = find_exact_duplicates(table, text_col)
        if exact:
            report["exact"][table] = merge_exact_duplicates(table, text_col, exact, dry_run=False)

        semantic = find_semantic_duplicates(table, text_col, threshold)
        if semantic:
            report["semantic"][table] = merge_semantic_duplicates(table, text_col, semantic, dry_run=False)

    return report


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Deduplicación de memorias — detecta y fusiona duplicados")
    parser.add_argument("--merge", action="store_true", help="Fusionar duplicados (por defecto solo analiza)")
    parser.add_argument(
        "--threshold",
        type=float,
        default=SIMILARITY_THRESHOLD,
        help=f"Umbral de similitud coseno (default {SIMILARITY_THRESHOLD})",
    )
    args = parser.parse_args()

    if args.merge:
        result = full_dedup_merge(args.threshold)
        total_removed = sum(v.get("removed", 0) for v in result["exact"].values()) + sum(
            v.get("removed", 0) for v in result["semantic"].values()
        )
        print(f"🔧 Dedup merge completado: {total_removed} registros eliminados")
        for k, v in result.items():
            for t, r in v.items():
                if r.get("removed", 0) > 0:
                    print(f"   {t} ({k}): {r['merged_groups']} grupos fusionados, {r['removed']} eliminados")
        print("   ✅ Proceso completado")
    else:
        result = full_dedup_analysis(args.threshold)
        for table, info in result.items():
            emoji = "⚠️" if info["total_recoverable"] > 0 else "✅"
            print(f"{emoji} {table}:")
            print(
                f"   Duplicados exactos: {info['exact_duplicates']} grupos ({info['exact_redundant_rows']} registros redundantes)"
            )
            print(
                f"   Duplicados semánticos: {info['semantic_groups']} grupos ({info['semantic_redundant_rows']} registros redundantes)"
            )
            print(f"   Espacio recuperable: {info['total_recoverable']} registros")
            if info["exact_duplicates"] > 0:
                print(f"   Ejemplo exactos: {info['exact_details'][:2]}")
            if info["semantic_groups"] > 0:
                print(f"   Ejemplo semánticos: {info['semantic_details'][:2]}")
        print("\n💡 Ejecuta con --merge para fusionar y limpiar")
