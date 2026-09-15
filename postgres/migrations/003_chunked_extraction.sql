ALTER TABLE extraction_runs
    ADD COLUMN IF NOT EXISTS chunks_written BIGINT NOT NULL DEFAULT 0;

ALTER TABLE object_extractions
    ADD COLUMN IF NOT EXISTS chunk_count BIGINT NOT NULL DEFAULT 0;

CREATE TABLE IF NOT EXISTS object_extraction_chunks (
    object_id BIGINT NOT NULL REFERENCES objects(id) ON DELETE CASCADE,
    chunk_id BIGINT NOT NULL,
    extracted_path TEXT NOT NULL,
    text_bytes BIGINT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (object_id, chunk_id)
);

CREATE INDEX IF NOT EXISTS idx_object_extraction_chunks_object_id
    ON object_extraction_chunks(object_id);
