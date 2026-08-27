-- ============================================================
-- Hipocampo — Esquema Completo de Base de Datos
-- PostgreSQL 17 + pgvector + pg_trgm
-- ============================================================

-- Extensiones requeridas
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- ============================================================
-- memoria_vectorial — Recuerdos técnicos con embedding semántico
-- ============================================================
CREATE TABLE memoria_vectorial (
    id BIGSERIAL PRIMARY KEY,
    contenido TEXT,
    metadatos JSONB,
    embedding VECTOR(1024),
    code_snippet TEXT
);

CREATE INDEX idx_memoria_vectorial_contenido_gin
    ON memoria_vectorial USING GIN (contenido gin_trgm_ops);

CREATE INDEX idx_memoria_vectorial_embedding
    ON memoria_vectorial USING HNSW (embedding vector_cosine_ops);

-- ============================================================
-- resources — Archivos/URLs referenciados
-- ============================================================
CREATE TABLE resources (
    id VARCHAR PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    name VARCHAR NOT NULL,
    description TEXT NOT NULL,
    url VARCHAR NOT NULL DEFAULT '',
    extra JSONB,
    user_id VARCHAR
);

-- ============================================================
-- memory_items — Perfil del usuario, eventos y relaciones
-- ============================================================
CREATE TABLE memory_items (
    id VARCHAR PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resource_id VARCHAR REFERENCES resources(id) ON DELETE CASCADE,
    memory_type VARCHAR NOT NULL,  -- 'profile' | 'event' | 'decision'
    summary TEXT NOT NULL,
    happened_at TIMESTAMP,
    extra JSONB,
    user_id VARCHAR,
    embedding VECTOR(1024)
);

CREATE INDEX idx_memory_items_summary_gin
    ON memory_items USING GIN (summary gin_trgm_ops);

CREATE INDEX idx_memory_items_embedding
    ON memory_items USING HNSW (embedding vector_cosine_ops);

CREATE INDEX ix_memory_items_user
    ON memory_items (user_id);

-- ============================================================
-- memory_categories — Taxonomía de 10 categorías
-- ============================================================
CREATE TABLE memory_categories (
    id VARCHAR PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    name VARCHAR NOT NULL,
    description TEXT NOT NULL,
    embedding VECTOR,
    summary TEXT,
    user_id VARCHAR
);

CREATE INDEX ix_memory_categories_name
    ON memory_categories (name);

-- ============================================================
-- category_items — Relación M:N entre items y categorías
-- ============================================================
CREATE TABLE category_items (
    id VARCHAR PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    item_id VARCHAR NOT NULL REFERENCES memory_items(id) ON DELETE CASCADE,
    category_id VARCHAR NOT NULL REFERENCES memory_categories(id) ON DELETE CASCADE,
    user_id VARCHAR
);

CREATE INDEX ix_category_items_item
    ON category_items (item_id);

CREATE INDEX ix_category_items_category
    ON category_items (category_id);

-- ============================================================
-- memory_categorias — Población inicial (10 categorías)
-- ============================================================
INSERT INTO memory_categories (id, name, description, user_id) VALUES
    (gen_random_uuid()::text, 'personal_info',   'Nombre, edad, ubicación, datos básicos', 'usuario_ejemplo'),
    (gen_random_uuid()::text, 'relationships',   'Familia, esposa, pareja, amigos', 'usuario_ejemplo'),
    (gen_random_uuid()::text, 'preferences',     'Gustos, preferencias, likes/dislikes', 'usuario_ejemplo'),
    (gen_random_uuid()::text, 'habits',          'Rutinas, costumbres', 'usuario_ejemplo'),
    (gen_random_uuid()::text, 'goals',           'Metas, aspiraciones', 'usuario_ejemplo'),
    (gen_random_uuid()::text, 'knowledge',       'Conocimientos adquiridos', 'usuario_ejemplo'),
    (gen_random_uuid()::text, 'opinions',        'Opiniones del usuario', 'usuario_ejemplo'),
    (gen_random_uuid()::text, 'work_life',       'Trabajo, vida profesional', 'usuario_ejemplo'),
    (gen_random_uuid()::text, 'activities',      'Actividades, hobbies', 'usuario_ejemplo'),
    (gen_random_uuid()::text, 'experiences',     'Experiencias pasadas', 'usuario_ejemplo');

-- ============================================================
-- query_stats — Métricas de rendimiento de búsquedas
-- ============================================================
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

-- ============================================================
-- watches — Webhooks para eventos de memoria
-- ============================================================
CREATE TABLE IF NOT EXISTS watches (
    id SERIAL PRIMARY KEY,
    pattern TEXT NOT NULL,
    webhook_url TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_triggered_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_watches_pattern ON watches(pattern);

-- ============================================================
-- memory_links — Grafo de memoria con decaimiento temporal
-- ============================================================
CREATE TABLE IF NOT EXISTS memory_links (
    id SERIAL PRIMARY KEY,
    source_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    relation_type TEXT NOT NULL DEFAULT 'related',
    weight REAL NOT NULL DEFAULT 1.0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_accessed TIMESTAMPTZ,
    reinforced_at TIMESTAMPTZ DEFAULT NOW(),
    metadata JSONB DEFAULT '{}',
    UNIQUE(source_id, target_id, relation_type)
);

CREATE INDEX IF NOT EXISTS idx_memory_links_source ON memory_links(source_id);
CREATE INDEX IF NOT EXISTS idx_memory_links_target ON memory_links(target_id);
CREATE INDEX IF NOT EXISTS idx_memory_links_type ON memory_links(relation_type);
CREATE INDEX IF NOT EXISTS idx_memory_links_last_accessed ON memory_links(last_accessed);
CREATE INDEX IF NOT EXISTS idx_memory_links_reinforced ON memory_links(reinforced_at);
