-- Eval harness storage — golden-set runs + per-document field scores.
-- Metadata / scores only; never store OCR text or extracted payloads.

CREATE TABLE IF NOT EXISTS eval_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ,
    status TEXT NOT NULL DEFAULT 'running',
    suite TEXT NOT NULL DEFAULT 'golden',
    template_filter TEXT,
    model TEXT,
    doc_count INT NOT NULL DEFAULT 0,
    field_checks INT NOT NULL DEFAULT 0,
    field_ok INT NOT NULL DEFAULT 0,
    docs_passed INT NOT NULL DEFAULT 0,
    field_accuracy FLOAT,
    error_message TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS eval_run_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    eval_run_id UUID NOT NULL REFERENCES eval_runs(id) ON DELETE CASCADE,
    fixture_path TEXT NOT NULL,
    template_id TEXT NOT NULL,
    passed BOOLEAN NOT NULL DEFAULT false,
    field_checks INT NOT NULL DEFAULT 0,
    field_ok INT NOT NULL DEFAULT 0,
    text_method TEXT,
    text_len INT,
    error_message TEXT,
    -- Per-field: [{field, ok, note}] — expected/actual omitted in API responses by default
    field_scores JSONB NOT NULL DEFAULT '[]',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_eval_runs_created ON eval_runs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_eval_run_items_run ON eval_run_items(eval_run_id);

ALTER TABLE eval_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE eval_run_items ENABLE ROW LEVEL SECURITY;
