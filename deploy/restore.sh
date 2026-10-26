#!/bin/bash
# Restore a pg_dump -Fc file into the production db container.
#   deploy/restore.sh <dump-file> <database> [--force]
#
# Restores into a FRESH database. If <database> exists and holds any table,
# it refuses unless --force is given; with --force the database is dropped
# (its connections closed) and recreated first.
# metabase_app is restored owned by its role metabase_app (Metabase
# connects as it); every other database is owned by postgres.
# Privileges are not restored: afterwards run `make prod-grant` (the
# read-only dashboard role), as deploy/import_db.sh does.
set -euo pipefail

usage() { echo "usage: $0 <dump-file> <database> [--force]" >&2; exit 2; }
[ $# -ge 2 ] || usage
dump="$1" db="$2" force=0
[ "${3:-}" = "--force" ] && force=1
[ $# -le 3 ] || usage
[ -f "$dump" ] || { echo "no such dump file: $dump" >&2; exit 2; }
dump="$(cd "$(dirname "$dump")" && pwd)/$(basename "$dump")"  # absolute, before the cd below
case "$db" in *[!a-z0-9_]* | '') echo "invalid database name: $db" >&2; exit 2 ;; esac

cd "$(dirname "$0")/.."
compose=(docker compose -f deploy/docker-compose.prod.yml --env-file .env)
psql_db() { "${compose[@]}" exec -T db psql -U postgres -v ON_ERROR_STOP=1 -tA "$@"; }

owner=postgres
[ "$db" = metabase_app ] && owner=metabase_app

"${compose[@]}" up -d --wait db >/dev/null
exists="$(psql_db -d postgres -c "select 1 from pg_database where datname = '${db}'")"
if [ "$exists" = 1 ]; then
    tables="$(psql_db -d "$db" -c "select count(*) from pg_tables where schemaname not in ('pg_catalog', 'information_schema')")"
    if [ "$tables" != 0 ] && [ "$force" != 1 ]; then
        echo "refusing: database ${db} is not empty (${tables} tables). Re-run with --force to replace it." >&2
        exit 1
    fi
    echo "dropping ${db} (${tables} tables)"
    psql_db -d postgres -c "drop database \"${db}\" with (force)" >/dev/null
fi
psql_db -d postgres -c "create database \"${db}\" owner ${owner}" >/dev/null

tmp="/tmp/restore_$$.dump"
"${compose[@]}" cp "$dump" "db:${tmp}" >/dev/null
"${compose[@]}" exec -T db pg_restore -U postgres -d "$db" --no-owner --no-privileges \
    --role="$owner" --exit-on-error "$tmp"
"${compose[@]}" exec -T db rm -f "$tmp"
tables="$(psql_db -d "$db" -c "select count(*) from pg_tables where schemaname = 'public'")"
echo "restored ${dump} into ${db} (${tables} tables, owner ${owner})"
