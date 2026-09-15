#!/usr/bin/env bash
set -euo pipefail

docker compose exec postgres psql -U dumping -d dumping -c "SELECT id, started_at, completed_at, objects_seen, objects_extracted, objects_unsupported, objects_empty, objects_skipped, objects_failed, chunks_written, pg_size_pretty(bytes_processed) AS bytes_processed, pg_size_pretty(text_bytes_written) AS text_bytes_written FROM extraction_runs ORDER BY id DESC LIMIT 10;"
