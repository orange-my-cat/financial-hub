#!/usr/bin/env bash
#
# Production container entrypoint.
#
#     wait for the database  →  dump  →  prune to 30  →  migrate  →  Gunicorn
#
# The ordering is the whole point (HLD §11.4). Every schema change is preceded
# by a restorable snapshot taken seconds earlier, so a failed migration leaves
# the application down with the data intact and a fresh dump beside it.
#
# Under the shared-instance decision (BUILD_PLAN §2.2) this dump is not merely
# good practice: `data-center` holds other tenants' databases too, and nothing
# in this application can prevent someone else's `docker compose down -v`. The
# dump is the only backstop, so a failure here stops the container rather than
# being logged and shrugged off.

set -euo pipefail

log() { printf '%s  entrypoint  %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$*"; }
die() { log "FATAL: $*" >&2; exit 1; }

: "${POSTGRES_HOST:?POSTGRES_HOST is not set}"
: "${POSTGRES_PORT:?POSTGRES_PORT is not set}"
: "${POSTGRES_DB:?POSTGRES_DB is not set}"
: "${POSTGRES_USER:?POSTGRES_USER is not set}"
: "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD is not set}"

BACKUP_DIR="${BACKUP_DIR:-/backups}"
BACKUP_RETAIN="${BACKUP_RETAIN:-30}"
GUNICORN_WORKERS="${GUNICORN_WORKERS:-2}"
GUNICORN_BIND="${GUNICORN_BIND:-0.0.0.0:8000}"

export PGPASSWORD="$POSTGRES_PASSWORD"

# ---------------------------------------------------------------------------
# 1. Wait for the database
# ---------------------------------------------------------------------------
# `data-center` is a shared container this compose file does not manage, so
# there is no healthcheck dependency to lean on. On a cold Docker Desktop start
# it is reliably slower to accept connections than this container is to start,
# and without the wait the first run of every session appears to fail.

log "waiting for ${POSTGRES_HOST}:${POSTGRES_PORT} ..."
for attempt in $(seq 1 60); do
    if pg_isready -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -q; then
        log "database is accepting connections (attempt ${attempt})"
        break
    fi
    if [ "$attempt" -eq 60 ]; then
        die "database not reachable at ${POSTGRES_HOST}:${POSTGRES_PORT} after 60 attempts"
    fi
    sleep 2
done

# ---------------------------------------------------------------------------
# 2. Dump — before anything touches the schema
# ---------------------------------------------------------------------------
# Custom format, compressed: roughly a megabyte at this volume, and restorable
# selectively. Plain SQL was rejected as larger and slower to restore; copying
# the data directory was rejected as unreliable against a running server
# (ADR-11).
#
# pg_dump targets the `financial_hub` database alone, never the cluster — the
# other databases on this instance belong to other tenants.

[ -d "$BACKUP_DIR" ] || die "backup directory ${BACKUP_DIR} does not exist — is BACKUP_HOST_DIR bind-mounted?"
[ -w "$BACKUP_DIR" ] || die "backup directory ${BACKUP_DIR} is not writable"

STAMP="$(date -u '+%Y%m%dT%H%M%SZ')"
DUMP_TMP="${BACKUP_DIR}/.${POSTGRES_DB}-${STAMP}.dump.partial"
DUMP_FILE="${BACKUP_DIR}/${POSTGRES_DB}-${STAMP}.dump"

log "dumping ${POSTGRES_DB} → $(basename "$DUMP_FILE")"

# Written under a temporary name and renamed on success, so a dump interrupted
# half-written can never be mistaken for a complete one by the restore
# procedure or by the backup-status service.
if ! pg_dump \
        --host="$POSTGRES_HOST" \
        --port="$POSTGRES_PORT" \
        --username="$POSTGRES_USER" \
        --dbname="$POSTGRES_DB" \
        --format=custom \
        --compress=9 \
        --no-owner \
        --no-privileges \
        --file="$DUMP_TMP"; then
    rm -f "$DUMP_TMP"
    die "pg_dump failed — refusing to migrate without a fresh snapshot"
fi

mv "$DUMP_TMP" "$DUMP_FILE"
log "dump complete: $(du -h "$DUMP_FILE" | cut -f1)"

# ---------------------------------------------------------------------------
# 3. Prune to the newest 30
# ---------------------------------------------------------------------------
# Sorted newest-first by name, which is chronological because the timestamp is
# a sortable UTC stamp. Only this database's dumps are considered, and only
# complete ones — `.partial` files are left for inspection.

mapfile -t OLD_DUMPS < <(
    find "$BACKUP_DIR" -maxdepth 1 -type f -name "${POSTGRES_DB}-*.dump" -printf '%f\n' \
        | sort -r \
        | tail -n "+$((BACKUP_RETAIN + 1))"
)

if [ "${#OLD_DUMPS[@]}" -gt 0 ]; then
    for old in "${OLD_DUMPS[@]}"; do
        log "pruning ${old}"
        rm -f "${BACKUP_DIR}/${old}"
    done
    log "pruned ${#OLD_DUMPS[@]}, retaining ${BACKUP_RETAIN}"
else
    log "nothing to prune"
fi

# ---------------------------------------------------------------------------
# 4. Migrate
# ---------------------------------------------------------------------------
# A failure here stops the container. The snapshot taken moments ago is the
# rollback: stop, restore it, revert the pinned image tag, start (§11.4).

log "applying migrations"
python manage.py migrate --noinput

# ---------------------------------------------------------------------------
# 5. Serve
# ---------------------------------------------------------------------------
# Two workers. One user, nothing asynchronous (ADR-10). Logs to stdout, where
# Docker's json-file driver captures them, capped at 10 MB × 3 (§9.2).

log "starting Gunicorn on ${GUNICORN_BIND} with ${GUNICORN_WORKERS} workers"
exec gunicorn config.wsgi:application \
    --bind "$GUNICORN_BIND" \
    --workers "$GUNICORN_WORKERS" \
    --access-logfile - \
    --error-logfile - \
    --capture-output \
    --timeout 60
