#!/usr/bin/env python3
"""hipocampo_calibrate.py v1.0 — Calibración de Ponderación Híbrida BIRE.

Encuentra los pesos óptimos (alpha, beta) para combinar puntuaciones
vectoriales y léxicas mediante validación cruzada sobre un conjunto
de consultas etiquetadas.

Uso:
    python3 hipocampo_calibrate.py
"""

import sys
import os
import json
import math

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hipocampo_search import (
    expandir_consulta,
    generar_patrones_ILIKE,
    buscar_vectorial,
    buscar_lexico_memoria_vectorial,
    buscar_lexico_memory_items,
)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from hipocampo.db import get_conn, load_config

load_config()

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hipocampo_hybrid_config.json")

# ─── DATASET ETIQUETADO ─────────────────────────────────────────────────────

LABELED_QUERIES = [
    {
        "query": "plantas medicinales",
        "relevant": [
            "Al usuario tambien le gusta el Oregano Orejon como planta medicinal",
            "el usuario planta malojillo",
            "Al usuario le gusta el Malojillo como planta medicinal",
            "el usuario planta oregano orejon",
        ],
    },
    {
        "query": "malojillo",
        "relevant": [
            "el usuario planta malojillo",
            "Al usuario le gusta el Malojillo como planta medicinal",
        ],
    },
    {
        "query": "orégano orejón",
        "relevant": [
            "Al usuario tambien le gusta el Oregano Orejon como planta medicinal",
            "el usuario planta oregano orejon",
        ],
    },
    {
        "query": "familia",
        "relevant": [
            "Haydee es la hermana de Gaudi Concepcion Puente Godoy (esposa del usuario), por lo tanto es cuñada del usuario. Es interesada: siempre busca al usuario cuando le conviene y luego le deja de hablar.",
            "The user is married to Gaudi Concepción Puente Godoy",
            "La esposa del usuario se llama Gaudi Concepción Puente Godoy",
            "La esposa del usuario es Gaudi Concepción Puente Godoy",
            "El usuario está casado con Gaudi Concepción Puente Godoy",
        ],
    },
    {
        "query": "cuñada",
        "relevant": [
            "Haydee es la hermana de Gaudi Concepcion Puente Godoy (esposa del usuario), por lo tanto es cuñada del usuario. Es interesada: siempre busca al usuario cuando le conviene y luego le deja de hablar.",
        ],
    },
    {
        "query": "esposa",
        "relevant": [
            "The user is married to Gaudi Concepción Puente Godoy",
            "La esposa del usuario se llama Gaudi Concepción Puente Godoy",
            "La esposa del usuario es Gaudi Concepción Puente Godoy",
            "El usuario está casado con Gaudi Concepción Puente Godoy",
        ],
    },
    {
        "query": "color azul",
        "relevant": [
            "Al usuario le gusta el color azul rey",
        ],
    },
    {
        "query": "hijo",
        "relevant": [
            "El hijo del usuario se llama Gabriel Alexander",
            "El usuario tiene un hijo llamado Gabriel Alexander",
            "El usuario tiene a Gabriel Alexander en casa",
        ],
    },
    {
        "query": "hija",
        "relevant": [
            "La hija del usuario se llama Gabriela Estefania",
        ],
    },
    {
        "query": "proyecto contable",
        "relevant": [
            "Proyecto: ContaVen (ERP Contable Bimonetario)",
        ],
    },
    {
        "query": "sistema contabilidad",
        "relevant": [
            "Proyecto: ContaVen (ERP Contable Bimonetario)",
        ],
    },
    {
        "query": "telegram bot",
        "relevant": [
            "musica_bot",
            "amarte75_bot",
        ],
    },
]


# ─── MÉTRICAS DE EVALUACIÓN ─────────────────────────────────────────────────


def ndcg_at_k(resultados, relevant_set, k=10):
    """NDCG (Normalized Discounted Cumulative Gain) @ k."""
    dcg = 0.0
    idcg = 0.0
    for i, r in enumerate(resultados[:k]):
        clave = r["contenido"][:120].lower()
        rel = 1.0 if any(clave in rel[:120].lower() or rel[:120].lower() in clave for rel in relevant_set) else 0.0
        dcg += rel / math.log2(i + 2)

    for i in range(min(len(relevant_set), k)):
        idcg += 1.0 / math.log2(i + 2)

    return dcg / idcg if idcg > 0 else 0.0


def precision_at_k(resultados, relevant_set, k=10):
    """Precisión @ k."""
    count = 0
    for r in resultados[:k]:
        clave = r["contenido"][:120].lower()
        if any(clave in rel[:120].lower() or rel[:120].lower() in clave for rel in relevant_set):
            count += 1
    return count / min(k, len(resultados)) if resultados else 0.0


def recall_at_k(resultados, relevant_set, k=10):
    """Recall @ k."""
    encontrados = 0
    for r in resultados[:k]:
        clave = r["contenido"][:120].lower()
        if any(clave in rel[:120].lower() or rel[:120].lower() in clave for rel in relevant_set):
            encontrados += 1
    return encontrados / len(relevant_set) if relevant_set else 0.0


def evaluate(resultados, relevant_set):
    """Evalúa un ranking contra el ground truth."""
    ndcg = ndcg_at_k(resultados, relevant_set, k=10)
    prec = precision_at_k(resultados, relevant_set, k=10)
    rec = recall_at_k(resultados, relevant_set, k=10)
    f1 = 2 * prec * rec / (prec + rec) if (prec + rec) > 0 else 0.0
    return {"ndcg": ndcg, "precision": prec, "recall": rec, "f1": f1}


# ─── FUSIÓN HÍBRIDA CALIBRADA ──────────────────────────────────────────────


def fusionar_hibrido(vectorial, lexico_mv, lexico_mi, alpha=0.5):
    """Fusión híbrida: combina vectorial y léxico con peso alpha.

    Aplica puntuación híbrida a TODOS los resultados:
      hybrid_score = alpha * max_vec_score + (1-alpha) * max_lex_score

    alpha = 1.0 → solo vectorial
    alpha = 0.0 → solo léxico
    alpha = 0.3 → 30% vectorial + 70% léxico
    """
    todos = vectorial + lexico_mv + lexico_mi

    grupos = {}
    for r in todos:
        clave = r["contenido"][:120].lower()
        if clave in grupos:
            existente = grupos[clave]
            existente["vec_score"] = max(existente.get("vec_score", 0), r["score"] if r["method"] == "vectorial" else 0)
            existente["lex_score"] = max(existente.get("lex_score", 0), r["score"] if r["method"] != "vectorial" else 0)
            # Recalcular híbrido con el nuevo score
            raw = alpha * existente["vec_score"] + (1 - alpha) * existente["lex_score"]
            existente["score"] = round(raw, 1)
        else:
            r["vec_score"] = r["score"] if r["method"] == "vectorial" else 0
            r["lex_score"] = r["score"] if r["method"] != "vectorial" else 0
            raw = alpha * r["vec_score"] + (1 - alpha) * r["lex_score"]
            r["score"] = round(raw, 1)
            grupos[clave] = r

    fusionados = sorted(grupos.values(), key=lambda x: x["score"], reverse=True)
    return fusionados


# ─── CALIBRACIÓN ────────────────────────────────────────────────────────────


def run_calibration():
    """Ejecuta validación cruzada para encontrar el alpha óptimo."""
    conn = get_conn()
    cur = conn.cursor()

    alpha_values = [i / 10.0 for i in range(0, 11)]  # 0.0, 0.1, ..., 1.0

    results_by_alpha = {alpha: {"ndcg": [], "precision": [], "recall": [], "f1": []} for alpha in alpha_values}

    for q in LABELED_QUERIES:
        query = q["query"]
        relevant = q["relevant"]

        terms = expandir_consulta(query)
        patterns = generar_patrones_ILIKE(terms)

        vectorial = buscar_vectorial(cur, query)
        lexico_mv = buscar_lexico_memoria_vectorial(cur, patterns, terms)
        lexico_mi = buscar_lexico_memory_items(cur, patterns, terms)

        for alpha in alpha_values:
            fusionados = fusionar_hibrido(vectorial, lexico_mv, lexico_mi, alpha=alpha)
            metrics = evaluate(fusionados, relevant)
            for k in metrics:
                results_by_alpha[alpha][k].append(metrics[k])

    cur.close()
    conn.close()

    # Promediar métricas por alpha
    avg_metrics = {}
    for alpha in alpha_values:
        avg = {}
        for k in results_by_alpha[alpha]:
            vals = results_by_alpha[alpha][k]
            avg[k] = sum(vals) / len(vals) if vals else 0.0
        avg_metrics[alpha] = avg

    # Encontrar alpha óptimo (por F1)
    best_alpha = max(avg_metrics, key=lambda a: avg_metrics[a]["f1"])
    best_ndcg = max(avg_metrics, key=lambda a: avg_metrics[a]["ndcg"])
    best_precision = max(avg_metrics, key=lambda a: avg_metrics[a]["precision"])

    return avg_metrics, best_alpha, best_ndcg, best_precision


def print_results(avg_metrics, best_alpha, best_ndcg, best_precision):
    """Muestra resultados de la calibración."""
    print("=" * 70)
    print("🔬 BIRE Calibration — Ponderación Híbrida v1.0")
    print("=" * 70)
    print(f"\n📊 Dataset: {len(LABELED_QUERIES)} consultas etiquetadas")
    print()

    print(f"{'Alpha':<8} {'NDCG@10':<10} {'Precision@10':<14} {'Recall@10':<12} {'F1':<8}")
    print("-" * 55)
    for alpha in sorted(avg_metrics.keys()):
        m = avg_metrics[alpha]
        marker = " ◀ ÓPTIMO" if alpha == best_alpha else ""
        print(f"{alpha:<8.1f} {m['ndcg']:<10.4f} {m['precision']:<14.4f} {m['recall']:<12.4f} {m['f1']:<8.4f}{marker}")

    print()
    print(f"🏆 Mejor F1:         alpha={best_alpha:.1f} (F1={avg_metrics[best_alpha]['f1']:.4f})")
    print(f"🏆 Mejor NDCG:       alpha={best_ndcg:.1f} (NDCG={avg_metrics[best_ndcg]['ndcg']:.4f})")
    print(f"🏆 Mejor Precisión:  alpha={best_precision:.1f} (P={avg_metrics[best_precision]['precision']:.4f})")
    print()

    return best_alpha


def save_config(alpha, filepath=CONFIG_PATH):
    """Guarda la configuración híbrida calibrada."""
    config = {
        "alpha": alpha,
        "beta": round(1.0 - alpha, 1),
        "description": f"Ponderación híbrida calibrada: {alpha * 100:.0f}% vectorial + {(1 - alpha) * 100:.0f}% léxico",
        "calibrated_at": "2026-05-24",
        "dataset_size": len(LABELED_QUERIES),
    }
    with open(filepath, "w") as f:
        json.dump(config, f, indent=2)
    print(f"💾 Config guardada en {filepath}")
    print(json.dumps(config, indent=2))


def load_config(filepath=CONFIG_PATH):
    """Carga la configuración híbrida."""
    try:
        with open(filepath) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"alpha": 0.5, "beta": 0.5}


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Calibración híbrida BIRE — ajusta ponderación vectorial vs léxica")
    parser.add_argument(
        "--save", action="store_true", default=True, help="Guardar configuración calibrada (default: True)"
    )
    args = parser.parse_args()

    avg_metrics, best_alpha, best_ndcg, best_precision = run_calibration()
    optimal = print_results(avg_metrics, best_alpha, best_ndcg, best_precision)

    if args.save:
        save_config(optimal)
