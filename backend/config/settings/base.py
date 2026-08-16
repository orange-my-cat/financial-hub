"""Settings common to every environment.

This module is never used on its own. `dev` and `prod` import it and then state
the handful of things that genuinely differ — DEBUG, the hosts, the database,
and whether dumps are being taken.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# backend/
BASE_DIR = Path(__file__).resolve().parent.parent.parent
# The repository root. Absent inside the container, where configuration arrives
# through compose's env_file.
REPO_ROOT = BASE_DIR.parent

load_dotenv(REPO_ROOT / ".env")


# ---------------------------------------------------------------------------
# Environment helpers
# ---------------------------------------------------------------------------
# Deliberately small. Everything environment-specific comes from .env (§9.3),
# and anything absent should fail loudly at start rather than fall back to a
# default that happens to work on one machine.


def env(key: str, default: str | None = None) -> str:
    value = os.environ.get(key, default)
    if value is None:
        raise RuntimeError(
            f"{key} is not set. Every key is documented in .env.example."
        )
    return value


def env_bool(key: str, default: bool) -> bool:
    raw = os.environ.get(key)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def env_list(key: str, default: str = "") -> list[str]:
    return [item.strip() for item in os.environ.get(key, default).split(",") if item.strip()]


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------

SECRET_KEY = env("DJANGO_SECRET_KEY")
DEBUG = False
ALLOWED_HOSTS: list[str] = []

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    # The five apps mirror the four BRD modules plus the shared primitives,
    # which makes BR-12's decoupling structural rather than a promise (ADR-10).
    "core",
    "accounts",
    "cashflow",
    "investments",
    "fx",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # Immediately after SecurityMiddleware, per WhiteNoise's documented order.
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
# PostgreSQL only. NUMERIC(19,4) for money and NUMERIC(19,10) for quantities and
# rates are not portable niceties — they are the reason no figure in this system
# is ever a float (ADR-02).

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env("POSTGRES_DB"),
        "USER": env("POSTGRES_USER"),
        "PASSWORD": env("POSTGRES_PASSWORD"),
        "HOST": env("POSTGRES_HOST"),
        "PORT": env("POSTGRES_PORT"),
        "CONN_MAX_AGE": 60,
    }
}


# ---------------------------------------------------------------------------
# Authentication and sessions
# ---------------------------------------------------------------------------
# One user, one password, no roles (§10.2). The password protects against
# another person at the keyboard — not against anyone holding the machine.

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# 30 days from login, and no idle timeout — SESSION_SAVE_EVERY_REQUEST stays
# False so the window is fixed rather than sliding. A re-login prompt part-way
# through a monthly close is friction against quality attribute 3, on a machine
# that is already trusted (ADR-16).
SESSION_COOKIE_AGE = 30 * 24 * 60 * 60
SESSION_SAVE_EVERY_REQUEST = False
SESSION_EXPIRE_AT_BROWSER_CLOSE = False
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_NAME = "financialhub_session"

# The one cookie the front end must read, to echo the token back as a header.
CSRF_COOKIE_HTTPONLY = False
CSRF_COOKIE_SAMESITE = "Lax"

# A break-glass route to soft-deleted rows (ADR-03), at a non-obvious path
# (§10.3). Any routine use of it indicates a missing feature.
ADMIN_PATH = env("DJANGO_ADMIN_PATH", "ops-7f3a91").strip("/")


# ---------------------------------------------------------------------------
# REST framework
# ---------------------------------------------------------------------------

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
    ],
    # The default, not a per-view decoration: a new endpoint is protected unless
    # it is deliberately opened, rather than exposed unless someone remembers to
    # close it (§10.2).
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    # JSON only. The browsable API is a debugging convenience that renders
    # financial data into an HTML page, and there is nothing here worth
    # browsing by hand that the admin does not already reach.
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ],
    "DEFAULT_PARSER_CLASSES": [
        "rest_framework.parsers.JSONParser",
    ],
    # One error shape from every endpoint (§8.3).
    "EXCEPTION_HANDLER": "core.api.errors.exception_handler",
    # Load-bearing (ADR-12). Decimals serialise as strings, because JSON.parse
    # turns a number into a float and a decade of exact arithmetic ends there.
    "COERCE_DECIMAL_TO_STRING": True,
    # ISO calendar dates, no time component, no offset (BR-24).
    "DATE_FORMAT": "%Y-%m-%d",
    "DATE_INPUT_FORMATS": ["%Y-%m-%d"],
}


# ---------------------------------------------------------------------------
# Time and locale
# ---------------------------------------------------------------------------
# The timezone has exactly one job: deciding what "today" means when defaulting
# a date field. It never adjusts a stored date, and changing it restates
# nothing (§9.4). Asia/Kuala_Lumpur because Perth and KL are both UTC+8 with no
# daylight saving, making the two locations identical year-round.

LANGUAGE_CODE = "en-au"
TIME_ZONE = env("DJANGO_TIME_ZONE", "Asia/Kuala_Lumpur")
USE_I18N = False
USE_TZ = True


# ---------------------------------------------------------------------------
# Static files
# ---------------------------------------------------------------------------
# The Vite bundle is built into the image and served by WhiteNoise from the same
# process as the API, so the two can never drift apart (ADR-10).

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
FRONTEND_DIST = BASE_DIR / "frontend_dist"

STATICFILES_DIRS = [FRONTEND_DIST] if FRONTEND_DIST.is_dir() else []

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        # Compressed but not manifest-hashed: Vite already content-hashes every
        # asset filename, so manifest storage would add a second hashing pass
        # whose only distinctive behaviour is failing the build on a reference
        # it cannot resolve.
        "BACKEND": "whitenoise.storage.CompressedStaticFilesStorage",
    },
}


# ---------------------------------------------------------------------------
# Backups
# ---------------------------------------------------------------------------
# The application never performs a backup — that is the container entrypoint's
# job (ADR-11). It only reads the folder, so the dashboard can say how old the
# newest dump is and warn when it predates the newest data change.

# The smoke test's fifth assertion: a month whose net worth must never change
# again. Empty until a month has actually been closed — a figure asserted before
# one exists would be asserting nothing (§11.5).
SMOKE_TEST_MONTH = os.environ.get("SMOKE_TEST_MONTH", "").strip()
SMOKE_TEST_NET_WORTH = os.environ.get("SMOKE_TEST_NET_WORTH", "").strip()
SMOKE_TEST_CURRENCY = os.environ.get("SMOKE_TEST_CURRENCY", "USD").strip()

BACKUP_DIR = os.environ.get("BACKUP_DIR", "").strip()
BACKUP_RETAIN = int(os.environ.get("BACKUP_RETAIN", "30"))
BACKUP_MAX_AGE_HOURS = int(os.environ.get("BACKUP_MAX_AGE_HOURS", "24"))


# ---------------------------------------------------------------------------
# Rate provider
# ---------------------------------------------------------------------------
# The second implementation of ADR-08's ingestion seam, read only by
# `manage.py load_rates`. Deliberately optional and deliberately not `env()`:
# every screen, report and calculation works with nothing but hand-entered
# rates, and an unset key must not stop the application starting. The command
# says what is missing if it is asked to run without one.

MASSIVE_API_KEY = os.environ.get("MASSIVE_API_KEY", "").strip()
MASSIVE_BASE_URL = os.environ.get("MASSIVE_BASE_URL", "https://api.massive.com").strip()
MASSIVE_TIMEOUT_SECONDS = int(os.environ.get("MASSIVE_TIMEOUT_SECONDS", "30"))


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
# stdout, captured by Docker's json-file driver and capped at 10 MB × 3 in
# compose.yaml. `docker compose logs financial-hub` is the entire diagnostic
# story a single-user system needs, and anything more elaborate is unjustified
# (§9.2).
#
# The `financial_hub` logger is where financially significant events go at info
# level: balance upserts, rate entries, investment transaction changes, backup
# runs and migrations.

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "standard": {
            "format": "{asctime} {levelname:<8} {name} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "standard",
        },
    },
    "root": {"handlers": ["console"], "level": "WARNING"},
    "loggers": {
        "django": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "django.db.backends": {"handlers": ["console"], "level": "WARNING", "propagate": False},
        "financial_hub": {"handlers": ["console"], "level": "INFO", "propagate": False},
    },
}
