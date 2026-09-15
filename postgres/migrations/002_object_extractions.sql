CREATE TABLE IF NOT EXISTS extraction_runs (
    id BIGSERIAL PRIMARY KEY,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    objects_seen BIGINT NOT NULL DEFAULT 0,
    objects_extracted BIGINT NOT NULL DEFAULT 0,
    objects_unsupported BIGINT NOT NULL DEFAULT 0,
    objects_empty BIGINT NOT NULL DEFAULT 0,
    objects_skipped BIGINT NOT NULL DEFAULT 0,
    objects_failed BIGINT NOT NULL DEFAULT 0,
    bytes_processed BIGINT NOT NULL DEFAULT 0,
    text_bytes_written BIGINT NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS object_extractions (
    object_id BIGINT PRIMARY KEY REFERENCES objects(id) ON DELETE CASCADE,
    status TEXT NOT NULL CHECK (status IN ('extracted', 'empty', 'unsupported', 'failed')),
    extractor TEXT NOT NULL,
    extractor_version TEXT NOT NULL,
    extracted_path TEXT,
    text_bytes BIGINT NOT NULL DEFAULT 0,
    truncated BOOLEAN NOT NULL DEFAULT FALSE,
    error_type TEXT,
    error_message TEXT,
    extracted_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_object_extractions_status ON object_extractions(status);
CREATE INDEX IF NOT EXISTS idx_object_extractions_extractor_version ON object_extractions(extractor, extractor_version);

CREATE TABLE IF NOT EXISTS extraction_errors (
    id BIGSERIAL PRIMARY KEY,
    extraction_run_id BIGINT NOT NULL REFERENCES extraction_runs(id) ON DELETE CASCADE,
    object_id BIGINT NOT NULL REFERENCES objects(id) ON DELETE CASCADE,
    error_type TEXT NOT NULL,
    error_message TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_extraction_errors_run_id ON extraction_errors(extraction_run_id);
CREATE INDEX IF NOT EXISTS idx_extraction_errors_object_id ON extraction_errors(object_id);
