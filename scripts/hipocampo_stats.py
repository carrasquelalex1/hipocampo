#!/usr/bin/env python3
"""hipocampo_stats.py v1.0 — Métricas y ajuste dinámico de Hipocampo.

Trackea rendimiento de queries, ajusta thresholds SSC automáticamente
y expone estadísticas para auto-mejora.

Uso:
    python3 scripts/hipocampo_stats.py                    # mostrar stats
    python3 scripts/hipocampo_stats.py --record           # registrar métrica (modo pipe)
    python3 scripts/hipocampo_stats.py --analyze          # análisis + recomendaciones
    python3 scripts/hipocampo_stats.py --tune             # ajustar thresholds
"""

import os
import sys
import json
import time
import logging

logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
logger = logging.getLogger("hipocampo_stats")

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(SCRIPTS_DIR, "hipocampo_hybrid_config.json")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from hipocampo.db import get_conn, load_config

DEFAULT_THRESHOLDS = {
    "vectorial_confidence_min": 0.65,
    "trigram_confidence_min": 0.35,
    "alpha": 0.5,
    "beta": 0.5,
}

LATENCY_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS query_stats (
    id SERIAL PRIMARY KEY,
    query_hash VARCHAR(64),
    query_text TEXT,
    latency_ms INTEGER,
    results_count INTEGER,
    method VARCHAR(20),
    top_score REAL,
    avg_score REAL,
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_query_stats_created ON query_stats(created_at);
"""


def ensure_stats_table():
    """Crea la tabla de estadísticas si no existe."""
    conn = get_conn()
    cur = conn.cursor()
    for stmt in LATENCY_TABLE_SQL.split(";"):
        if stmt.strip():
            cur.execute(stmt)
    conn.commit()
    cur.close()
    conn.close()


def record_query(query_text, latency_ms, results_count, method, top_score, avg_score):
    """Registra una métrica de query en la tabla query_stats."""
    import hashlib

    query_hash = hashlib.sha256(query_text.encode()).hexdigest()[:12]
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO query_stats (query_hash, query_text, latency_ms, results_count, method, top_score, avg_score)
           VALUES (%s, %s, %s, %s, %s, %s, %s)""",
        (query_hash, query_text[:200], int(latency_ms), results_count, method, float(top_score), float(avg_score)),
    )
    conn.commit()
    cur.close()
    conn.close()


def get_stats(last_hours=24):
    """Obtiene estadísticas de las últimas N horas."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        f"""SELECT count(*),
                  COALESCE(avg(latency_ms), 0) as avg_latency,
                  COALESCE(percentile_cont(0.5) WITHIN GROUP (ORDER BY latency_ms), 0) as p50_latency,
                  COALESCE(percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms), 0) as p95_latency,
                  COALESCE(avg(results_count), 0) as avg_results,
                  COALESCE(avg(top_score), 0) as avg_top_score
           FROM query_stats
           WHERE created_at > NOW() - interval '{last_hours} hours'""",
    )
    row = cur.fetchone()
    cur.execute(
        f"SELECT method, count(*) as cnt, avg(latency_ms) as avg_lat FROM query_stats WHERE created_at > NOW() - interval '{last_hours} hours' GROUP BY method ORDER BY cnt DESC"
    )
    by_method = cur.fetchall()
    cur.close()
    conn.close()
    return {
        "total_queries": row[0],
        "avg_latency_ms": round(row[1], 1),
        "p50_latency_ms": round(row[2], 1),
        "p95_latency_ms": round(row[3], 1),
        "avg_results": round(row[4], 1),
        "avg_top_score": round(row[5], 3),
        "by_method": [{"method": m[0], "count": m[1], "avg_latency": round(m[2], 1)} for m in by_method],
    }


def analyze():
    """Analiza el rendimiento y da recomendaciones."""
    ensure_stats_table()
    stats = get_stats(168)
    config = {}
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH) as f:
            config = json.load(f)

    recommendations = []
    issues = []

    if stats["total_queries"] == 0:
        recommendations.append("No hay datos de queries aún. Realiza búsquedas para generar métricas.")
        return {"stats": stats, "config": config, "recommendations": recommendations, "issues": issues}

    if stats["p95_latency_ms"] > 10000:
        issues.append(f"⚠️ Latencia P95 muy alta: {stats['p95_latency_ms']}ms (>10s)")
        recommendations.append(
            "Alta latencia detectada. Sugerir: reducir top-K en búsqueda vectorial, o verificar API NVIDIA."
        )
    elif stats["p95_latency_ms"] > 5000:
        recommendations.append(
            f"Latencia P95 de {stats['p95_latency_ms']}ms. Considerar reducir parámetro 'top_k' en SSC."
        )

    if stats["avg_top_score"] < 15:
        recommendations.append(
            "Score promedio bajo. Los resultados no son muy relevantes. Sugerir re-calibrar pesos híbridos con hipocampo_calibrate.py"
        )

    if stats["total_queries"] < 10:
        recommendations.append("Pocos datos registrados. Continuar usando el sistema para generar más métricas.")

    return {"stats": stats, "config": config, "recommendations": recommendations, "issues": issues}


def tune_thresholds():
    """Ajusta thresholds SSC basado en las métricas acumuladas."""
    ensure_stats_table()
    config = {}
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH) as f:
            config = json.load(f)
    else:
        config = dict(DEFAULT_THRESHOLDS)

    stats = get_stats(168)
    if stats["total_queries"] < 5:
        return {"status": "skipped", "reason": "Pocos datos para ajustar", "config": config}

    changes = {}
    old_config = dict(config)

    MAX_ALPHA = 0.6
    MIN_ALPHA = 0.4
    MAX_CONFIDENCE = 0.75
    MIN_CONFIDENCE = 0.5

    if stats["p95_latency_ms"] > 8000 and config.get("vectorial_confidence_min", 0.65) < MAX_CONFIDENCE:
        nuevo_vc = min(MAX_CONFIDENCE, config.get("vectorial_confidence_min", 0.65) + 0.05)
        config["vectorial_confidence_min"] = nuevo_vc
        changes["vectorial_confidence_min"] = f"{old_config.get('vectorial_confidence_min', 0.65):.2f} → {nuevo_vc:.2f}"

    if stats["p95_latency_ms"] < 2000 and config.get("vectorial_confidence_min", 0.65) > MIN_CONFIDENCE:
        nuevo_vc = max(MIN_CONFIDENCE, config.get("vectorial_confidence_min", 0.65) - 0.05)
        config["vectorial_confidence_min"] = nuevo_vc
        changes["vectorial_confidence_min"] = f"{old_config.get('vectorial_confidence_min', 0.65):.2f} → {nuevo_vc:.2f}"

    if stats["avg_top_score"] < 15 and stats["total_queries"] > 10:
        new_alpha = min(MAX_ALPHA, config.get("alpha", 0.5) + 0.05)
        config["alpha"] = new_alpha
        config["beta"] = 1 - new_alpha
        changes["alpha"] = f"{old_config.get('alpha', 0.5):.1f} → {new_alpha:.1f}"

    if stats["avg_top_score"] > 30 and stats["total_queries"] > 10:
        new_alpha = max(MIN_ALPHA, config.get("alpha", 0.5) - 0.05)
        config["alpha"] = new_alpha
        config["beta"] = 1 - new_alpha
        changes["alpha"] = f"{old_config.get('alpha', 0.5):.1f} → {new_alpha:.1f}"

    config["last_tuned"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    with open(CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)

    return {"status": "tuned" if changes else "no_changes", "changes": changes, "config": config}


def format_result(data):
    """Formatea resultados para mostrar."""
    lines = []
    if "stats" in data:
        s = data["stats"]
        lines.append(f"📊 {s.get('total_queries', 'N/A')} queries en 7 días")
        lines.append(
            f"   Latencia: avg={s.get('avg_latency_ms', 'N/A')}ms  P50={s.get('p50_latency_ms', 'N/A')}ms  P95={s.get('p95_latency_ms', 'N/A')}ms"
        )
        lines.append(
            f"   Resultados promedio: {s.get('avg_results', 'N/A')}  Score avg: {s.get('avg_top_score', 'N/A')}"
        )
        for m in s.get("by_method", []):
            lines.append(f"   Método '{m['method']}': {m['count']} queries, {m['avg_latency']}ms avg")
    if "recommendations" in data:
        for r in data["recommendations"]:
            lines.append(f"   💡 {r}")
    if "issues" in data:
        for i in data["issues"]:
            lines.append(f"   {i}")
    if "changes" in data and data["changes"]:
        lines.append(f"   🔧 Ajustes aplicados: {data['changes']}")
    if "config" in data:
        lines.append(
            f"   ⚙️ Config actual: α={data['config'].get('alpha', '?')} β={data['config'].get('beta', '?')} threshold_v={data['config'].get('vectorial_confidence_min', '?')}"
        )
    return "\n".join(lines)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Estadísticas y ajuste dinámico del motor de búsqueda")
    parser.add_argument("--analyze", action="store_true", help="Mostrar análisis de rendimiento")
    parser.add_argument("--tune", action="store_true", help="Ajustar thresholds automáticamente")
    parser.add_argument("--hours", type=int, default=168, help="Ventana de horas para estadísticas (default 168)")
    parser.add_argument(
        "--record",
        nargs=6,
        metavar=("QUERY", "LATENCY", "RESULTS", "METHOD", "TOP_SCORE", "AVG_SCORE"),
        help="Registrar una query manualmente",
    )
    args = parser.parse_args()

    load_config()
    ensure_stats_table()

    if args.record:
        record_query(
            args.record[0],
            float(args.record[1]),
            int(args.record[2]),
            args.record[3],
            float(args.record[4]),
            float(args.record[5]),
        )
        print("✅ Recorded")
    elif args.analyze:
        result = analyze()
        print(format_result(result))
    elif args.tune:
        result = tune_thresholds()
        print(format_result(result))
    else:
        stats = get_stats(args.hours)
        print(format_result({"stats": stats}))
