# syntax=docker/dockerfile:1
#
# One image, two build stages. Node builds the React bundle; Python runs
# Gunicorn, Django and WhiteNoise serving that bundle (ADR-10).
#
# The point of shipping them together is that the front end can never drift out
# of sync with the back end — they are the same artefact.

# ---------------------------------------------------------------------------
# Stage 1 — build the React bundle
# ---------------------------------------------------------------------------
FROM node:22-bookworm-slim AS frontend

WORKDIR /build

COPY frontend/package.json ./
COPY frontend/package-lock.json* ./

# `npm ci` is the reproducible path and requires the lockfile. The fallback
# exists only for the first build, before a lockfile has been generated.
RUN if [ -f package-lock.json ]; then npm ci; else npm install; fi

COPY frontend/ ./
RUN npm run build
# → /build/dist

# ---------------------------------------------------------------------------
# Stage 2 — runtime
# ---------------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# postgresql-client 18 for pg_dump and pg_restore. It must be at least the
# version of the server it dumps (data-center runs 18.4), and Debian bookworm
# ships 15 — hence the PGDG repository.
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends curl ca-certificates gnupg; \
    install -d /usr/share/postgresql-common/pgdg; \
    curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc \
        -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc; \
    echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt bookworm-pgdg main" \
        > /etc/apt/sources.list.d/pgdg.list; \
    apt-get update; \
    apt-get install -y --no-install-recommends postgresql-client-18; \
    apt-get purge -y --auto-remove gnupg curl; \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependencies before source, so a code change does not reinstall the world.
# requirements.lock.txt is the pinned artefact (CON-13); requirements.txt is the
# ranged input it is generated from. See README, "Pinning dependencies".
COPY backend/requirements.txt backend/requirements.lock.txt* ./
RUN if [ -f requirements.lock.txt ]; then \
        pip install -r requirements.lock.txt; \
    else \
        pip install -r requirements.txt; \
    fi

COPY backend/ ./

# The built bundle lands where WhiteNoise will serve it from.
COPY --from=frontend /build/dist ./frontend_dist

# Static files are collected at build time, not at start: the entrypoint's job
# is dump-then-migrate, and adding work to it lengthens the window before the
# application answers. A throwaway key is enough — collectstatic touches no
# database and no secret.
RUN DJANGO_SETTINGS_MODULE=config.settings.prod \
    DJANGO_SECRET_KEY=build-time-only-not-a-secret \
    DJANGO_ALLOWED_HOSTS=localhost \
    POSTGRES_DB=x POSTGRES_USER=x POSTGRES_PASSWORD=x \
    POSTGRES_HOST=x POSTGRES_PORT=5432 \
    python manage.py collectstatic --noinput --clear

COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

# Runs as root, deliberately. The container writes its dumps to a Windows
# folder over a Docker Desktop bind mount, whose ownership semantics are not
# something to leave to chance when that dump is the only backstop against
# another tenant's teardown (BUILD_PLAN P-02). The threat model (HLD §10.1)
# accepts considerably more than this: no published port, reachable only
# through nginx, on a physically controlled single-user machine. Worth
# revisiting once the mount's permissions have been observed in practice.

EXPOSE 8000

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
