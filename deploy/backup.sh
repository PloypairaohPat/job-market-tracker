#!/bin/bash
# Nightly backup of the production databases (docs/deploy.md, "Backups").
# Run from anywhere: deploy/backup.sh   (the systemd timer runs it at 03:30 UTC)
#
# Dumps the pipeline database (JOBMARKET_DB, default jobmarket) and
# metabase_app with pg_dump -Fc INSIDE the db container, then copies each
# file out -- never through a shell redirect. Names are UTC-dated:
#   <db>_YYYYMMDDTHHMMSSZ.dump
# Keeps the newest BACKUP_KEEP (default 14) per database and deletes only
# files matching exactly that pattern in BACKUP_DIR; nothing else there is
# touched.
#
# Settings: environment first, then the repo's .env, then defaults.
#   BACKUP_DIR (default /var/backups/jobmarket), BACKUP_KEEP (14),
#   JOBMARKET_DB (jobmarket)
set -euo pipefail
umask 077  # dumps hold the whole dataset: owner-only files and directories

cd "$(dirname "$0")/.."
compose=(docker compose -f deploy/docker-compose.prod.yml --env-file .env)

env_value() {  # env_value KEY DEFAULT: environment, else .env, else DEFAULT
    local key="$1" default="$2" value=""
    value="${!key:-}"
    if [ -z "$value" ] && [ -f .env ]; then
        value="$(grep -E "^${key}=" .env | tail -n 1 | cut -d= -f2- || true)"
    fi
    printf '%s' "${value:-$default}"
}
log() { echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) backup: $*"; }

backup_dir="$(env_value BACKUP_DIR /var/backups/jobmarket)"
keep="$(env_value BACKUP_KEEP 14)"
databases=("$(env_value JOBMARKET_DB jobmarket)" metabase_app)
stamp="$(date -u +%Y%m%dT%H%M%SZ)"

case "$keep" in '' | *[!0-9]* | 0) log "BACKUP_KEEP must be a positive integer"; exit 2 ;; esac
mkdir -p "$backup_dir"  # new directories are 700 under umask 077

for db in "${databases[@]}"; do
    name="${db}_${stamp}.dump"
    "${compose[@]}" exec -T db pg_dump -U postgres -Fc -f "/tmp/${name}" "$db"
    "${compose[@]}" cp "db:/tmp/${name}" "${backup_dir}/${name}.partial" >/dev/null
    "${compose[@]}" exec -T db rm -f "/tmp/${name}"
    # `docker compose cp` sets the mode from its tar stream, not our umask
    chmod 600 "${backup_dir}/${name}.partial"
    mv "${backup_dir}/${name}.partial" "${backup_dir}/${name}"
    log "wrote ${backup_dir}/${name} ($(du -h "${backup_dir}/${name}" | cut -f1))"

    # retention: newest $keep of THIS database's dated dumps; nothing else
    find "$backup_dir" -maxdepth 1 -type f -regextype posix-extended \
        -regex ".*/${db}_[0-9]{8}T[0-9]{6}Z\.dump" -printf '%f\n' |
        sort -r | tail -n "+$((keep + 1))" |
        while read -r old; do
            rm -f -- "${backup_dir:?}/${old}"
            log "deleted old ${old}"
        done
done
log "done; $(find "$backup_dir" -maxdepth 1 -name '*.dump' | wc -l) dump(s) in ${backup_dir}, $(du -sh "$backup_dir" | cut -f1) total"
