#!/usr/bin/env python3
"""hipocampo_backfill_embeddings.py — Regenera embeddings 1024d en memory_items.

Problema: memory_items fue poblado con embeddings 768d (gemini-embedding-001).
memoria_vectorial tambien usaba 768d. Este script unifica ambos subsistemas al
mismo modelo (nvidia/nv-embedqa-e5-v5) y dimensionalidad (1024d).

Uso:
    python3 hipocampo_backfill_embeddings.py
"""
import os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from hipocampo.db import get_conn, get_embedding, load_config

load_config()

BATCH_SIZE = 5
DELAY_BETWEEN_BATCHES = 5.0


def get_embedding_1024(text, retries=3):
    for attempt in range(retries):
        try:
            emb = get_embedding(text)
            if emb is not None:
                return emb
        except Exception as e:
            err_str = str(e)
            if '429' in err_str or 'RATE_LIMIT' in err_str:
                wait = 10 * (attempt + 1)
                print(f"  ⏳ Rate limit, esperando {wait}s (intento {attempt+1}/{retries})...")
                time.sleep(wait)
                continue
            print(f"  Error: {e}")
            return None
    return None


def main():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("SELECT id, summary FROM memory_items WHERE embedding IS NULL ORDER BY created_at")
    rows = cur.fetchall()
    total = len(rows)
    print(f"📦 {total} registros en memory_items necesitan embedding 1024d")

    if total == 0:
        print("✅ Todo unificado — 0 registros por procesar")
        cur.close()
        conn.close()
        return

    processed = 0
    errors = 0
    for i in range(0, total, BATCH_SIZE):
        batch = rows[i:i + BATCH_SIZE]
        batch_num = i // BATCH_SIZE + 1
        total_batches = (total + BATCH_SIZE - 1) // BATCH_SIZE
        print(f"\n🔨 Lote {batch_num}/{total_batches} ({len(batch)} registros)")

        for item_id, summary in batch:
            emb = get_embedding_1024(summary)
            if emb is None:
                errors += 1
                print(f"  ❌ {item_id}: error (pendiente para próxima ejecución)")
                continue
            cur.execute(
                "UPDATE memory_items SET embedding = %s::vector(1024) WHERE id = %s",
                (emb, item_id)
            )
            processed += 1
            print(f"  ✅ {item_id}: {summary[:60]}...")

        conn.commit()
        if batch_num < total_batches:
            print(f"  ⏳ Esperando {DELAY_BETWEEN_BATCHES}s...")
            time.sleep(DELAY_BETWEEN_BATCHES)

    cur.execute("SELECT COUNT(*) FROM memory_items WHERE embedding IS NOT NULL")
    ok = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM memory_items")
    total_items = cur.fetchone()[0]

    print(f"\n{'='*50}")
    print(f"✅ Embeddings unificados: {ok}/{total_items} registros con embedding 1024d")
    print(f"⚠️  Errores en esta ejecución: {errors}")
    print(f"{'='*50}")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
