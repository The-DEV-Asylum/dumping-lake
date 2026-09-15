#!/usr/bin/env bash
set -euo pipefail

for migration in postgres/migrations/*.sql; do
  [ -e "$migration" ] || continue
  docker compose exec -T postgres psql -U dumping -d dumping -v ON_ERROR_STOP=1 -f - < "$migration"
done
