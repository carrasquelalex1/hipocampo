#!/usr/bin/env python3
"""Ciclo glinfático de Hipocampo — pasada nocturna ligera y con gate de actividad.

Analogía: el sistema glinfático del cerebro drena desechos durante el sueño
profundo, no mientras estás despierto procesando. Este ciclo hace lo mismo con
la memoria, pero solo la parte SEGURA:

  1. Mide la carga de desecho (4 métricas de aclaramiento).
  2. Purga la caché de juicios caducada (TTL 30 días).
  3. Refresca estadísticas del planificador (ANALYZE).

NO consolida, NO fusiona duplicados, NO borra memorias: eso es la limpieza
profunda semanal (hipocampo-maintenance.timer). Aquí nada es irreversible.

Gate de actividad: si no hubo consultas, accesos ni memorias nuevas en las
últimas N horas (default 24), no hace nada. El cerebro tampoco limpia despierto.

Uso:
    python3 scripts/hipocampo_glymphatic.py             # dry-run (default)
    python3 scripts/hipocampo_glymphatic.py --apply     # ops seguras reales
    python3 scripts/hipocampo_glymphatic.py --force     # ignora el gate
    python3 scripts/hipocampo_glymphatic.py --json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPTS_DIR)
sys.path.insert(0, os.path.dirname(SCRIPTS_DIR))

from hipocampo.db import get_conn, load_config  # noqa: E402

STATE_DIR = os.path.expanduser("~/.hipocampo/state")
STATE_PATH = os.path.join(STATE_DIR, "glymphatic_last.json")
JCACHE_TTL_DAYS = int(os.getenv("HIPOCAMPO_JCACHE_TTL_DIAS", "30"))


def actividad(cur, horas: int) -> dict:
    """Cuenta señales de actividad reciente para decidir si hay algo que limpiar."""
    intervalo = f"{int(horas)} hours"
    cur.execute("SELECT count(*) FROM query_stats WHERE created_at > now() - %s::interval", (intervalo,))
    consultas = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM memory_access WHERE accessed_at > now() - %s::interval", (intervalo,))
    accesos = cur.fetchone()[0]
    cur.execute(
        """
        SELECT count(*) FROM memoria_vectorial
        WHERE metadatos->>'date' = to_char(CURRENT_DATE, 'YYYY-MM-DD')
        """
    )
    nuevas = cur.fetchone()[0]
    return {
        "consultas": consultas,
        "accesos": accesos,
        "memorias_nuevas": nuevas,
        "total": consultas + accesos + nuevas,
    }


def metricas(cur) -> dict:
    """Las 4 métricas de aclaramiento (mismas que hipocampo_health)."""
    cur.execute(
        """
        WITH norm AS (
            SELECT id, md5(lower(btrim(contenido))) AS h
            FROM memoria_vectorial WHERE contenido IS NOT NULL
        )
        SELECT count(*) AS total, count(*) - count(DISTINCT h) AS dup_extra
        FROM norm
        """
    )
    total, dup_extra = cur.fetchone()
    dup_pct = round((dup_extra / total * 100) if total else 0.0, 2)

    cur.execute(
        """
        SELECT count(*) FROM memoria_vectorial mv
        WHERE mv.metadatos->>'nivel' = 'episodica'
          AND COALESCE((mv.metadatos->>'date')::date, CURRENT_DATE)
              < CURRENT_DATE - INTERVAL '90 days'
          AND NOT EXISTS (
              SELECT 1 FROM memory_access ma
              WHERE ma.memory_id = mv.id::text
                AND ma.accessed_at > now() - INTERVAL '90 days'
          )
        """
    )
    frios = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM memoria_vectorial WHERE metadatos->>'nivel' = 'episodica'")
    n_epi = cur.fetchone()[0]
    frios_pct = round((frios / n_epi * 100) if n_epi else 0.0, 2)

    cur.execute(
        """
        SELECT count(*) FROM memory_links l
        WHERE NOT EXISTS (SELECT 1 FROM memoria_vectorial mv WHERE mv.id::text = l.source_id)
          AND NOT EXISTS (SELECT 1 FROM memory_items mi WHERE mi.id = l.source_id)
        """
    )
    huerfanos_src = cur.fetchone()[0]
    cur.execute(
        """
        SELECT count(*) FROM memory_links l
        WHERE NOT EXISTS (SELECT 1 FROM memoria_vectorial mv WHERE mv.id::text = l.target_id)
          AND NOT EXISTS (SELECT 1 FROM memory_items mi WHERE mi.id = l.target_id)
        """
    )
    huerfanos_tgt = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM memory_links")
    n_links = cur.fetchone()[0]
    huerfanos = huerfanos_src + huerfanos_tgt
    huerfanos_pct = round((huerfanos / n_links * 100) if n_links else 0.0, 2)

    cur.execute("SELECT count(*) FROM memory_links WHERE relation_type = 'contradicts' AND weight >= 0.5")
    contradicciones = cur.fetchone()[0]

    cur.execute(
        "SELECT count(*) FROM judgment_cache WHERE created_at < now() - %s::interval",
        (f"{JCACHE_TTL_DAYS} days",),
    )
    jcache_expirada = cur.fetchone()[0]

    revisar = dup_pct > 2 or frios_pct > 20 or huerfanos_pct > 5 or contradicciones > 50
    return {
        "duplicados_exactos": dup_extra,
        "duplicados_pct": dup_pct,
        "episodicos_frios_90d": frios,
        "episodicos_frios_pct": frios_pct,
        "enlaces_huerfanos": huerfanos,
        "enlaces_huerfanos_pct": huerfanos_pct,
        "contradicciones_fuertes": contradicciones,
        "judgment_cache_expirada": jcache_expirada,
        "revisar": revisar,
    }


def aplicar_ops_seguras(cur, conn, m: dict, dry_run: bool) -> dict:
    """Solo operaciones reversibles o sin pérdida de memoria."""
    hechas = {}

    if m["judgment_cache_expirada"]:
        if dry_run:
            hechas["judgment_cache"] = f"omitido (dry-run): {m['judgment_cache_expirada']} caducadas"
        else:
            cur.execute(
                "DELETE FROM judgment_cache WHERE created_at < now() - %s::interval",
                (f"{JCACHE_TTL_DAYS} days",),
            )
            hechas["judgment_cache"] = f"{cur.rowcount} caducadas eliminadas"
    else:
        hechas["judgment_cache"] = "sin caducadas"

    if dry_run:
        hechas["analyze"] = "omitido (dry-run)"
    else:
        conn.commit()
        conn.autocommit = True
        try:
            cur.execute("ANALYZE memoria_vectorial, memory_items, memoria_vectorial_chunks, memory_links")
            hechas["analyze"] = "ok"
        finally:
            conn.autocommit = False

    return hechas


def guardar_estado(payload: dict) -> None:
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        tmp = STATE_PATH + ".tmp"
        with open(tmp, "w") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp, STATE_PATH)
    except Exception as e:  # noqa: BLE001
        print(f"⚠️  No se pudo escribir estado glinfático: {e}", file=sys.stderr)


def main() -> int:
    ap = argparse.ArgumentParser(description="Ciclo glinfático nocturno de Hipocampo")
    ap.add_argument("--apply", action="store_true", help="Aplica ops seguras (default: dry-run)")
    ap.add_argument("--force", action="store_true", help="Ignora el gate de actividad")
    ap.add_argument("--json", action="store_true", help="Salida JSON")
    ap.add_argument("--quiet", action="store_true", help="Solo errores (para systemd)")
    ap.add_argument(
        "--activity-hours",
        type=int,
        default=int(os.getenv("HIPOCAMPO_GLYMPH_ACTIVITY_HOURS", "24")),
        help="Ventana de actividad en horas (default: 24)",
    )
    args = ap.parse_args()

    load_config()
    dry_run = not args.apply
    t0 = time.monotonic()
    payload: dict = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "mode": "dry-run" if dry_run else "apply",
        "activity_hours": args.activity_hours,
    }

    conn = None
    try:
        conn = get_conn()
        cur = conn.cursor()

        act = actividad(cur, args.activity_hours)
        payload["actividad"] = act

        if act["total"] == 0 and not args.force:
            payload.update({"gate": "dormido", "acciones": {}, "metricas": {}})
            guardar_estado(payload)
            if args.json:
                print(json.dumps(payload, ensure_ascii=False, indent=2))
            elif not args.quiet:
                print(
                    f"💤 GLINFÁTICO — sin actividad en {args.activity_hours}h; "
                    "se omite (el cerebro tampoco limpia despierto)."
                )
            return 0

        payload["gate"] = "activo" if act["total"] else "forzado"
        m = metricas(cur)
        payload["metricas"] = m

        acciones = aplicar_ops_seguras(cur, conn, m, dry_run)
        payload["acciones"] = acciones
        payload["elapsed_s"] = round(time.monotonic() - t0, 2)
        payload["revisar"] = m["revisar"]
        guardar_estado(payload)

        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        elif not args.quiet:
            modo = "DRY-RUN" if dry_run else "APLICADO"
            print(f"🧠 GLINFÁTICO — {payload['timestamp']} ({modo}, gate={payload['gate']})")
            print(
                f"   Actividad {args.activity_hours}h: {act['consultas']} consultas, "
                f"{act['accesos']} accesos, {act['memorias_nuevas']} memorias nuevas"
            )
            print(
                f"   Desechos: duplicados {m['duplicados_exactos']} ({m['duplicados_pct']}%) · "
                f"episódicos fríos {m['episodicos_frios_90d']} ({m['episodicos_frios_pct']}%) · "
                f"enlaces huérfanos {m['enlaces_huerfanos']} ({m['enlaces_huerfanos_pct']}%) · "
                f"contradicciones fuertes {m['contradicciones_fuertes']}"
            )
            print(f"   Acciones: {acciones}")
            if m["revisar"]:
                print("   ⚠️  Carga de desecho por encima del umbral: revisar limpieza profunda.")
            print(f"   🏁 {payload['elapsed_s']}s")

        cur.close()
        return 0
    except Exception as e:  # noqa: BLE001
        payload["error"] = str(e)[:300]
        guardar_estado(payload)
        print(f"❌ GLINFÁTICO error: {e}", file=sys.stderr)
        return 1
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass


if __name__ == "__main__":
    sys.exit(main())
