#!/usr/bin/env python3
"""hipocampo_checkpoint.py — Checkpointing con decaimiento logarítmico v1.0

Inspirado en "Memory Caching: RNNs with Growing Memory" (Google, 2025).

Concepto:
  - Las memorias RECIENTES se mantienen con grano fino (detalle completo)
  - Las memorias ANTIGUAS se comprimen en "checkpoints" (resúmenes agregados)
  - Esto reduce el ruido en búsquedas y mejora la relación señal/ruido

Arquitectura de escalas temporales:
  - < 24h: detalle completo (sin compresión)
  - 1-7 días: compresión ligera (top 3 items por sesión)
  - 7-30 días: compresión media (resumen de 200 chars por sesión)
  - 30-90 días: compresión fuerte (resumen de 100 chars por semana)
  - > 90 días: checkpoint único por proyecto/dominio

Uso:
    python3 scripts/hipocampo_checkpoint.py [--dry-run] [--force]
"""

import os
import json
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from hipocampo.db import get_conn, load_config

load_config()

ESCALAS = [
    ("24h", timedelta(hours=24)),
    ("7d", timedelta(days=7)),
    ("30d", timedelta(days=30)),
    ("90d", timedelta(days=90)),
    ("all", None),
]


def obtener_edades(cur):
    """Clasifica entradas por escala temporal según metadatos->'fecha'.

    Respeta niveles jerárquicos:
      - automatica: se omite (nunca se comprime)
      - semantica: se marca como no comprimible
      - episodica o sin nivel: comprimible normalmente
    """
    ahora = datetime.now()

    cur.execute("""
        SELECT id, contenido, metadatos::text
        FROM memoria_vectorial
        ORDER BY id
    """)
    rows = cur.fetchall()

    escalas = {e[0]: [] for e in ESCALAS}
    sin_fecha = []

    for row in rows:
        meta = json.loads(row[2])
        nivel = meta.get("nivel", "episodica")

        # automatica = regla permanente, nunca se toca
        if nivel == "automatica":
            continue

        # semantica = protegida, solo se indexa como no comprimible
        es_semantica = nivel == "semantica"

        fecha_str = meta.get("fecha")
        if fecha_str:
            try:
                fecha = datetime.fromisoformat(fecha_str)
                edad = ahora - fecha
                key = (escalas["24h"], [])
                if edad < timedelta(hours=24):
                    key = escalas["24h"]
                elif edad < timedelta(days=7):
                    key = escalas["7d"]
                elif edad < timedelta(days=30):
                    key = escalas["30d"]
                elif edad < timedelta(days=90):
                    key = escalas["90d"]
                else:
                    key = escalas["all"]
                key.append((row, es_semantica))
            except (ValueError, TypeError):
                sin_fecha.append((row, es_semantica))
        else:
            sin_fecha.append((row, es_semantica))

    return escalas, sin_fecha


def agrupar_por_proyecto(entries):
    """Agrupa entradas por proyecto según metadatos.
    entries: list of (row, es_semantica) tuples.
    """
    grupos = {}
    for row, es_semantica in entries:
        meta = json.loads(row[2])
        proyecto = meta.get("proyecto", meta.get("path", "general"))
        if proyecto not in grupos:
            grupos[proyecto] = []
        grupos[proyecto].append((row, es_semantica))
    return grupos


def generar_resumen(grupo, max_chars=300):
    """Genera un resumen comprimido de un grupo de entradas.
    grupo: list of (row, es_semantica) tuples.
    """
    if not grupo:
        return None

    titulos = []
    for row, es_semantica in grupo:
        contenido = row[1][:150].strip()
        titulos.append(contenido)

    resumen = " | ".join(titulos)
    if len(resumen) > max_chars:
        resumen = resumen[: max_chars - 3] + "..."

    tags = set()
    for row, es_semantica in grupo:
        meta = json.loads(row[2])
        ts = meta.get("tags", [])
        if isinstance(ts, list):
            tags.update(t.strip().lower() for t in ts if isinstance(t, str))

    return {
        "resumen": resumen,
        "total_items": len(grupo),
        "tags": sorted(tags),
    }


def generar_checkpoints(escalas, sin_fecha, dry_run=False):
    """Genera checkpoints por escala temporal.
    entries ahora son listas de (row, es_semantica) tuples.
    Las semánticas se mantienen sin comprimir.
    """
    reportes = []

    for escala_nombre, _ in ESCALAS:
        entries = escalas[escala_nombre]
        if not entries:
            continue

        grupos = agrupar_por_proyecto(entries)

        if escala_nombre == "24h":
            max_items = None
            max_chars = 500
        elif escala_nombre == "7d":
            max_items = 3
            max_chars = 300
        elif escala_nombre == "30d":
            max_items = 2
            max_chars = 200
        elif escala_nombre == "90d":
            max_items = 1
            max_chars = 150
        else:
            max_items = 1
            max_chars = 100

        total_items = len(entries)
        total_grupos = len(grupos)

        resumenes = []
        for proyecto, grupo in grupos.items():
            semanticas = [g for g in grupo if g[1]]
            episodicas = [g for g in grupo if not g[1]]

            # Las semánticas siempre se mantienen en detalle
            for row, es_sem in semanticas:
                meta = json.loads(row[2])
                resumenes.append(
                    {
                        "proyecto": proyecto,
                        "resumen": row[1][:max_chars],
                        "total_items": 1,
                        "tags": meta.get("tags", []),
                        "comprimido": False,
                        "original_count": 1,
                        "nivel": "semantica",
                    }
                )

            # Episódicas se comprimen según la escala
            if max_items is not None and len(episodicas) > max_items:
                r = generar_resumen(episodicas, max_chars)
                if r:
                    resumenes.append(
                        {
                            "proyecto": proyecto,
                            **r,
                            "comprimido": True,
                            "original_count": len(episodicas),
                        }
                    )
            else:
                for row, es_sem in episodicas:
                    meta = json.loads(row[2])
                    resumenes.append(
                        {
                            "proyecto": proyecto,
                            "resumen": row[1][:max_chars],
                            "total_items": 1,
                            "tags": meta.get("tags", []),
                            "comprimido": False,
                            "original_count": 1,
                        }
                    )

        reportes.append(
            {
                "escala": escala_nombre,
                "total_items": total_items,
                "total_grupos": total_grupos,
                "items_comprimidos": sum(1 for r in resumenes if r["comprimido"]),
                "items_detalle": sum(1 for r in resumenes if not r["comprimido"]),
                "resumenes": resumenes,
            }
        )

    return reportes


def formatear_reporte(reportes, sin_fecha, dry_run):
    lines = [
        f"\n{'=' * 60}",
        "Checkpoint v1.0 — Decaimiento Logarítmico",
        f"  Modo: {'DRY-RUN' if dry_run else 'ACTIVO'}",
        f"{'=' * 60}",
    ]

    total_comprimidos = 0
    total_detalle = 0

    for r in reportes:
        comp = r["items_comprimidos"]
        det = r["items_detalle"]
        total_comprimidos += comp
        total_detalle += det

        lines.append(
            f"\n Escala: {r['escala']:5s} | {r['total_items']:4d} items | {r['total_grupos']:3d} grupos | {comp:3d} comprimidos | {det:3d} detalle"
        )

        if r["escala"] == "24h" and r["resumenes"]:
            lines.append("  Recientes (<24h) — sin compresión:")
            for s in r["resumenes"][:3]:
                lines.append(f"    [{s['proyecto']}] {s['resumen'][:80]}")

        if r["escala"] in ("7d", "30d", "90d", "all"):
            for s in sorted(r["resumenes"], key=lambda x: x["original_count"], reverse=True)[:5]:
                if s["comprimido"]:
                    lines.append(f"    [{s['proyecto']}] COMPRIMIDO: {s['original_count']} items → {s['resumen'][:80]}")
                else:
                    lines.append(f"    [{s['proyecto']}] detalle: {s['resumen'][:80]}")

    if sin_fecha:
        lines.append(f"\n  Sin fecha: {len(sin_fecha)} items (no clasificables)")

    lines.append(f"\n{'=' * 60}")
    lines.append(f"Total: {sum(r['total_items'] for r in reportes)} items")
    lines.append(f"Comprimidos: {total_comprimidos} grupos | Detalle: {total_detalle} items")
    lines.append(f"{'=' * 60}")

    return "\n".join(lines)


def run_checkpoint(dry_run: bool = True):
    """Ejecuta el checkpoint y retorna el texto formateado."""
    conn = get_conn()
    cur = conn.cursor()

    escalas, sin_fecha = obtener_edades(cur)
    reportes = generar_checkpoints(escalas, sin_fecha, dry_run=dry_run)
    output = formatear_reporte(reportes, sin_fecha, dry_run)

    if not dry_run:
        for r in reportes:
            comprimidos = [s for s in r["resumenes"] if s["comprimido"]]
            for s in comprimidos:
                resumen = s["resumen"]
                tags = s["tags"]
                try:
                    cur.execute(
                        "INSERT INTO memoria_vectorial (contenido, metadatos) VALUES (%s, %s)",
                        (
                            f"[CHECKPOINT {r['escala']}] {resumen}",
                            json.dumps(
                                {
                                    "tipo": "checkpoint",
                                    "escala": r["escala"],
                                    "fecha": datetime.now().isoformat(),
                                    "proyecto": s["proyecto"],
                                    "tags": tags + ["checkpoint"],
                                    "items_originales": s["original_count"],
                                }
                            ),
                        ),
                    )
                except Exception as e:
                    print(f"  Error guardando checkpoint: {e}")
        if comprimidos:
            conn.commit()
            output += f"\n  {len(comprimidos)} checkpoints guardados en memoria_vectorial"
        else:
            output += "\n  No se encontraron items para comprimir."
    else:
        output += "\n\nUsa --force para guardar los checkpoints en memoria_vectorial."

    print(output)
    cur.close()
    conn.close()
    return output


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Checkpointing logarítmico — comprime memorias antiguas")
    parser.add_argument("--dry-run", action="store_true", help="Solo mostrar qué se comprimiría (default)")
    parser.add_argument("--force", action="store_true", help="Ejecutar compresión y guardar checkpoints")
    args = parser.parse_args()
    run_checkpoint(dry_run=not args.force or args.dry_run)


if __name__ == "__main__":
    main()
