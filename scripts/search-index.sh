#!/usr/bin/env bash
set -euo pipefail

docker compose run --rm indexer python -m app.main "$@"
