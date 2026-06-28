#!/usr/bin/env python3
"""hipocampo_health.py v1.0 — Autodiagnóstico del sistema Hipocampo.

Verifica todos los componentes críticos y reporta su estado.
Puede ejecutarse standalone o desde el MCP server.

Uso:
    python3 scripts/hipocampo_health.py              # health check completo
    python3 scripts/hipocampo_health.py --json       # salida JSON
    python3 scripts/hipocampo_health.py --repair     # intenta reparar
"""

import os
import sys
import json
import time
import subprocess
import logging

logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
logger = logging.getLogger("hipocampo_health")

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
PYTHON_BIN = sys.executable

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from hipocampo.db import get_conn, load_config


def check_postgresql():
    """Verifica conexión a PostgreSQL y existencia de tablas."""
    results = {"status": "ok", "checks": {}}
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT 1")
        results["checks"]["connection"] = "ok"

        for table in ["memoria_vectorial", "memory_items", "memory_categories", "query_stats", "watches"]:
            cur.execute("SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name=%s)", (table,))
            exists = cur.fetchone()[0]
            results["checks"][f"table_{table}"] = "ok" if exists else "missing"
            if not exists:
                results["status"] = "degraded"

        cur.execute("SELECT count(*) FROM memoria_vectorial")
        results["checks"]["memoria_vectorial_count"] = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM memory_items")
        results["checks"]["memory_items_count"] = cur.fetchone()[0]

        cur.close()
        conn.close()
    except Exception as e:
        results["status"] = "error"
        results["checks"]["connection"] = str(e)
    return results


def check_nvidia_api():
    """Verifica que la NVIDIA API key sea funcional."""
    results = {"status": "ok", "checks": {}}
    api_key = os.getenv("NVIDIA_API_KEY", "")
    if not api_key or api_key == "":
        results["status"] = "error"
        results["checks"]["api_key_present"] = "missing"
        return results

    results["checks"]["api_key_present"] = "ok"
    try:
        from openai import OpenAI

        client = OpenAI(
            base_url="https://integrate.api.nvidia.com/v1",
            api_key=api_key,
        )
        t0 = time.time()
        resp = client.embeddings.create(
            input="health check probe",
            model="nvidia/nv-embedqa-e5-v5",
            encoding_format="float",
            extra_body={"input_type": "query"},
        )
        latency = time.time() - t0
        results["checks"]["embedding_generation"] = "ok"
        results["checks"]["embedding_latency_s"] = round(latency, 2)
        results["checks"]["embedding_dim"] = len(resp.data[0].embedding)
        if latency > 5:
            results["status"] = "degraded"
            results["checks"]["embedding_latency_note"] = "alta latencia (>5s)"
    except Exception as e:
        results["status"] = "error"
        results["checks"]["embedding_generation"] = str(e)
    return results


def check_disk_space():
    """Verifica espacio en disco disponible."""
    results = {"status": "ok", "checks": {}}
    try:
        st = os.statvfs("/")
        free_gb = (st.f_frsize * st.f_bavail) / (1024**3)
        results["checks"]["disk_free_gb"] = round(free_gb, 1)
        if free_gb < 1:
            results["status"] = "error"
            results["checks"]["disk_note"] = "menos de 1GB libre"
        elif free_gb < 5:
            results["status"] = "degraded"
            results["checks"]["disk_note"] = "menos de 5GB libre"
    except Exception as e:
        results["status"] = "error"
        results["checks"]["disk_space"] = str(e)
    return results


def check_extensions():
    """Verifica extensiones de PostgreSQL."""
    results = {"status": "ok", "checks": {}}
    try:
        conn = get_conn()
        cur = conn.cursor()
        for ext in ["vector", "pg_trgm"]:
            cur.execute("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname=%s)", (ext,))
            exists = cur.fetchone()[0]
            results["checks"][f"extension_{ext}"] = "ok" if exists else "missing"
            if not exists:
                results["status"] = "degraded"
        cur.close()
        conn.close()
    except Exception as e:
        results["status"] = "error"
        results["checks"]["extensions_error"] = str(e)
    return results


def full_health_check():
    """Ejecuta todos los health checks y retorna resultado consolidado."""
    load_config()
    results = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "overall": "ok",
        "checks": {},
    }
    checks = {
        "postgresql": check_postgresql(),
        "nvidia_api": check_nvidia_api(),
        "disk_space": check_disk_space(),
        "extensions": check_extensions(),
    }
    for name, result in checks.items():
        results["checks"][name] = result["checks"]
        if result["status"] == "error":
            results["overall"] = "error"
        elif result["status"] == "degraded" and results["overall"] == "ok":
            results["overall"] = "degraded"
    return results


def auto_repair():
    """Intenta reparar problemas detectados automáticamente."""
    load_config()
    report = {"repaired": [], "failed": [], "skipped": []}

    pg = check_postgresql()
    if pg["status"] == "error":
        try:
            subprocess.run(["sudo", "systemctl", "start", "postgresql"], capture_output=True, text=True, timeout=30)
            retry = check_postgresql()
            if retry["status"] == "ok":
                report["repaired"].append("postgresql_service")
            else:
                report["failed"].append("postgresql_service")
        except Exception as e:
            report["failed"].append(f"postgresql_service: {e}")
    else:
        report["skipped"].append("postgresql_ok")

    for table in ["memoria_vectorial", "memory_items", "memory_categories"]:
        check = pg.get("checks", {}).get(f"table_{table}", "missing")
        if check == "missing":
            schema_path = os.path.join(os.path.dirname(SCRIPTS_DIR), "esquema.sql")
            if os.path.exists(schema_path):
                try:
                    conn = get_conn()
                    cur = conn.cursor()
                    with open(schema_path) as f:
                        cur.execute(f.read())
                    conn.commit()
                    cur.close()
                    conn.close()
                    report["repaired"].append(f"table_{table}_created")
                except Exception as e:
                    report["failed"].append(f"table_{table}: {e}")
            else:
                report["failed"].append(f"schema_not_found_{schema_path}")

    nv = check_nvidia_api()
    if nv["status"] == "error":
        report["failed"].append("nvidia_api_key_check_env")
    else:
        report["skipped"].append("nvidia_api_ok")

    return report


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Health check y auto-repair del sistema Hipocampo")
    parser.add_argument("--repair", action="store_true", help="Ejecutar auto-repair en lugar de health check")
    parser.add_argument("--json", action="store_true", help="Salida en formato JSON")
    args = parser.parse_args()

    if args.repair:
        result = auto_repair()
    else:
        result = full_health_check()

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        overall = result.get("overall", result.get("status", "unknown"))
        emoji = {"ok": "✅", "degraded": "⚠️", "error": "❌"}.get(overall, "❓")
        print(f"{emoji} Health: {overall.upper()}")
        print(f"   Timestamp: {result.get('timestamp', 'N/A')}")
        for category, checks in result.get("checks", {}).items():
            print(f"\n   📊 {category}:")
            if isinstance(checks, dict):
                for k, v in checks.items():
                    print(f"      {k}: {v}")
            else:
                print(f"      {checks}")
        if "repaired" in result:
            print(f"\n   🔧 Reparados: {result['repaired']}")
            print(f"   ❌ Fallaron: {result['failed']}")
            print(f"   ⏭️  Omitidos: {result['skipped']}")
