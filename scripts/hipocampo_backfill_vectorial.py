#!/usr/bin/env python3
"""hipocampo_backfill_vectorial.py — Backfill embeddings 768d en memoria_vectorial.

Genera embeddings para registros existentes que tienen embedding IS NULL.
Usa Gemini API (gemini-embedding-001, 768d) con rate limiting.

Uso:
    python3 scripts/hipocampo_backfill_vectorial.py
"""
import psycopg2, os, time, sys
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

DB_NAME = os.getenv('DB_NAME', 'hipocampo_db')
DB_USER = os.getenv('DB_USER', 'postgres')
DB_PASSWORD = os.getenv('DB_PASSWORD', '')
DB_HOST = os.getenv('DB_HOST', 'localhost')

client = genai.Client(api_key=os.getenv('GOOGLE_API_KEY'))

BATCH_SIZE = 3
DELAY_BETWEEN_BATCHES = 30.0

def get_embedding_768(text, retries=3):
    for attempt in range(retries):
        try:
            result = client.models.embed_content(
                model="gemini-embedding-001",
                contents=text[:3000],
                config=types.EmbedContentConfig(
                    task_type="RETRIEVAL_DOCUMENT",
                    output_dimensionality=768
                )
            )
            return result.embeddings[0].values
        except Exception as e:
            err_str = str(e)
            if '429' in err_str or 'RESOURCE_EXHAUSTED' in err_str:
                wait = 65 * (attempt + 1)
                print(f"  Cuota agotada, esperando {wait}s...")
                time.sleep(wait)
                continue
            print(f"  Error: {e}")
            return None
    return None

def main():
    conn = psycopg2.connect(
        dbname=DB_NAME, user=DB_USER,
        password=DB_PASSWORD, host=DB_HOST
    )
    cur = conn.cursor()

    cur.execute("""
        SELECT id, contenido FROM memoria_vectorial
        WHERE embedding IS NULL
        ORDER BY id
    """)
    rows = cur.fetchall()
    total = len(rows)
    print(f"memoria_vectorial: {total} registros sin embedding")

    if total == 0:
        print("TODO unificado — 0 registros por procesar")
        cur.close(); conn.close()
        return

    processed = 0; errors = 0
    for i in range(0, total, BATCH_SIZE):
        batch = rows[i:i + BATCH_SIZE]
        batch_num = i // BATCH_SIZE + 1
        total_batches = (total + BATCH_SIZE - 1) // BATCH_SIZE
        print(f"\nLote {batch_num}/{total_batches}")

        for item_id, contenido in batch:
            emb = get_embedding_768(contenido)
            if emb is None:
                errors += 1
                print(f"  X {item_id}: error")
                continue
            cur.execute(
                "UPDATE memoria_vectorial SET embedding = %s::vector(768) WHERE id = %s",
                (emb, item_id)
            )
            processed += 1
            print(f"  OK {item_id}: {contenido[:60]}...")

        conn.commit()
        if batch_num < total_batches:
            print(f"  Esperando {DELAY_BETWEEN_BATCHES}s...")
            time.sleep(DELAY_BETWEEN_BATCHES)

    cur.execute("SELECT COUNT(*) FROM memoria_vectorial WHERE embedding IS NOT NULL")
    ok = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM memoria_vectorial")
    total_items = cur.fetchone()[0]

    print(f"\nResultado: {ok}/{total_items} registros con embedding 768d")
    print(f"Errores: {errors}")

    if errors > 0:
        print("Re-ejecutar el script para los registros faltantes.")

    cur.close(); conn.close()

if __name__ == "__main__":
    main()
