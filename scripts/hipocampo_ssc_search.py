#!/usr/bin/env python3
"""hipocampo_ssc_search.py — Sparse Selective Caching (SSC) v1.0

Inspirado en "Memory Caching: RNNs with Growing Memory" (Google, 2025).

Arquitectura SSC aplicada a Hipocampo:
  - Fase 1 — TAG ROUTER: Clasifica la consulta en dominios. Asigna pesos
              a cada tabla (memoria_vectorial / memory_items) según relevancia.
  - Fase 2 — PGVECTOR SPARSE: Búsqueda semántica en AMBAS tablas, pero
              limitando a top-K con corte temprano si hay alta confianza.
  - Fase 3 — GIN TRIGRAM: Si confianza baja, expande usando índices GIN.
  - Fase 4 — ILIKE FALLBACK: Solo si las fases anteriores no alcanzan el umbral.

Uso:
    python3 scripts/hipocampo_ssc_search.py "consulta" [umbral]
"""
import psycopg2, os, json, sys, re, time
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()
client = genai.Client(api_key=os.getenv('GOOGLE_API_KEY'))

DB_NAME = os.getenv('DB_NAME', 'hipocampo_db')
DB_USER = os.getenv('DB_USER', 'alex')
DB_HOST = os.getenv('DB_HOST', '/var/run/postgresql')

CONFIANZA_ALTA = 70.0
CONFIANZA_MEDIA = 40.0
SSC_TOP_K = 20

PERFIL_KEYWORDS = [
    'nombre', 'llama', 'gusta', 'gustan', 'esposa', 'hijo', 'hija',
    'familia', 'color', 'edad', 'vive', 'prefiere', 'favorito',
    'casado', 'hermano', 'madre', 'padre', 'trabaja', 'estudia',
    'cumple', 'años', 'mascota', 'tiene', 'quiere', 'sueña',
]
TECNICO_KEYWORDS = [
    'proyecto', 'código', 'codigo', 'sistema', 'servidor', 'api',
    'bot', 'mcp', 'python', 'docker', 'linux', 'base de datos',
    'postgres', 'sql', 'programa', 'desarrollo', 'config',
]


def get_embedding(text, dims=768):
    try:
        result = client.models.embed_content(
            model="gemini-embedding-001",
            contents=text[:3000],
            config=types.EmbedContentConfig(
                task_type="RETRIEVAL_QUERY",
                output_dimensionality=dims
            )
        )
        return result.embeddings[0].values
    except Exception as e:
        return None


# ─── FASE 1: TAG ROUTER ──────────────────────────────────────────────────────

def tag_router(query):
    q = query.lower()
    tokens = set(re.findall(r'\w+', q))

    peso_perfil = sum(1 for kw in PERFIL_KEYWORDS if kw in q) / len(PERFIL_KEYWORDS)
    peso_tecnico = sum(1 for kw in TECNICO_KEYWORDS if kw in q) / len(TECNICO_KEYWORDS)

    peso_perfil = min(peso_perfil * 20, 1.0)
    peso_tecnico = min(peso_tecnico * 20, 1.0)

    return {
        'peso_perfil': peso_perfil,
        'peso_tecnico': peso_tecnico,
        'tokens': tokens,
        'modo': 'perfil' if peso_perfil > peso_tecnico else 'tecnico' if peso_tecnico > 0 else 'mixto',
    }


# ─── FASE 2: PGVECTOR SPARSE (ambas tablas) ─────────────────────────────────

def ssc_vectorial(cur, query, router):
    """Búsqueda pgvector en AMBAS tablas. Sin filtro de tags."""
    query_embed = get_embedding(query)
    if query_embed is None:
        return [], 0.0

    max_score = 0.0
    todos = []

    # memoria_vectorial
    cur.execute("""
        SELECT id, contenido, metadatos::text, code_snippet,
               1 - (embedding <=> %s::vector(768)) as similitud
        FROM memoria_vectorial
        WHERE embedding IS NOT NULL
        ORDER BY embedding <=> %s::vector(768)
        LIMIT %s
    """, (query_embed, query_embed, SSC_TOP_K))

    for row in cur.fetchall():
        score = round(float(row[4]) * 100, 1)
        max_score = max(max_score, score)
        meta = json.loads(row[2])
        todos.append({
            'id': f'v{row[0]}',
            'contenido': row[1],
            'metadatos': meta,
            'code_snippet': row[3],
            'score': score,
            'method': 'vectorial',
            'tabla': 'memoria_vectorial',
        })

    # memory_items (siempre, pero con boost si es perfil)
    cur.execute("""
        SELECT mi.id::text, mi.summary, mi.memory_type,
               mc.name as categoria,
               1 - (mi.embedding <=> %s::vector(768)) as similitud
        FROM memory_items mi
        LEFT JOIN category_items ci ON ci.item_id = mi.id
        LEFT JOIN memory_categories mc ON mc.id = ci.category_id
        WHERE mi.embedding IS NOT NULL
        ORDER BY mi.embedding <=> %s::vector(768)
        LIMIT %s
    """, (query_embed, query_embed, SSC_TOP_K))

    for row in cur.fetchall():
        score_raw = float(row[4])
        profile_boost = 15 if (row[2] == 'profile' and router['peso_perfil'] > 0.3) else 5
        score = round(min(100, (score_raw * 100) + profile_boost), 1)
        max_score = max(max_score, score)
        todos.append({
            'id': f'p{row[0]}',
            'contenido': row[1],
            'metadatos': {'memory_type': row[2], 'categoria': row[3]},
            'code_snippet': None,
            'score': score,
            'method': 'vectorial',
            'tabla': 'memory_items',
        })

    return todos, max_score


# ─── FASE 3: GIN TRIGRAM EXPANSION ──────────────────────────────────────────

def ssc_trigram(cur, query, router):
    tokens = re.findall(r'\w+', query.lower().strip())
    if not tokens:
        return [], 0.0

    cur.execute("SET pg_trgm.similarity_threshold = 0.2")
    cur.execute("""
        SELECT id, contenido, metadatos::text, code_snippet,
               similarity(contenido, %s) AS trgm_sim
        FROM memoria_vectorial
        WHERE contenido %% %s
        ORDER BY trgm_sim DESC
        LIMIT 25
    """, (query, query))

    max_score = 0.0
    todos = []
    total_terms = len(tokens)

    for row in cur.fetchall():
        content_lower = (row[1] or '').lower()
        match_count = sum(1 for t in tokens if t in content_lower)
        trgm_sim = float(row[4]) if row[4] is not None else 0.0
        score = round(min(100, (match_count / total_terms) * 60 + trgm_sim * 25 + 10), 1)
        max_score = max(max_score, score)
        meta = json.loads(row[2])
        todos.append({
            'id': f'g{row[0]}', 'contenido': row[1],
            'metadatos': meta, 'code_snippet': row[3],
            'score': score, 'method': 'trigram', 'tabla': 'memoria_vectorial',
        })

    return todos, max_score


# ─── FASE 4: ILIKE FALLBACK ──────────────────────────────────────────────────

def ssc_ilike(cur, query, router):
    tokens = re.findall(r'\w+', query.lower().strip())
    if not tokens:
        return [], 0.0

    patterns = ','.join([f"'%{t}%'" for t in tokens])
    cur.execute(f"""
        SELECT id, contenido, metadatos::text, code_snippet
        FROM memoria_vectorial
        WHERE contenido ILIKE ANY (ARRAY[{patterns}])
        ORDER BY LENGTH(contenido) ASC
        LIMIT 25
    """)

    max_score = 0.0
    todos = []
    total_terms = len(tokens)
    for row in cur.fetchall():
        content_lower = (row[1] or '').lower()
        match_count = sum(1 for t in tokens if t in content_lower)
        score = round(min(100, (match_count / total_terms) * 70 + 10), 1)
        max_score = max(max_score, score)
        meta = json.loads(row[2])
        todos.append({
            'id': f'i{row[0]}', 'contenido': row[1],
            'metadatos': meta, 'code_snippet': row[3],
            'score': score, 'method': 'ilike', 'tabla': 'memoria_vectorial',
        })

    return todos, max_score


# ─── FUSIÓN SSC ───────────────────────────────────────────────────────────────

def ssc_search(query, umbral_minimo=10.0):
    conn = psycopg2.connect(dbname=DB_NAME, user=DB_USER, host=DB_HOST)
    cur = conn.cursor()
    start = time.time()

    router = tag_router(query)
    todos = {}
    confianza_max = 0.0
    fase = 2

    # Fase 2: pgvector en ambas tablas
    vec_results, confianza = ssc_vectorial(cur, query, router)
    confianza_max = max(confianza_max, confianza)
    for r in vec_results:
        todos[r['id']] = r

    tags_msg = router['modo'].upper()

    # Fase 3: trigram si confianza baja
    if confianza_max < CONFIANZA_ALTA or len(todos) < 3:
        tri_results, confianza = ssc_trigram(cur, query, router)
        confianza_max = max(confianza_max, confianza)
        fase = 3
        for r in tri_results:
            if r['id'] not in todos:
                todos[r['id']] = r

    # Fase 4: ILIKE si confianza muy baja
    if confianza_max < CONFIANZA_MEDIA or len([r for r in todos.values() if r['score'] >= umbral_minimo]) < 2:
        ili_results, confianza = ssc_ilike(cur, query, router)
        fase = 4
        for r in ili_results:
            if r['id'] not in todos:
                todos[r['id']] = r

    fusionados = sorted(todos.values(), key=lambda x: x['score'], reverse=True)
    filtrados = [r for r in fusionados if r['score'] >= umbral_minimo]

    elapsed = time.time() - start
    cur.close(); conn.close()

    return filtrados, tags_msg, fase, elapsed


# ─── OUTPUT ────────────────────────────────────────────────────────────────────

def formatear_resultados(resultados, query, modo, fase, elapsed):
    if not resultados:
        return f"\nSSC: '{query}' → 0 resultados ({elapsed:.2f}s)"

    lines = [
        f"\n{'='*60}",
        f"SSC v1.0 — Sparse Selective Caching",
        f"  Consulta: \"{query}\"",
        f"  Router modo: {modo} | Fase: {fase}/4 | {elapsed:.2f}s",
        f"  Resultados: {len(resultados)}",
        f"{'='*60}",
    ]

    for i, r in enumerate(resultados, 1):
        score = r['score']
        met = r['method'].upper()
        tabla = 'MV' if r['tabla'] == 'memoria_vectorial' else 'MI'
        if r.get('metadatos', {}).get('tags'):
            tags = r['metadatos']['tags']
            if isinstance(tags, list) and len(tags) > 0:
                met += f" [{tags[0]}]"
        barra = '█' * int(score / 5) + '░' * (20 - int(score / 5))
        lines.append(f"  {i:2d}. [{score:5.1f}] {barra} [{tabla}|{met}]")
        texto = r['contenido'][:200]
        lines.append(f"      {texto}")
        lines.append("")

    lines.append(f"{'='*60}")
    lines.append(f"Promedio: {sum(r['score'] for r in resultados)/len(resultados):.1f}")
    lines.append(f"Mejor: {resultados[0]['score']} | Peor: {resultados[-1]['score']}")
    return '\n'.join(lines)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: hipocampo_ssc_search.py <consulta> [umbral]")
        sys.exit(1)

    query = sys.argv[1]
    umbral = float(sys.argv[2]) if len(sys.argv) > 2 else 10.0

    resultados, modo, fase, elapsed = ssc_search(query, umbral_minimo=umbral)
    output = formatear_resultados(resultados, query, modo, fase, elapsed)
    print(output)
