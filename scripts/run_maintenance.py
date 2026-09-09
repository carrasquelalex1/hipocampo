#!/usr/bin/env python3
"""Ciclo de mantenimiento periódico de Hipocampo con persistencia.

Diseñado para systemd timer de usuario con Persistent=true: si la PC estaba
apagada en la ventana programada, la tarea se ejecuta apenas enciende.

Reutiliza el motor real del servidor MCP (scripts/hipocampo_mcp_server.py):
mismo código de consolidación, decay, dedup y purga — sin duplicar lógica.

IMPORTANTE: importa el módulo del server SIN levantar el transporte MCP (el
bloque `if __name__ == "__main__"` del server no corre al importar).

Uso:
    python3 run_maintenance.py              # DRY-RUN (simulación, seguro)
    python3 run_maintenance.py --apply      # aplica cambios reales
    python3 run_maintenance.py --apply --min-age 14
"""

import argparse
import os
import sys
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.dirname(BASE_DIR))  # project root para el paquete hipocampo

# El import de hipocampo_mcp_server inicializa el pool vía módulos importados
# (hipocampo.db), pero NO levanta el server MCP ni hace warm-up de embeddings.
import hipocampo_mcp_server as srv


def _fmt_step(name: str, result: str) -> str:
    ok = not result.startswith("error")
    return f"  {'✅' if ok else '❌'} {name}: {result}"


def run(dry_run: bool, min_age: int, decay_min_age: int, quiet: bool = False, review_only: bool = False) -> int:
    mode = "DRY-RUN (simulación)" if dry_run else "APLICANDO CAMBIOS"
    if not quiet:
        print(f"🧠 HIPOCAMPO MAINTENANCE — Modo: {mode}")
        print(f"   min_age (consolidación) = {min_age}d | decay (olvido) = {decay_min_age}d")

    exit_code = 0
    t0 = time.monotonic()

    if review_only:
        try:
            import asyncio
            review_result = asyncio.run(srv.review_automatica(max_age_days=30, dry_run=False))
            if not quiet:
                print(f"  {'✅' if not review_result.startswith('error') else '❌'} review_automatica: {review_result}")
            if review_result.startswith("error"):
                exit_code = 1
        except Exception as e:
            if not quiet:
                print(f"  ❌ review_automatica: {e}")
            exit_code = 1
        elapsed = time.monotonic() - t0
        if not quiet:
            print(f"🏁 review_automatica finalizado en {elapsed:.1f}s (exit={exit_code}).")
        return exit_code

    if dry_run:
        # Simulación: usar las tools con dry_run=True (solo lectura)
        import asyncio

        c = asyncio.run(srv.consolidate_hipocampo(min_age_days=min_age, dry_run=True))
        d = asyncio.run(srv.decay_hipocampo(dry_run=True, min_age_days=decay_min_age))
        if not quiet:
            print(c)
            print(d)
        print("🏁 DRY-RUN finalizado (ningún cambio aplicado).")
        return 0

    # Modo apply: usar el ciclo real del server (idéntico al scheduler interno)
    srv._MAINT_MIN_AGE_DAYS = min_age
    srv._MAINT_DECAY_MIN_AGE_DAYS = decay_min_age
    results = srv._run_maintenance_cycle(reason="cli")

    for name, res in results.items():
        if not quiet:
            print(_fmt_step(name, res))
        if res.startswith("error"):
            exit_code = 1

    # review_automatica: revisar reglas automatica sin revisión
    # (ejecuta siempre, dry_run=False para actualizar review_count)
    try:
        import asyncio
        review_result = asyncio.run(srv.review_automatica(max_age_days=30, dry_run=False))
        if not quiet:
            print(f"  {'✅' if not review_result.startswith('error') else '❌'} review_automatica: {review_result}")
        if review_result.startswith("error"):
            exit_code = 1
    except Exception as e:
        if not quiet:
            print(f"  ❌ review_automatica: {e}")
        exit_code = 1

    elapsed = time.monotonic() - t0
    if not quiet:
        print(f"🏁 Mantenimiento finalizado en {elapsed:.1f}s (exit={exit_code}).")
    return exit_code


def main():
    parser = argparse.ArgumentParser(description="Mantenimiento periódico de Hipocampo")
    parser.add_argument("--apply", action="store_true", help="Aplica los cambios reales (default: dry-run)")
    parser.add_argument(
        "--min-age",
        type=int,
        default=int(os.getenv("HIPOCAMPO_MAINT_MIN_AGE_DAYS", "7")),
        help="Días mínimos para consolidación episódica (default: 7)",
    )
    parser.add_argument(
        "--decay-min-age",
        type=int,
        default=int(os.getenv("HIPOCAMPO_MAINT_DECAY_MIN_AGE_DAYS", "60")),
        help="Días mínimos para archivar episódicas sin acceso (default: 60)",
    )
    parser.add_argument("--quiet", action="store_true", help="Solo errores (para logs limpios de systemd)")
    parser.add_argument("--review-only", action="store_true", help="Solo ejecuta review_automatica sin el ciclo completo")
    args = parser.parse_args()

    sys.exit(run(dry_run=not args.apply, min_age=args.min_age, decay_min_age=args.decay_min_age, quiet=args.quiet, review_only=args.review_only))


if __name__ == "__main__":
    main()
