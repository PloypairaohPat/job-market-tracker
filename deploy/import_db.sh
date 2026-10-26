#!/bin/bash
# Import the laptop's database on the server (docs/deploy.md, "Cut-over").
#   deploy/import_db.sh <dump-file> [--force]
#
# <dump-file> comes from scripts/windows/export_db.ps1 on the laptop.
#   1. deploy/restore.sh restores it into a fresh pipeline database
#      (JOBMARKET_DB in .env, default jobmarket); a non-empty one is refused
#      unless --force is given
#   2. inside the pipeline image: alembic upgrade head, the SQL views, the
#      read-only metabase_reader role and the Metabase dashboards
#   3. prints the same row counts as export_db.ps1, to compare line by line
#
# Build the image first (make prod-build). Public links are never turned on
# here: that is the last step of the cut-over.
set -euo pipefail

usage() { echo "usage: $0 <dump-file> [--force]" >&2; exit 2; }
[ $# -ge 1 ] && [ $# -le 2 ] || usage
force=()
if [ $# -eq 2 ]; then
    [ "$2" = --force ] || usage
    force=(--force)
fi
[ -f "$1" ] || { echo "no such dump file: $1" >&2; exit 2; }
dump="$(cd "$(dirname "$1")" && pwd)/$(basename "$1")"  # absolute, before the cd below

cd "$(dirname "$0")/.."
compose=(docker compose -f deploy/docker-compose.prod.yml --env-file .env)
pipeline() { "${compose[@]}" run --rm pipeline "$@"; }
step() { echo; echo "== $*"; }

db="${JOBMARKET_DB:-}"
if [ -z "$db" ] && [ -f .env ]; then
    db="$(grep -E '^JOBMARKET_DB=' .env | tail -n 1 | cut -d= -f2- || true)"
fi
db="${db:-jobmarket}"

step "restore ${dump} into ${db}"
deploy/restore.sh "$dump" "$db" "${force[@]}"

step "start Metabase (and db)"
"${compose[@]}" up -d --wait db metabase

step "migrations"
pipeline alembic -c /app/alembic.ini upgrade head
step "views"
pipeline python /app/scripts/apply_views.py
step "read-only dashboard role"
pipeline python -m src.dashboard.reader_role
step "dashboards"
pipeline python -m src.dashboard.provision

step "row counts in ${db} (compare with export_db.ps1 on the laptop)"
"${compose[@]}" exec -T db psql -U postgres -d "$db" -v ON_ERROR_STOP=1 -tA <deploy/row_counts.sql
