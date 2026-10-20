#!/usr/bin/env python3
"""Evalúa la búsqueda del Hipocampo con Recall@K y MRR@K.

Uso:
    python3 scripts/hipocampo_eval_search.py
    python3 scripts/hipocampo_eval_search.py --rerank auto --k 5
    python3 scripts/hipocampo_eval_search.py --json-out /tmp/eval_new.json
    python3 scripts/hipocampo_eval_search.py --module hipocampo_search_old \
        --json-out /tmp/eval_old.json

El módulo es configurable para poder comparar contra una versión anterior
(p. ej. `git show HEAD:scripts/hipocampo_search.py` en /tmp/opencode).
"""

from __future__ import annotations

import argparse
import importlib
import inspect
import json
import os
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DEFAULT_CASES = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "tests",
    "eval_search_cases.json",
)


def _id_numerico(resultado) -> int | None:
    """ID de memoria_vectorial a partir de los prefijos internos (v/l/tv/t)."""
    mid = str((resultado or {}).get("id") or "")
    for pref in ("tv", "t", "l", "v"):
        resto = mid[len(pref) :] if mid.startswith(pref) else ""
        if resto.isdigit():
            return int(resto)
    return None


def _metricas(hit_rank: int | None, k: int) -> tuple[float, float, float]:
    if hit_rank is None or hit_rank > k:
        return 0.0, 0.0, 0.0
    return 1.0, 1.0 / hit_rank, 1.0 if hit_rank == 1 else 0.0


def _buscar(mod, query: str, k: int, rerank: str):
    kwargs = {"umbral_minimo": 0}
    params = inspect.signature(mod.bire_search).parameters
    if "k" in params:
        kwargs["k"] = k
    if "rerank_mode" in params:
        kwargs["rerank_mode"] = rerank
    return mod.bire_search(query, **kwargs)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cases", default=DEFAULT_CASES)
    ap.add_argument("--module", default="hipocampo_search")
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--rerank", choices=["auto", "always", "never"], default="never")
    ap.add_argument("--json-out", default="")
    ap.add_argument("--baseline", default="", help="JSON de una corrida anterior para comparar")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    with open(args.cases, encoding="utf-8") as fh:
        payload = json.load(fh)
    casos = payload.get("cases") or []
    if not casos:
        print("No hay casos en", args.cases)
        return 2

    mod = importlib.import_module(args.module)
    filas = []
    recalls = []
    mrrs = []
    top1s = []
    for caso in casos:
        query = caso["query"]
        esperados = [int(x) for x in (caso.get("expected") or [])]
        t0 = time.time()
        try:
            resultados = _buscar(mod, query, args.k, args.rerank)
            error = ""
        except Exception as e:  # un caso roto no debe tumbar la evaluación
            resultados = []
            error = f"{type(e).__name__}: {e}"
        elapsed_ms = int((time.time() - t0) * 1000)

        ids = [_id_numerico(r) for r in resultados[: args.k]]
        hit_rank = None
        for i, rid in enumerate(ids, 1):
            if rid in esperados:
                hit_rank = i
                break
        recall, mrr, top1 = _metricas(hit_rank, args.k)
        recalls.append(recall)
        mrrs.append(mrr)
        top1s.append(top1)
        fila = {
            "query": query,
            "expected": esperados,
            "top_ids": ids,
            "top_raw_ids": [r.get("id") for r in resultados[: args.k]],
            "hit_rank": hit_rank,
            "recall_at_k": recall,
            "mrr_at_k": mrr,
            "top1": top1,
            "elapsed_ms": elapsed_ms,
            "note": caso.get("note", ""),
        }
        if error:
            fila["error"] = error
        filas.append(fila)

        if not args.quiet:
            marca = f"✅ #{hit_rank}" if hit_rank else "❌"
            print(f"{marca:>6}  {query!r}")
            print(f"        top={ids} esperados={esperados} ({elapsed_ms} ms)")

    metrics = {
        "recall_at_k": round(sum(recalls) / len(recalls), 4),
        "mrr_at_k": round(sum(mrrs) / len(mrrs), 4),
        "top1_accuracy": round(sum(top1s) / len(top1s), 4),
        "k": args.k,
        "n": len(filas),
    }
    print("\nRESUMEN")
    print(f"  Recall@{args.k}: {metrics['recall_at_k']:.3f}")
    print(f"  MRR@{args.k}:    {metrics['mrr_at_k']:.3f}")
    print(f"  Top-1:       {metrics['top1_accuracy']:.3f}")

    salida = {
        "module": args.module,
        "rerank": args.rerank,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "metrics": metrics,
        "cases": filas,
    }
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as fh:
            json.dump(salida, fh, ensure_ascii=False, indent=2)
        print("  JSON:", args.json_out)

    if args.baseline:
        with open(args.baseline, encoding="utf-8") as fh:
            base = json.load(fh)
        bm = base.get("metrics") or {}
        print("\nCONTRA LÍNEA BASE")
        for clave in ("recall_at_k", "mrr_at_k", "top1_accuracy"):
            if clave in bm:
                delta = metrics.get(clave, 0.0) - float(bm[clave])
                print(f"  {clave}: {float(bm[clave]):.3f} → {metrics.get(clave, 0.0):.3f} ({delta:+.3f})")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
