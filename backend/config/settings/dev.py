"""Development — a local hot-reloading process on Windows.

Only the database is containerised. Django runs on port 8001 (8000 on this host
belongs to `control-tower`), and the Vite dev server proxies /api to it so the
browser sees a single origin (BUILD_PLAN §2.3).
"""

from __future__ import annotations

from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F401,F403
from .base import DATABASES, env_bool, env_list
from .guards import ConfigurationRefused, assert_development_database

DEBUG = env_bool("DJANGO_DEBUG", True)

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")
CSRF_TRUSTED_ORIGINS = env_list(
    "DJANGO_CSRF_TRUSTED_ORIGINS",
    "http://localhost:5173,http://localhost:8001",
)

# Everything development is permitted to address. `financial_hub_ci` is the
# throwaway tmpfs instance from compose.test.yaml.
EXPECTED_DATABASE_NAMES = {"financial_hub_dev", "financial_hub_ci"}

# P-04. See config/settings/guards.py for why this is a hard stop rather than a
# warning: a rule enforced only by care is a rule that holds until the evening
# someone is tired.
try:
    assert_development_database(
        DATABASES["default"]["NAME"],
        DATABASES["default"]["PORT"],
        EXPECTED_DATABASE_NAMES,
    )
except ConfigurationRefused as exc:
    raise ImproperlyConfigured(str(exc)) from exc
