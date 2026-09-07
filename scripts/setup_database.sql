-- ============================================================
-- Hipocampo — Setup idempotente de Base de Datos
-- PostgreSQL 15+ | pgvector | pg_trgm
--
-- Ejecutado por install.sh vía: sudo -u postgres psql -d hipocampo_db
-- Re-ejecutable sin errores: seguro sobre instalaciones existentes
-- (corrige ownership/grants sin borrar datos).
--
-- Placeholders sustituidos por install.sh:
--   __DB_USER__   → rol dedicado (default: hipocampo_user)
-- ============================================================

-- ------------------------------------------------------------
-- 1. Extensiones (requieren superuser)
-- ------------------------------------------------------------
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- ------------------------------------------------------------
-- 2. Asegurar ownership de la BD al usuario del MCP
--    (evita el bug de query_stats: tablas creadas por otro rol)
-- ------------------------------------------------------------
ALTER DATABASE hipocampo_db OWNER TO __DB_USER__;

-- ------------------------------------------------------------
-- 3. memoria_vectorial — Recuerdos técnicos con embedding semántico
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS memoria_vectorial (
    id BIGSERIAL PRIMARY KEY,
    contenido TEXT,
    metadatos JSONB,
    embedding VECTOR(1024),
    code_snippet TEXT
);

CREATE INDEX IF NOT EXISTS idx_memoria_vectorial_contenido_gin
    ON memoria_vectorial USING GIN (contenido gin_trgm_ops);

CREATE INDEX IF NOT EXISTS idx_memoria_vectorial_embedding
    ON memoria_vectorial USING HNSW (embedding vector_cosine_ops);

-- ------------------------------------------------------------
-- 4. resources — Archivos/URLs referenciadas
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS resources (
    id VARCHAR PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    name VARCHAR NOT NULL,
    description TEXT NOT NULL,
    url VARCHAR NOT NULL DEFAULT '',
    extra JSONB,
    user_id VARCHAR
);

-- ------------------------------------------------------------
-- 5. memory_items — Perfil del usuario, eventos y relaciones
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS memory_items (
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

CREATE INDEX IF NOT EXISTS idx_memory_items_summary_gin
    ON memory_items USING GIN (summary gin_trgm_ops);

CREATE INDEX IF NOT EXISTS idx_memory_items_embedding
    ON memory_items USING HNSW (embedding vector_cosine_ops);

CREATE INDEX IF NOT EXISTS ix_memory_items_user
    ON memory_items (user_id);

-- ------------------------------------------------------------
-- 6. memory_categories — Taxonomía
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS memory_categories (
    id VARCHAR PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    name VARCHAR NOT NULL,
    description TEXT NOT NULL,
    embedding VECTOR,
    summary TEXT,
    user_id VARCHAR
);

CREATE INDEX IF NOT EXISTS ix_memory_categories_name
    ON memory_categories (name);

-- ------------------------------------------------------------
-- 7. category_items — Relación M:N items ↔ categorías
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS category_items (
    id VARCHAR PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    item_id VARCHAR NOT NULL REFERENCES memory_items(id) ON DELETE CASCADE,
    category_id VARCHAR NOT NULL REFERENCES memory_categories(id) ON DELETE CASCADE,
    user_id VARCHAR
);

CREATE INDEX IF NOT EXISTS ix_category_items_item
    ON category_items (item_id);

CREATE INDEX IF NOT EXISTS ix_category_items_category
    ON category_items (category_id);

-- Población inicial de categorías (solo si no existen aún)
INSERT INTO memory_categories (id, name, description, user_id)
SELECT gen_random_uuid()::text, c.name, c.descr, 'usuario_ejemplo'
FROM (VALUES
    ('personal_info', 'Nombre, edad, ubicación, datos básicos'),
    ('relationships', 'Familia, esposa, pareja, amigos'),
    ('preferences',   'Gustos, preferencias, likes/dislikes'),
    ('habits',        'Rutinas, costumbres'),
    ('goals',         'Metas, aspiraciones'),
    ('knowledge',     'Conocimientos adquiridos'),
    ('opinions',      'Opiniones del usuario'),
    ('work_life',     'Trabajo, vida profesional'),
    ('activities',    'Actividades, hobbies'),
    ('experiences',   'Experiencias pasadas')
) AS c(name, descr)
WHERE NOT EXISTS (SELECT 1 FROM memory_categories WHERE name = c.name);

-- ------------------------------------------------------------
-- 8. query_stats — Métricas de rendimiento de búsquedas
-- ------------------------------------------------------------
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

-- ------------------------------------------------------------
-- 9. watches — Webhooks para eventos de memoria
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS watches (
    id SERIAL PRIMARY KEY,
    pattern TEXT NOT NULL,
    webhook_url TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_triggered_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_watches_pattern ON watches(pattern);

-- ------------------------------------------------------------
-- 10. memory_links — Grafo de memoria con decaimiento temporal
-- ------------------------------------------------------------
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

-- ------------------------------------------------------------
-- 11. memory_access — Fatigue boost (v5.0)
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS memory_access (
    id SERIAL PRIMARY KEY,
    memory_id TEXT NOT NULL,
    source TEXT NOT NULL,
    accessed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    query_hash VARCHAR(64)
);

CREATE INDEX IF NOT EXISTS idx_memory_access_lookup ON memory_access(memory_id, accessed_at);
CREATE INDEX IF NOT EXISTS idx_memory_access_age ON memory_access(accessed_at);

-- ------------------------------------------------------------
-- 12. memoria_historica — Cold tier (olvido activo v5.0)
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS memoria_historica (
    id BIGSERIAL PRIMARY KEY,
    contenido TEXT,
    tags JSONB,
    embedding TEXT DEFAULT '',
    archived_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ------------------------------------------------------------
-- 13. Ownership y permisos — TODO al usuario del MCP
--     (resuelve y previene el bug de query_stats por siempre)
-- ------------------------------------------------------------
DO $$
DECLARE
    r RECORD;
BEGIN
    -- Ownership de todas las tablas y secuencias al rol del MCP
    FOR r IN SELECT tablename FROM pg_tables WHERE schemaname = 'public'
    LOOP
        EXECUTE format('ALTER TABLE public.%I OWNER TO __DB_USER__', r.tablename);
    END LOOP;
    FOR r IN SELECT sequencename FROM pg_sequences WHERE schemaname = 'public'
    LOOP
        EXECUTE format('ALTER SEQUENCE public.%I OWNER TO __DB_USER__', r.sequencename);
    END LOOP;
END $$;

GRANT ALL PRIVILEGES ON DATABASE hipocampo_db TO __DB_USER__;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO __DB_USER__;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO __DB_USER__;
ALTER DEFAULT PRIVILEGES FOR ROLE __DB_USER__ IN SCHEMA public GRANT ALL ON TABLES TO __DB_USER__;
ALTER DEFAULT PRIVILEGES FOR ROLE __DB_USER__ IN SCHEMA public GRANT ALL ON SEQUENCES TO __DB_USER__;
