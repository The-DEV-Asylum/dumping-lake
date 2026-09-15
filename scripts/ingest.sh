#!/usr/bin/env bash
set -euo pipefail

docker compose config >/dev/null
docker compose build ingest
docker compose run --rm ingest
