-- RAG chunks over extracted document text (PGVector in existing Supabase Postgres).
-- Embedding cost must stay under OPENAI_DAILY_BUDGET_USD — see docs/SCALING-AND-JOBS.md.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS document_chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    run_id UUID NOT NULL REFERENCES workflow_runs(id) ON DELETE CASCADE,
    user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    document_id TEXT NOT NULL DEFAULT '',
    filename TEXT NOT NULL DEFAULT '',
    chunk_index INT NOT NULL DEFAULT 0,
    content TEXT NOT NULL,
    embedding vector(1536),
    UNIQUE (run_id, document_id, chunk_index)
);

CREATE INDEX IF NOT EXISTS idx_document_chunks_run ON document_chunks(run_id);
CREATE INDEX IF NOT EXISTS idx_document_chunks_user ON document_chunks(user_id);

-- Cosine similarity search scoped to a single run (ownership enforced in API).
CREATE OR REPLACE FUNCTION match_document_chunks(
    query_embedding vector(1536),
    match_run_id uuid,
    match_count int DEFAULT 6
)
RETURNS TABLE (
    id uuid,
    document_id text,
    filename text,
    chunk_index int,
    content text,
    similarity float
)
LANGUAGE sql
STABLE
AS $$
    SELECT
        c.id,
        c.document_id,
        c.filename,
        c.chunk_index,
        c.content,
        (1 - (c.embedding <=> query_embedding))::float AS similarity
    FROM document_chunks c
    WHERE c.run_id = match_run_id
      AND c.embedding IS NOT NULL
    ORDER BY c.embedding <=> query_embedding
    LIMIT greatest(match_count, 1);
$$;

ALTER TABLE document_chunks ENABLE ROW LEVEL SECURITY;
