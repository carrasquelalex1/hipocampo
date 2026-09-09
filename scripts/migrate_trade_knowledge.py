#!/usr/bin/env python3
"""Migración one-time para reclasificar las memorias existentes con trade knowledge.

Ejecutar: python3 migrate_trade_knowledge.py
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.chdir(sys.path[0])

import json
from datetime import date
import hipocampo.db as db
from hipocampo_trade_knowledge import classify_trade_knowledge


def migrate():
    conn = db.get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id, contenido, metadatos::text FROM memoria_vectorial")
    rows = cur.fetchall()
    total = len(rows)

    trade_count = 0
    high_reuse_count = 0
    auto_promoted_count = 0
    migrated_count = 0
    skipped_count = 0
    error_count = 0

    print(f"🔄 Migración de {total} memorias...")

    for mv_id, contenido, meta_text in rows:
        try:
            meta = json.loads(meta_text) if meta_text else {}
            if "trade_knowledge" in meta:
                skipped_count += 1
                continue

            categories = meta.get("categories", [])
            result = classify_trade_knowledge(contenido, categories)
            meta["trade_knowledge"] = result["is_trade"]
            meta["reusability"] = result["reusability"]
            meta["domain_profile"] = result["domain_profile"]

            if result["is_trade"]:
                trade_count += 1
                high_reuse_count += 1 if result["reusability"] == "high" else 0
                if result["reusability"] == "high" and meta.get("nivel") == "episodica":
                    meta["nivel"] = "semantica"
                    meta["consolidated_at"] = str(date.today())
                    meta["consolidated_reason"] = "migration_trade_knowledge"
                    auto_promoted_count += 1

            cur.execute(
                "UPDATE memoria_vectorial SET metadatos=%s WHERE id=%s",
                (json.dumps(meta), mv_id),
            )
            migrated_count += 1
        except Exception as e:
            error_count += 1
            print(f"  ⚠️ Error en id={mv_id}: {e}")
            continue

    conn.commit()
    cur.close()
    conn.close()

    print("\n✅ Migración completada:")
    print(f"   Total procesadas: {total}")
    print(f"   Ya clasificadas (skip): {skipped_count}")
    print(f"   Migradas nuevas: {migrated_count}")
    print(f"   Con trade_knowledge=true: {trade_count}")
    print(f"   Con reusability=high: {high_reuse_count}")
    print(f"   Auto-promovidas a semántica: {auto_promoted_count}")
    print(f"   Errores: {error_count}")


if __name__ == "__main__":
    migrate()
