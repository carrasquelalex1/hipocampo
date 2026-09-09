"""Trade Knowledge Classification for Hipocampo v4.3.

Implements 4 layers of protection for latent knowledge preservation:
1. Category "oficio" - knowledge that never decays
2. Automatic reusability classification
3. Domain-specific decay profiles
4. Periodic review with spaced repetition
"""

import json
import re
import logging
from datetime import date

logger = logging.getLogger(__name__)

# ─── CONSTANTS ───────────────────────────────────────────────────────────

TRADE_KNOWLEDGE_PATTERNS = [
    r"extension.*(?:postgis|pg_trgm|pgvector)",
    r"(?:obligatorio|requerido|necesario).*antes de",
    r"(?:nunca|siempre|jamás).*(?:hacer|aplicar|usar)",
    r"si\s+(?:no|falta|omita).*(?:rompe|falla|crash|error)",
    r"(?:password|credenciales?|api.?key).*(?:hardcodeado|fallback|env)",
    r"(?:backup|respaldo).*(?:antes|pre|siempre)",
    r"(?:dependencias?|includes?|require).*(?:rompe|afecta|cambia)",
    r"(?:session_start|ob_start|header).*(?:rompe|bloquea|causa)",
    r"(?:FETCH|curl|request).*(?:URL relativa|siempre.*AJAX_BASE)",
    r"(?:nunca|jamás).*(?:exponer|log.*password|commit.*secret)",
    r"(?:CSRF|token).*(?:validar|verificar|generar)",
    r"REGLA.*:(?:NUNCA|SIEMPRE|NO)",
    r"LECCIÓN.*:",
    r"FALLÓ.*porque.*solución.*:",
]

TRADE_DOMAINS = {
    "postgresql",
    "postgis",
    "pgvector",
    "pg_trgm",
    "dhis2",
    "tomcat",
    "apache",
    "php",
    "security",
    "deploy",
    "backup",
    "restauracion",
    "docker",
    "systemd",
    "cron",
    "nginx",
    "node",
    "react",
    "nextjs",
}

HIGH_REUSABILITY_PATTERNS = [
    r"(?:extension|plugin|modulo).*(?:obligatorio|requerido|necesario)",
    r"(?:nunca|siempre|jamás|no).*(?:hacer|aplicar|usar|olvidar)",
    r"si\s+(?:no|falta|omita).*(?:rompe|falla|crash|error|404)",
    r"(?:password|credenciales?|api.?key).*(?:hardcodeado|fallback|env)",
    r"(?:backup|respaldo).*(?:antes|pre|siempre)",
    r"(?:REGLA|LECCIÓN|FALLÓ|CRÍTICO).*:",
    r"(?:session_start|ob_start|header).*(?:rompe|bloquea|causa)",
    r"(?:FETCH|curl|request).*(?:URL relativa|AJAX_BASE)",
    r"(?:nunca|jamás).*(?:exponer|log.*password|commit.*secret)",
]

LOW_REUSABILITY_PATTERNS = [
    r"(?:cambié|ajusté|moví).*(?:color|padding|margin|font)",
    r"(?:fix|arreglo).*(?:específico|puntual)",
    r"(?:eliminad|borrad|removid).*(?:prueba|test|datos de prueba)",
    r"(?:usuario|user).*(?:\d{3,}).*(?:prueba|test)",
]

DECAY_PROFILES = {
    "infrastructure": {"decay_days": 180, "description": "PostgreSQL, DHIS2, Apache, PHP, seguridad"},
    "project_specific": {"decay_days": 90, "description": "Fixes específicos pero transferibles"},
    "temporary": {"decay_days": 14, "description": "Datos de prueba, ajustes cosméticos"},
}

DEFAULT_DECAY_DAYS = 60


# ─── CLASSIFICATION FUNCTIONS ────────────────────────────────────────────


def classify_reusability(content: str, categories: list | None = None) -> dict:
    content_lower = (content or "").lower()
    cats = set(categories or [])
    high_score = sum(1 for p in HIGH_REUSABILITY_PATTERNS if re.search(p, content_lower))
    low_score = sum(1 for p in LOW_REUSABILITY_PATTERNS if re.search(p, content_lower))
    has_trade_domain = bool(cats & TRADE_DOMAINS)

    if high_score >= 2 or has_trade_domain:
        return {"reusability": "high", "domain_profile": "infrastructure", "auto_promote": True}
    elif high_score >= 1 or low_score == 0:
        return {"reusability": "medium", "domain_profile": "project_specific", "auto_promote": False}
    else:
        return {"reusability": "low", "domain_profile": "temporary", "auto_promote": False}


def classify_trade_knowledge(content: str, categories: list | None = None) -> dict:
    content_lower = (content or "").lower()
    cats = set(categories or [])
    has_trade_pattern = any(re.search(p, content_lower) for p in TRADE_KNOWLEDGE_PATTERNS)
    has_trade_domain = bool(cats & TRADE_DOMAINS)

    if has_trade_pattern or has_trade_domain:
        cls = classify_reusability(content, categories)
        return {"is_trade": True, "reusability": cls["reusability"], "domain_profile": cls["domain_profile"]}
    cls = classify_reusability(content, categories)
    return {"is_trade": False, "reusability": cls["reusability"], "domain_profile": cls["domain_profile"]}


def get_decay_cutoff(domain_profile: str) -> int:
    return DECAY_PROFILES.get(domain_profile, {}).get("decay_days", DEFAULT_DECAY_DAYS)


# ─── SERVER INTEGRATION HELPERS ──────────────────────────────────────────


def build_trade_knowledge_metadata(
    content: str, categories: list | None = None, existing_meta: dict | None = None
) -> dict:
    result = classify_trade_knowledge(content, categories)
    meta = existing_meta or {}
    meta["trade_knowledge"] = result["is_trade"]
    meta["reusability"] = result["reusability"]
    meta["domain_profile"] = result["domain_profile"]
    if result["is_trade"] and result["reusability"] == "high" and meta.get("nivel") == "episodica":
        meta["nivel"] = "semantica"
        meta["consolidated_at"] = str(date.today())
        meta["consolidated_reason"] = "auto_high_trade_reusability"
    return meta


def apply_classification_to_row(row_id: int, content: str, categories: list | None = None):
    try:
        from hipocampo.db import get_conn

        result = classify_trade_knowledge(content, categories)
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT metadatos FROM memoria_vectorial WHERE id=%s", (row_id,))
        row = cur.fetchone()
        if row:
            meta = json.loads(row[0]) if row[0] else {}
            meta["trade_knowledge"] = result["is_trade"]
            meta["reusability"] = result["reusability"]
            meta["domain_profile"] = result["domain_profile"]
            if result["is_trade"] and result["reusability"] == "high" and meta.get("nivel") == "episodica":
                meta["nivel"] = "semantica"
                meta["consolidated_at"] = str(date.today())
                meta["consolidated_reason"] = "migration_trade_knowledge"
            cur.execute("UPDATE memoria_vectorial SET metadatos=%s WHERE id=%s", (json.dumps(meta), row_id))
            conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        logger.warning("Classification failed for id=%s: %s", row_id, e)
