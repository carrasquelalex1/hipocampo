#!/usr/bin/env python3
# hipocampo_save_cli.py — Guardar memoria en Hipocampo sin MCP
# ADVERTENCIA: inserta directo en memoria_vectorial, saltándose dedup y
# auditoría de contradicciones del MCP. Solo para emergencias o bulk
# controlado (luego verificar con hipocampo_dedup.py).
# Uso (usar el venv de hipocampo):
#   ~/.hipocampo/venv/bin/python3 ~/.hipocampo/scripts/hipocampo_save_cli.py \
#     "contenido" "tipo(event|decision|profile)" "code" '["cat1","cat2"]' "nivel(episodica|semantica|automatica)"
# Nota: genera embedding local (Ollama qwen3-embedding:0.6b). Si Ollama está
#       caído, guarda con embedding NULL; luego backfill con: hipocampo_backfill_vectorial.py
import sys
import os
import json

sys.path.insert(0, os.path.expanduser("~/.hipocampo"))
from hipocampo.db import get_conn, load_config, get_embedding
from datetime import date

load_config()
content, mtype, code, cats, nivel = sys.argv[1], sys.argv[2], sys.argv[3], json.loads(sys.argv[4]), sys.argv[5]
meta = {"type": mtype, "code": code, "categories": cats, "date": str(date.today()), "source": "cli", "nivel": nivel}
emb = get_embedding(content)
conn = get_conn()
cur = conn.cursor()
if emb is not None:
    cur.execute(
        "INSERT INTO memoria_vectorial (contenido, metadatos, embedding) VALUES (%s, %s, %s::vector(1024)) RETURNING id",
        (content, json.dumps(meta), emb),
    )
else:
    cur.execute(
        "INSERT INTO memoria_vectorial (contenido, metadatos, embedding) VALUES (%s, %s, NULL) RETURNING id",
        (content, json.dumps(meta)),
    )
rid = cur.fetchone()[0]
conn.commit()
conn.close()
print(f"Guardado ID={rid}" + ("" if emb else " (embedding pendiente de backfill)"))
