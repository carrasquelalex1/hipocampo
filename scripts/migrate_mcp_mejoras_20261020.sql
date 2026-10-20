-- ============================================================
-- Migración idempotente — Mejoras MCP Hipocampo (2026-10-20)
-- Fases 1-3: filtros estructurados, summary/tsvector y chunks.
--
-- Seguro de re-ejecutar. Requiere PostgreSQL 15+, pgvector y pg_trgm.
-- Aplicar SIEMPRE después de un respaldo (regla 0.1 de AGENTS.md).
-- ============================================================

-- 1. Columnas nuevas de memoria_vectorial ---------------------
ALTER TABLE memoria_vectorial ADD COLUMN IF NOT EXISTS summary TEXT;
ALTER TABLE memoria_vectorial ADD COLUMN IF NOT EXISTS summary_embedding VECTOR(1024);
ALTER TABLE memoria_vectorial ADD COLUMN IF NOT EXISTS contenido_tsv TSVECTOR
    GENERATED ALWAYS AS (to_tsvector('spanish'::regconfig, coalesce(contenido, ''))) STORED;

-- 2. Índices de filtros estructurados -------------------------
-- code/categorías/nivel/fecha viven en metadatos; sin estos índices los
-- filtros funcionan pero escanean. jsonb_path_ops cubre @> y ?|.
CREATE INDEX IF NOT EXISTS idx_mv_metadatos_gin
    ON memoria_vectorial USING GIN (metadatos jsonb_path_ops);
CREATE INDEX IF NOT EXISTS idx_mv_code_lower
    ON memoria_vectorial (lower(metadatos->>'code'));
CREATE INDEX IF NOT EXISTS idx_mv_nivel
    ON memoria_vectorial ((metadatos->>'nivel'));
CREATE INDEX IF NOT EXISTS idx_mv_date
    ON memoria_vectorial ((metadatos->>'date'));

-- 3. Búsqueda léxica y de resumen -----------------------------
CREATE INDEX IF NOT EXISTS idx_mv_contenido_tsv
    ON memoria_vectorial USING GIN (contenido_tsv);
CREATE INDEX IF NOT EXISTS idx_mv_summary_gin
    ON memoria_vectorial USING GIN (summary gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_mv_summary_embedding_hnsw
    ON memoria_vectorial USING HNSW (summary_embedding vector_cosine_ops);

-- 4. Chunks de recuerdos largos (Fase 3) ----------------------
CREATE TABLE IF NOT EXISTS memoria_vectorial_chunks (
    id BIGSERIAL PRIMARY KEY,
    parent_id BIGINT NOT NULL REFERENCES memoria_vectorial(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    contenido TEXT NOT NULL,
    embedding VECTOR(1024),
    contenido_tsv TSVECTOR GENERATED ALWAYS AS
        (to_tsvector('spanish'::regconfig, coalesce(contenido, ''))) STORED,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (parent_id, chunk_index)
);
CREATE INDEX IF NOT EXISTS idx_mv_chunks_parent
    ON memoria_vectorial_chunks (parent_id);
CREATE INDEX IF NOT EXISTS idx_mv_chunks_embedding_hnsw
    ON memoria_vectorial_chunks USING HNSW (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS idx_mv_chunks_contenido_gin
    ON memoria_vectorial_chunks USING GIN (contenido gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_mv_chunks_tsv
    ON memoria_vectorial_chunks USING GIN (contenido_tsv);

-- 5. Comentarios de documentación -----------------------------
COMMENT ON COLUMN memoria_vectorial.summary IS
    'Resumen extractivo corto; evita que recuerdos largos se diluyan en el embedding completo.';
COMMENT ON COLUMN memoria_vectorial.summary_embedding IS
    'Embedding del summary (1024d). Opcional: si falta, se usa el canal léxico.';
COMMENT ON TABLE memoria_vectorial_chunks IS
    'Chunks de recuerdos largos con agregación por parent_id (Fase 3).';
