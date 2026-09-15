CREATE TABLE IF NOT EXISTS objects (
    id BIGSERIAL PRIMARY KEY,
    sha256 CHAR(64) UNIQUE NOT NULL,
    size_bytes BIGINT NOT NULL,
    original_name TEXT,
    mime_type TEXT,
    detected_type TEXT,
    source TEXT,
    source_path TEXT,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    modified_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_objects_sha256 ON objects (sha256);
CREATE INDEX IF NOT EXISTS idx_objects_source ON objects (source);
CREATE INDEX IF NOT EXISTS idx_objects_mime_type ON objects (mime_type);
CREATE INDEX IF NOT EXISTS idx_objects_detected_type ON objects (detected_type);
CREATE TABLE IF NOT EXISTS ingestion_runs (
    id BIGSERIAL PRIMARY KEY,
    source TEXT NOT NULL,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    files_seen BIGINT NOT NULL DEFAULT 0,
    files_new BIGINT NOT NULL DEFAULT 0,
    files_duplicate BIGINT NOT NULL DEFAULT 0,
    files_failed BIGINT NOT NULL DEFAULT 0,
    files_unchanged BIGINT NOT NULL DEFAULT 0,
    filesystem_errors BIGINT NOT NULL DEFAULT 0,
    bytes_processed BIGINT NOT NULL DEFAULT 0
);
