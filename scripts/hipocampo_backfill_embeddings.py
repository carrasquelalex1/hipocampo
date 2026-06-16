#!/usr/bin/env python3
"""hipocampo_backfill_embeddings.py — Regenera embeddings 1024d en memory_items.

Problema: memory_items fue poblado con embeddings 768d (gemini-embedding-001).
memoria_vectorial tambien usaba 768d. Este script unifica ambos subsistemas al
mismo modelo (nvidia/nv-embedqa-e5-v5) y dimensionalidad (1024d).

Uso:
    python3 hipocampo_backfill_embeddings.py
"""
import psycopg2, os, sys, time
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

DB_NAME = os.getenv('DB_NAME', 'hipocampo_db')
DB_USER = os.getenv('DB_USER', 'alex')
DB_PASSWORD = os.getenv('DB_PASSWORD', '')
DB_HOST = os.getenv('DB_HOST', '/var/run/postgresql')

client = OpenAI(
    base_url="https://integrate.api.nvidia.com/v1",
    api_key=os.getenv("NVIDIA_API_KEY"),
)

BATCH_SIZE = 5
DELAY_BETWEEN_BATCHES = 5.0


def get_embedding_1024(text, retries=3):
    for attempt in range(retries):
        try:
            resp = client.embeddings.create(
                input=text,
                model="nvidia/nv-embedqa-e5-v5",
                encoding_format="float",
                extra_body={"input_type": "query"},
            )
            return resp.data[0].embedding
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
    conn = psycopg2.connect(
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
        host=DB_HOST
    )
    cur = conn.cursor()

    # Check current state of the column
    cur.execute("""
        SELECT column_name, udt_name 
        FROM information_schema.columns 
        WHERE table_name = 'memory_items' AND column_name = 'embedding'
    """)
    col_info = cur.fetchone()
    if col_info:
        print(f"📊 Columna embedding existe: {col_info}")

    # Check if column is vector(1024) or just vector
    cur.execute("""
        SELECT e.typname, e.typtype
        FROM pg_type e
        JOIN pg_attribute a ON a.atttypid = e.oid
        WHERE a.attrelid = 'memory_items'::regclass AND a.attname = 'embedding'
    """)
    type_info = cur.fetchone()
    print(f"📊 Tipo de embedding: {type_info}")

    # Fetch remaining records without embeddings
    cur.execute("""
        SELECT id, summary FROM memory_items
        WHERE embedding IS NULL
        ORDER BY created_at
    """)
    rows = cur.fetchall()
    total = len(rows)
    print(f"📦 {total} registros en memory_items necesitan embedding 1024d")

    if total == 0:
        print("✅ Todo unificado — 0 registros por procesar")
        cur.close()
        conn.close()
        return

    # Process in batches with rate limit awareness
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

    # Verify HNSW index exists
    cur.execute("""
        SELECT 1 FROM pg_indexes 
        WHERE indexname = 'idx_memory_items_embedding'
    """)
    if not cur.fetchone():
        print(f"\n📊 Creando índice HNSW en memory_items.embedding...")
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_memory_items_embedding
            ON memory_items USING hnsw (embedding vector_cosine_ops)
        """)
        conn.commit()

    # Summary
    cur.execute("SELECT COUNT(*) FROM memory_items WHERE embedding IS NOT NULL")
    ok = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM memory_items")
    total_items = cur.fetchone()[0]

    print(f"\n{'='*50}")
    print(f"✅ Embeddings unificados: {ok}/{total_items} registros con embedding 1024d")
    print(f"⚠️  Errores en esta ejecución: {errors}")
    print(f"📊 Índice HNSW: idx_memory_items_embedding (vector_cosine_ops)")
    print(f"{'='*50}")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
