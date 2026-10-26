#!/bin/sh
# Create/update the metabase_app role and database on an EXISTING db volume
# (a fresh volume gets them from initdb/10-metabase-app.sh automatically).
# Idempotent. Run from the repo root:  deploy/ensure_metabase_db.sh
set -eu
cd "$(dirname "$0")/.."
docker compose -f deploy/docker-compose.prod.yml --env-file .env up -d --wait db
docker compose -f deploy/docker-compose.prod.yml --env-file .env exec -T db \
    bash /docker-entrypoint-initdb.d/10-metabase-app.sh
