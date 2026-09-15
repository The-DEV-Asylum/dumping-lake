#!/usr/bin/env bash
set -euo pipefail

docker compose exec postgres psql -U dumping -d dumping -c "SELECT id, source, started_at, completed_at, files_seen, files_new, files_duplicate, files_unchanged, files_failed, filesystem_errors, pg_size_pretty(bytes_processed) AS bytes_processed FROM ingestion_runs ORDER BY id DESC LIMIT 10;"
