CREATE TABLE IF NOT EXISTS source_files (
    id BIGSERIAL PRIMARY KEY,
    object_id BIGINT REFERENCES objects(id),
    source TEXT NOT NULL,
    source_path TEXT NOT NULL,
    size_bytes BIGINT NOT NULL,
    modified_at TIMESTAMPTZ,
    modified_ns BIGINT,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(source, source_path)
);
CREATE INDEX IF NOT EXISTS idx_source_files_object_id ON source_files (object_id);
CREATE INDEX IF NOT EXISTS idx_source_files_source ON source_files (source);
CREATE INDEX IF NOT EXISTS idx_source_files_source_path ON source_files (source_path);
