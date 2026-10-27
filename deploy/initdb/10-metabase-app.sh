#!/bin/bash
# Creates (or updates) Metabase's app database and its own role.
# Runs automatically on a FRESH db volume (docker-entrypoint-initdb.d), and
# is re-run on an existing volume by deploy/ensure_metabase_db.sh.
# Idempotent: create role/database only if missing; always (re)set the password.
set -euo pipefail
: "${METABASE_APP_DB_PASSWORD:?METABASE_APP_DB_PASSWORD is not set}"

psql -v ON_ERROR_STOP=1 --username "${POSTGRES_USER:-postgres}" --dbname postgres \
    -v pw="$METABASE_APP_DB_PASSWORD" <<'SQL'
SELECT 'CREATE ROLE metabase_app LOGIN'
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'metabase_app')\gexec
SELECT format('ALTER ROLE metabase_app WITH LOGIN PASSWORD %L', :'pw')\gexec
SELECT 'CREATE DATABASE metabase_app OWNER metabase_app'
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = 'metabase_app')\gexec
REVOKE CONNECT ON DATABASE metabase_app FROM PUBLIC;
GRANT CONNECT ON DATABASE metabase_app TO metabase_app;
SQL
echo "metabase_app role and database are in place"
