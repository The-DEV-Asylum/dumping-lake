CREATE TABLE IF NOT EXISTS ingestion_errors (
    id BIGSERIAL PRIMARY KEY,
    ingestion_run_id BIGINT NOT NULL REFERENCES ingestion_runs(id),
    source TEXT NOT NULL,
    source_path TEXT NOT NULL,
    error_type TEXT NOT NULL,
    error_message TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_ingestion_errors_run_id ON ingestion_errors (ingestion_run_id);
CREATE INDEX IF NOT EXISTS idx_ingestion_errors_source ON ingestion_errors (source);
CREATE INDEX IF NOT EXISTS idx_ingestion_errors_source_path ON ingestion_errors (source_path);
CREATE INDEX IF NOT EXISTS idx_ingestion_errors_type ON ingestion_errors (error_type);
