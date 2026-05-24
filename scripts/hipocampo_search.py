#!/home/usuario/.gemini/mcp_venv/bin/python3
"""hipocampo_search.py v3.6 — BIRE con Embeddings Unificados

Algoritmo de búsqueda unificada en los dos sistemas de memoria del Hipocampo.
Usa expansión de consulta + búsqueda vectorial (ambas tablas, 768d unificado)
+ búsqueda léxica expansiva + puntuación compuesta + fusión con corte dinámico
+ expansión por tags.
"""
import psycopg2, os, json, sys, re, math
from dotenv import load_dotenv
from pgvector.psycopg2 import register_vector
from google import genai
from google.genai import types

ENV_PATH = "/home/usuario/scripts/.env"
load_dotenv(ENV_PATH)

client = genai.Client(api_key=os.getenv('GOOGLE_API_KEY'))


# ─── FASE 1: EXPANSIÓN DE CONSULTA ───────────────────────────────────────────

STEM_MAP = {
    'planta': ['planta', 'plantas', 'vegetal', 'hierba', 'hierbas', 'herbal'],
    'medicinal': ['medicinal', 'medicinales', 'medicina', 'curativa', 'curativo'],
    'gusta': ['gusta', 'gustan', 'gustaba', 'favorita', 'favorito', 'prefiere', 'preferida'],
    'té': ['té', 'te', 'infusión', 'infusion', 'tisana'],
    'malojillo': ['malojillo', 'malojilla', 'hierba', 'limón', 'lemongrass', 'citronela'],
    'orégano': ['orégano', 'oregano', 'orejón', 'orejon'],
    'nombre': ['nombre', 'nombres', 'llama', 'llaman', 'llamaba'],
    'grupo': ['grupo', 'grupos', 'integrantes', 'miembros', 'quienes'],
    'color': ['color', 'colores', 'tono', 'tonalidad'],
    'azul': ['azul', 'rey', 'marino', 'celeste'],
    'amarillo': ['amarillo', 'amarilla', 'dorado'],
}

SINONIMOS_GLOBALES = {
    'medicinal': ['curativa', 'natural', 'botánica', 'herbal'],
    'planta': ['vegetal', 'hierba', 'arbusto', 'flor'],
    'gustar': ['preferir', 'encantar', 'fascinar', 'agradar'],
}

def expandir_consulta(query):
    query_lower = query.lower().strip()
    tokens_originales = re.findall(r'\w+', query_lower)
    tokens_expandidos = set(tokens_originales)

    for token in tokens_originales:
        if token in STEM_MAP:
            tokens_expandidos.update(STEM_MAP[token])
        for raiz, vars in STEM_MAP.items():
            if raiz in token or token in raiz:
                tokens_expandidos.update(vars)
        if token in SINONIMOS_GLOBALES:
            tokens_expandidos.update(SINONIMOS_GLOBALES[token])

    terms = sorted(tokens_expandidos)
    return terms


def generar_patrones_ILIKE(terms):
    return [f'%{t}%' for t in terms]


# ─── FASE 2: BÚSQUEDA VECTORIAL ──────────────────────────────────────────────

def get_embedding(text, dims=768):
    try:
        result = client.models.embed_content(
            model="gemini-embedding-001",
            contents=text,
            config=types.EmbedContentConfig(
                task_type="RETRIEVAL_QUERY",
                output_dimensionality=dims
            )
        )
        return result.embeddings[0].values
    except Exception as e:
        return None


def buscar_vectorial(cur, query, limit=50):
    query_embed = get_embedding(query, dims=768)
    if query_embed is None:
        return []

    cur.execute("""
        SELECT id, contenido, metadatos::text, code_snippet,
               1 - (embedding <=> %s::vector(768)) as similitud
        FROM memoria_vectorial
        WHERE embedding IS NOT NULL
        ORDER BY embedding <=> %s::vector(768)
        LIMIT %s
    """, (query_embed, query_embed, limit))

    results = []
    for row in cur.fetchall():
        meta = json.loads(row[2])
        results.append({
            'id': f'v{row[0]}',
            'contenido': row[1],
            'metadatos': meta,
            'code_snippet': row[3],
            'score_raw': float(row[4]),
            'score': round(float(row[4]) * 100, 1),
            'source': 'memoria_vectorial',
            'method': 'vectorial',
            'tabla': 'memoria_vectorial',
        })
    return results


def buscar_vectorial_memory_items(cur, query, limit=50):
    """Búsqueda vectorial (768d) en memory_items usando cosine similarity."""
    query_embed = get_embedding(query, dims=768)
    if query_embed is None:
        return []

    cur.execute("""
        SELECT mi.id::text, mi.summary, mi.memory_type, mi.extra::text,
               mc.name as categoria,
               1 - (mi.embedding <=> %s::vector(768)) as similitud
        FROM memory_items mi
        LEFT JOIN category_items ci ON ci.item_id = mi.id
        LEFT JOIN memory_categories mc ON mc.id = ci.category_id
        WHERE mi.embedding IS NOT NULL
        ORDER BY mi.embedding <=> %s::vector(768)
        LIMIT %s
    """, (query_embed, query_embed, limit))

    results = []
    for row in cur.fetchall():
        extra_raw = row[3]
        extra = {}
        if extra_raw:
            try:
                extra = json.loads(extra_raw) if extra_raw != 'None' else {}
            except (json.JSONDecodeError, TypeError):
                extra = {}

        score_raw = float(row[5])
        # Profile boost for vector search too (profile items get +5 in raw score)
        profile_boost = 5 if row[2] == 'profile' else 0
        score = round(min(100, (score_raw * 100) + profile_boost), 1)

        results.append({
            'id': f'vmi{row[0]}',
            'contenido': row[1],
            'metadatos': {
                'memory_type': row[2],
                'categoria': row[4] if row[4] else 'sin_categoria',
            },
            'extra': extra,
            'code_snippet': None,
            'score_raw': score_raw,
            'score': score,
            'source': 'memory_items',
            'method': 'vectorial',
            'tabla': 'memory_items',
            'memory_type': row[2],
            'categoria': row[4] if row[4] else None,
        })
    return results


# ─── FASE 3: BÚSQUEDA LÉXICA EXPANSIVA (pg_trgm + GIN Index) ───────────────

# pg_trgm similarity threshold para el operador % (default 0.3)
# Valores más bajos = más resultados, más lentos
TRGM_SIMILARITY_THRESHOLD = 0.2


def set_trgm_threshold(cur, threshold=0.2):
    """Ajusta el umbral de similitud de pg_trgm para esta sesión."""
    try:
        cur.execute(f"SET pg_trgm.similarity_threshold = {threshold};")
    except Exception:
        pass


def buscar_lexico_memoria_vectorial(cur, patterns, query_tokens, query_original=None):
    if not patterns:
        return []

    set_trgm_threshold(cur, TRGM_SIMILARITY_THRESHOLD)
    query_text = query_original or ' '.join(query_tokens)
    # Usar ILIKE con índice GIN (pg_trgm acelera ILIKE con gin_trgm_ops)
    # y ORDER BY similitud trigramática descendente para mejor ranking
    placeholders = ','.join(['%s'] * len(patterns))
    sql = f"""
        SELECT id, contenido, metadatos::text, code_snippet,
               similarity(contenido, %s) AS trgm_sim
        FROM memoria_vectorial
        WHERE contenido ILIKE ANY (ARRAY[{placeholders}])
        ORDER BY trgm_sim DESC, LENGTH(contenido) ASC
    """
    cur.execute(sql, [query_text] + patterns)
    rows = cur.fetchall()
    if not rows:
        return []

    seen_ids = set()
    results = []
    total_terms = len(query_tokens)
    for row in rows:
        if row[0] in seen_ids:
            continue
        seen_ids.add(row[0])
        meta = json.loads(row[2])
        content_lower = (row[1] or '').lower()
        match_count = sum(1 for t in query_tokens if t in content_lower)
        match_ratio = match_count / total_terms if total_terms > 0 else 0
        trgm_sim = float(row[4]) if row[4] is not None else 0.0
        exact_bonus = 15 if any(t in content_lower for t in query_tokens) else 0
        # Score híbrido: 70% match_ratio + 20% trgm_sim + 10% exact_bonus
        score = min(100, round(match_ratio * 70 + trgm_sim * 20 + exact_bonus, 1))

        results.append({
            'id': f'l{row[0]}',
            'contenido': row[1],
            'metadatos': meta,
            'code_snippet': row[3],
            'score_raw': trgm_sim,
            'score': score,
            'source': 'memoria_vectorial',
            'method': 'lexico_expansivo',
            'tabla': 'memoria_vectorial',
        })
    return results


def buscar_lexico_memory_items(cur, patterns, query_tokens, query_original=None):
    if not patterns:
        return []

    set_trgm_threshold(cur, TRGM_SIMILARITY_THRESHOLD)
    query_text = query_original or ' '.join(query_tokens)
    placeholders = ','.join(['%s'] * len(patterns))
    sql = f"""
        SELECT mi.id::text, mi.summary, mi.memory_type, mi.extra::text,
               mc.name as categoria,
               similarity(mi.summary, %s) AS trgm_sim
        FROM memory_items mi
        LEFT JOIN category_items ci ON ci.item_id = mi.id
        LEFT JOIN memory_categories mc ON mc.id = ci.category_id
        WHERE mi.summary ILIKE ANY (ARRAY[{placeholders}])
        ORDER BY trgm_sim DESC
    """
    cur.execute(sql, [query_text] + patterns)
    rows = cur.fetchall()
    if not rows:
        return []

    seen = set()
    results = []
    total_terms = len(query_tokens)
    for row in rows:
        dedup_key = row[0] + row[1][:50]
        if dedup_key in seen:
            continue
        seen.add(dedup_key)
        content_lower = (row[1] or '').lower()
        match_count = sum(1 for t in query_tokens if t in content_lower)
        match_ratio = match_count / total_terms if total_terms > 0 else 0
        trgm_sim = float(row[5]) if row[5] is not None else 0.0
        profile_boost = 15 if row[2] == 'profile' else 5
        exact_bonus = 10 if any(t == w for t in query_tokens for w in content_lower.split()) else 0
        # Score híbrido: 55% match_ratio + 20% trgm_sim + profile_boost + exact_bonus
        score = min(100, round(match_ratio * 55 + trgm_sim * 20 + profile_boost + exact_bonus, 1))

        extra_raw = row[3]
        extra = {}
        if extra_raw:
            try:
                extra = json.loads(extra_raw) if extra_raw != 'None' else {}
            except (json.JSONDecodeError, TypeError):
                extra = {}

        results.append({
            'id': f'm{row[0]}',
            'contenido': row[1],
            'metadatos': {
                'memory_type': row[2],
                'categoria': row[4] if row[4] else 'sin_categoria',
            },
            'extra': extra,
            'code_snippet': None,
            'score_raw': trgm_sim,
            'score': score,
            'source': 'memory_items',
            'method': 'lexico_expansivo',
            'tabla': 'memory_items',
            'memory_type': row[2],
            'categoria': row[4] if row[4] else None,
        })
    return results


# ─── FASE 4: EXPANSIÓN POR TAGS (relacionados) ──────────────────────────────

def extraer_tags_de_resultados(resultados):
    """Extrae tags únicos de todos los resultados (ambas tablas)."""
    tags = set()
    for r in resultados:
        if r['tabla'] == 'memoria_vectorial':
            ts = r['metadatos'].get('tags', [])
        elif r['tabla'] == 'memory_items':
            extra = r.get('extra', {})
            ts = extra.get('tags', []) if isinstance(extra, dict) else []
        else:
            continue
        if isinstance(ts, list):
            for t in ts:
                if isinstance(t, str) and t.strip():
                    tags.add(t.strip().lower())
    return tags


def obtener_todos_los_tags(cur):
    """Obtiene todos los tags únicos de ambas tablas."""
    tags = set()

    try:
        cur.execute("""
            SELECT DISTINCT jsonb_array_elements_text(metadatos->'tags')
            FROM memoria_vectorial
            WHERE metadatos->'tags' IS NOT NULL
        """)
        for row in cur.fetchall():
            if row[0]:
                tags.add(row[0].strip().lower())
    except Exception:
        pass

    try:
        cur.execute("""
            SELECT DISTINCT jsonb_array_elements_text(extra->'tags')
            FROM memory_items
            WHERE extra->'tags' IS NOT NULL
        """)
        for row in cur.fetchall():
            if row[0]:
                tags.add(row[0].strip().lower())
    except Exception:
        pass

    return tags


def tags_coinciden_con_terminos(tags_disponibles, query_terms):
    """Encuentra qué tags coinciden (parcial o totalmente) con los términos de búsqueda."""
    coincidentes = set()
    for tag in tags_disponibles:
        tag_lower = tag.lower()
        if any(t in tag_lower or tag_lower in t for t in query_terms):
            coincidentes.add(tag)
    return coincidentes


def expandir_por_tags(cur, tags, contenidos_existentes):
    """Busca items relacionados por tags compartidos y los agrega."""
    if not tags:
        return []

    tag_list = sorted(tags)
    nuevos = []

    for tag_subset in (tag_list,):
        # Buscar en memoria_vectorial
        sql_mv = """
            SELECT id, contenido, metadatos::text, code_snippet
            FROM memoria_vectorial
            WHERE metadatos->'tags' ?| %s
        """
        try:
            cur.execute(sql_mv, (tag_subset,))
            for row in cur.fetchall():
                clave = (row[1] or '')[:120].lower()
                if clave in contenidos_existentes:
                    continue
                meta = json.loads(row[2])
                nuevos.append({
                    'id': f'tv{row[0]}',
                    'contenido': row[1],
                    'metadatos': meta,
                    'code_snippet': row[3],
                    'score_raw': 0,
                    'score': 70.0,
                    'source': 'memoria_vectorial',
                    'method': 'expansion_por_tags',
                    'tabla': 'memoria_vectorial',
                })
        except Exception:
            pass

        # Buscar en memory_items
        sql_mi = """
            SELECT mi.id::text, mi.summary, mi.memory_type, mi.extra::text,
                   mc.name as categoria
            FROM memory_items mi
            LEFT JOIN category_items ci ON ci.item_id = mi.id
            LEFT JOIN memory_categories mc ON mc.id = ci.category_id
            WHERE mi.extra->'tags' ?| %s
        """
        try:
            cur.execute(sql_mi, (tag_subset,))
            for row in cur.fetchall():
                clave = (row[1] or '')[:120].lower()
                if clave in contenidos_existentes:
                    continue
                extra_raw = row[3]
                extra = {}
                if extra_raw:
                    try:
                        extra = json.loads(extra_raw) if extra_raw != 'None' else {}
                    except (json.JSONDecodeError, TypeError):
                        extra = {}
                nuevos.append({
                    'id': f'tm{row[0]}',
                    'contenido': row[1],
                    'metadatos': {
                        'memory_type': row[2],
                        'categoria': row[4] if row[4] else 'sin_categoria',
                    },
                    'extra': extra,
                    'code_snippet': None,
                    'score_raw': 0,
                    'score': 70.0,
                    'source': 'memory_items',
                    'method': 'expansion_por_tags',
                    'tabla': 'memory_items',
                    'memory_type': row[2],
                    'categoria': row[4] if row[4] else None,
                })
        except Exception:
            pass

    return nuevos


# ─── FASE 5: FUSIÓN Y RANKING (BIRE CORE) ────────────────────────────────────

HYBRID_CONFIG_PATH = "hipocampo_hybrid_config.json"

def cargar_config_hibrida():
    """Carga la configuración de ponderación híbrida calibrada."""
    try:
        with open(HYBRID_CONFIG_PATH) as f:
            cfg = json.load(f)
            return cfg.get('alpha', 0.3)
    except (FileNotFoundError, json.JSONDecodeError):
        return 0.3


def fusionar_resultados(vectorial, lexico_mv, lexico_mi, alpha=None):
    """Fusión con ponderación híbrida calibrada.

    Si alpha no se especifica, se carga del archivo de configuración
    generado por hipocampo_calibrate.py.

    hybrid_score = alpha * best_vec_score + (1-alpha) * best_lex_score
    """
    if alpha is None:
        alpha = cargar_config_hibrida()

    todos = vectorial + lexico_mv + lexico_mi

    grupos = {}
    for r in todos:
        clave = r['contenido'][:120].lower()
        if clave in grupos:
            existente = grupos[clave]
            existente['vec_score'] = max(existente.get('vec_score', 0),
                                         r['score'] if r['method'] == 'vectorial' else 0)
            existente['lex_score'] = max(existente.get('lex_score', 0),
                                         r['score'] if r['method'] != 'vectorial' else 0)
            raw = alpha * existente['vec_score'] + (1 - alpha) * existente['lex_score']
            existente['score'] = round(raw, 1)
            if r['source'] == 'memory_items':
                existente['source'] = 'memory_items'
                existente['memory_type'] = r.get('memory_type')
                existente['categoria'] = r.get('categoria')
        else:
            r['vec_score'] = r['score'] if r['method'] == 'vectorial' else 0
            r['lex_score'] = r['score'] if r['method'] != 'vectorial' else 0
            raw = alpha * r['vec_score'] + (1 - alpha) * r['lex_score']
            r['score'] = round(raw, 1)
            grupos[clave] = r

    fusionados = sorted(grupos.values(), key=lambda x: x['score'], reverse=True)

    return fusionados


# ─── FASE 6: RE-RANKING POR EL AGENTE ACTIVO ─────────────────────────────────

RE_RANK_TOP_N = 15


def re_rank_results(resultados, query, top_n=RE_RANK_TOP_N):
    """Marca los top_n resultados para re-ranking por el agente activo (Claude).

    No hace llamadas API externas. Simplemente preserva los scores originales
    y marca los resultados como pendientes de re-rank. El agente activo (Claude)
    lee la salida y re-ordena según su criterio de relevancia contextual.
    """
    if not resultados:
        return resultados

    top = resultados[:top_n]
    resto = resultados[top_n:]

    if len(top) < 3:
        return resultados

    for i, r in enumerate(top):
        r['score_bire'] = r['score']
        r['rank_bire'] = i + 1

    return top + resto


# ─── FASE 7: OUTPUT FORMATEADO ──────────────────────────────────────────────

def formatear_resultados(resultados, query):
    if not resultados:
        return f"\n🔍 BIRE: '{query}' → 0 resultados"

    alpha = cargar_config_hibrida()
    alpha_desc = f"⚖️  α={alpha:.1f}" if alpha != 0.5 else ""
    has_rerank = any(r.get('score_bire') is not None for r in resultados) if resultados else False
    rerank_desc = "  🔄 re-rank AGENTE" if has_rerank else ""

    lines = [f"\n{'='*60}",
             f"🔍 BIRE v3.6 — Embeddings Unificados 768d + GIN + Híbrido + Auto-Tagging",
             f"   Consulta: \"{query}\"",
             f"   Resultados: {len(resultados)} encontrados {alpha_desc}{rerank_desc}",
             f"{'='*60}"]

    mv_count = sum(1 for r in resultados if r['tabla'] == 'memoria_vectorial')
    mi_count = sum(1 for r in resultados if r['tabla'] == 'memory_items')
    tag_count = sum(1 for r in resultados if r['method'] == 'expansion_por_tags')
    lines.append(f"📊 memoria_vectorial: {mv_count}  |  memory_items: {mi_count}  |  por_tags: {tag_count}")
    if has_rerank:
        lines.append("⚡ RE-RANK PENDIENTE: el agente activo (Claude) re-ordenará estos resultados tras leerlos.")
    lines.append("")

    for i, r in enumerate(resultados, 1):
        score_display = r['score']
        metodo_map = {'vectorial': '🧠 vectorial', 'lexico_expansivo': '📖 léxico', 'expansion_por_tags': '🏷️ tags'}
        if r['tabla'] == 'memory_items':
            mt = r.get('memory_type', '?')
            cat = r.get('categoria', '?')
            fuente = f"memory_items [{mt}|{cat}]"
        else:
            ruta = r['metadatos'].get('path', '?')
            tags = r['metadatos'].get('tags', [])
            tags_str = f" [{', '.join(tags[:3])}]" if tags else ''
            fuente = f"memoria_vectorial{tags_str}"

        barra = '█' * int(score_display / 5) + '░' * (20 - int(score_display / 5))
        lines.append(f"  {i:2d}. [{score_display:5.1f}] {barra}")
        metodo_label = metodo_map.get(r.get('method', ''), r.get('method', '?'))
        lines.append(f"      📍 {fuente} | {metodo_label}")
        texto = r['contenido']
        if len(texto) > 250:
            texto = texto[:247] + '...'
        lines.append(f"      💬 {texto}")

        if r.get('code_snippet'):
            cs = r['code_snippet']
            if len(cs) > 100:
                cs = cs[:97] + '...'
            lines.append(f"      📎 {cs}")
        lines.append("")

    lines.append(f"{'='*60}")
    lines.append(f"📈 Score promedio: {sum(r['score'] for r in resultados)/len(resultados):.1f}")
    lines.append(f"🏆 Mejor score: {resultados[0]['score']} | Peor: {resultados[-1]['score']}")
    lines.append(f"{'='*60}")

    return '\n'.join(lines)


# ─── MAIN ──────────────────────────────────────────────────────────────────────

def bire_search(query, umbral_minimo=10.0, rerank=False):
    conn = psycopg2.connect(
        dbname="hipocampo_db",
        user="usuario",
        password=os.getenv('DB_PASSWORD', ''),
        host="localhost"
    )
    register_vector(conn)
    cur = conn.cursor()

    terms = expandir_consulta(query)
    patterns = generar_patrones_ILIKE(terms)

    vectorial_mv = buscar_vectorial(cur, query)
    vectorial_mi = buscar_vectorial_memory_items(cur, query)
    lexico_mv = buscar_lexico_memoria_vectorial(cur, patterns, terms, query_original=query)
    lexico_mi = buscar_lexico_memory_items(cur, patterns, terms, query_original=query)

    fusionados = fusionar_resultados(vectorial_mv, lexico_mv + vectorial_mi, lexico_mi)

    # Expansión por tags: combina tags de resultados + tags que coinciden con la consulta
    contenidos_existentes = {r['contenido'][:120].lower() for r in fusionados}
    tags_encontrados = extraer_tags_de_resultados(fusionados)

    # También buscar tags que coincidan directamente con los términos expandidos
    todos_tags_db = obtener_todos_los_tags(cur)
    tags_por_query = tags_coinciden_con_terminos(todos_tags_db, terms)
    tags_encontrados.update(tags_por_query)

    if tags_encontrados:
        por_tags = expandir_por_tags(cur, tags_encontrados, contenidos_existentes)
        fusionados = fusionar_resultados(fusionados, por_tags, [])

    if rerank:
        fusionados = re_rank_results(fusionados, query, top_n=RE_RANK_TOP_N)

    filtrados = [r for r in fusionados if r['score'] >= umbral_minimo]

    cur.close()
    conn.close()
    return filtrados


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: hipocampo_search.py <consulta> [umbral_minimo] [--rerank]")
        print("  umbral_minimo: score mínimo (0-100, default 10)")
        print("  --rerank:       marcar top resultados para re-ranking por el agente activo (Claude)")
        sys.exit(1)

    query = sys.argv[1]
    umbral = 10.0
    rerank = False
    for arg in sys.argv[2:]:
        if arg == '--rerank':
            rerank = True
        else:
            try:
                umbral = float(arg)
            except ValueError:
                pass

    resultados = bire_search(query, umbral_minimo=umbral, rerank=rerank)
    output = formatear_resultados(resultados, query)
    print(output)
