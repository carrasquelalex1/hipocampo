#!/usr/bin/env python3
"""Backfill de summary, chunks y (opcional) embeddings — mejoras MCP 2026-10-20.

Por defecto solo hace trabajo de texto (rápido): rellena summary y crea los
chunks de recuerdos largos. Los embeddings son opcionales y se activan con
--embed-summaries / --embed-chunks; sin ellos, la búsqueda usa el canal
léxico de chunks, que ya funciona.

Uso:
    python3 scripts/hipocampo_backfill_summary_chunks.py
    python3 scripts/hipocampo_backfill_summary_chunks.py --ids 4039,4040
    python3 scripts/hipocampo_backfill_summary_chunks.py --embed-summaries --ids 4039
    python3 scripts/hipocampo_backfill_summary_chunks.py --dry-run
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hipocampo.db import get_conn, get_embedding  # noqa: E402
from hipocampo.textutil import dividir_en_chunks, resumir_contenido  # noqa: E402


def _md5(texto: str) -> str:
    return hashlib.md5((texto or "").encode("utf-8")).hexdigest()


def _ids(valor: str) -> list[int]:
    return [int(x) for x in valor.replace(" ", "").split(",") if x.isdigit()]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ids", default="", help="IDs concretos, separados por coma")
    ap.add_argument("--limit", type=int, default=0, help="Máximo de filas (0 = todas)")
    ap.add_argument("--chunk-min", type=int, default=1800, help="Longitud mínima para chunkear")
    ap.add_argument("--chunk-max", type=int, default=1800, help="Tamaño máximo de chunk")
    ap.add_argument("--overlap", type=int, default=180, help="Solapamiento entre chunks")
    ap.add_argument("--summary-chars", type=int, default=600)
    ap.add_argument("--embed-summaries", action="store_true", help="Generar summary_embedding")
    ap.add_argument("--embed-chunks", action="store_true", help="Generar embeddings de chunks")
    ap.add_argument("--timeout", type=float, default=900.0, help="Timeout de embedding (s)")
    ap.add_argument("--sleep", type=float, default=0.0, help="Pausa entre embeddings (s)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    conn = get_conn()
    cur = conn.cursor()
    where = ["contenido IS NOT NULL", "length(contenido) > 0"]
    params: list = []
    ids = _ids(args.ids)
    if ids:
        where.append("id = ANY(%s)")
        params.append(ids)
    sql = f"SELECT id, contenido FROM memoria_vectorial WHERE {' AND '.join(where)} ORDER BY id"
    if args.limit and args.limit > 0:
        sql += " LIMIT %s"
        params.append(args.limit)
    cur.execute(sql, params)
    rows = cur.fetchall()
    print(f"Filas a procesar: {len(rows)}")

    n_summary = 0
    n_chunks = 0
    n_embed_s = 0
    n_embed_c = 0
    for n, (row_id, contenido) in enumerate(rows, 1):
        contenido = contenido or ""
        summary = resumir_contenido(contenido, args.summary_chars)
        if args.dry_run:
            if n <= 5:
                print(f"[dry-run] id={row_id} chars={len(contenido)} summary={summary[:80]!r}")
            continue

        cur.execute(
            """UPDATE memoria_vectorial
               SET summary = %s,
                   metadatos = COALESCE(metadatos, '{}'::jsonb)
                       || jsonb_build_object('summary_src_md5', %s)
               WHERE id = %s""",
            (summary, _md5(contenido), row_id),
        )
        n_summary += 1

        if len(contenido) >= args.chunk_min:
            chunks = dividir_en_chunks(
                contenido,
                max_chars=args.chunk_max,
                overlap=args.overlap,
            )
            for ch in chunks:
                cur.execute(
                    """INSERT INTO memoria_vectorial_chunks (parent_id, chunk_index, contenido)
                       VALUES (%s, %s, %s)
                       ON CONFLICT (parent_id, chunk_index)
                       DO UPDATE SET contenido = EXCLUDED.contenido,
                                     embedding = CASE
                                         WHEN memoria_vectorial_chunks.contenido = EXCLUDED.contenido
                                         THEN memoria_vectorial_chunks.embedding
                                         ELSE NULL
                                     END""",
                    (row_id, ch["index"], ch["contenido"]),
                )
            cur.execute(
                "DELETE FROM memoria_vectorial_chunks WHERE parent_id = %s AND chunk_index >= %s",
                (row_id, len(chunks)),
            )
            n_chunks += len(chunks)
        else:
            cur.execute("DELETE FROM memoria_vectorial_chunks WHERE parent_id = %s", (row_id,))

        if args.embed_summaries and summary:
            cur.execute("SELECT summary_embedding IS NULL FROM memoria_vectorial WHERE id=%s", (row_id,))
            falta = cur.fetchone()
            if falta and falta[0]:
                emb = get_embedding(summary, timeout_s=args.timeout)
                if emb is not None:
                    cur.execute(
                        """UPDATE memoria_vectorial
                           SET summary_embedding = %s::vector(1024),
                               metadatos = COALESCE(metadatos, '{}'::jsonb)
                                   || jsonb_build_object('summary_embedding_src_md5', %s)
                           WHERE id = %s""",
                        (emb, _md5(summary), row_id),
                    )
                    n_embed_s += 1
                    if args.sleep:
                        time.sleep(args.sleep)

        if args.embed_chunks:
            cur.execute(
                """SELECT chunk_index, contenido FROM memoria_vectorial_chunks
                   WHERE parent_id=%s AND embedding IS NULL ORDER BY chunk_index""",
                (row_id,),
            )
            for ch_idx, ch_txt in cur.fetchall():
                emb = get_embedding(ch_txt, timeout_s=args.timeout)
                if emb is not None:
                    cur.execute(
                        "UPDATE memoria_vectorial_chunks SET embedding=%s::vector(1024) WHERE parent_id=%s AND chunk_index=%s",
                        (emb, row_id, ch_idx),
                    )
                    n_embed_c += 1
                    if args.sleep:
                        time.sleep(args.sleep)

        if n % 50 == 0:
            conn.commit()
            print(f"  ... {n}/{len(rows)} (summaries={n_summary}, chunks={n_chunks})")

    conn.commit()
    cur.close()
    conn.close()
    print(f"OK: summaries={n_summary}, chunks={n_chunks}, summary_embeddings={n_embed_s}, chunk_embeddings={n_embed_c}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
