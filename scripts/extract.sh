#!/usr/bin/env bash
set -euo pipefail

docker compose config >/dev/null
docker compose build extractor
docker compose run --rm extractor
