"""Configuration guards.

Plain functions with no Django imports, so they can be called from a settings
module at import time — before the app registry exists — and tested without
reloading settings.
"""

from __future__ import annotations


class ConfigurationRefused(Exception):
    """The process must not start with this configuration."""


# `data-center`, the shared production instance. It publishes 0.0.0.0:5432 on
# the same host the development server runs on.
PRODUCTION_DATABASE_NAME = "financial_hub"
PRODUCTION_DATABASE_PORT = "5432"


def assert_development_database(name: str, port: str | int, permitted: set[str]) -> None:
    """Refuse to start if development is pointed at production (BUILD_PLAN P-04).

    `data-center` (production, `financial_hub`, port 5432) and
    `data-center-test` (development, `financial_hub_dev`, port 5433) differ by
    one digit, and the development server runs on the same host with DEBUG on
    and migrations pending. Nothing else in this system can catch that mistake —
    not the ORM, not a migration, not a test — because every one of them would
    do exactly what it was asked to.

    So the check happens before anything is asked at all.
    """
    port = str(port)

    if name == PRODUCTION_DATABASE_NAME:
        raise ConfigurationRefused(
            f"Refusing to start: POSTGRES_DB is '{name}', the production database. "
            f"Development uses 'financial_hub_dev' on port 5433. "
            f"Check POSTGRES_DB in .env (BUILD_PLAN P-04)."
        )

    if port == PRODUCTION_DATABASE_PORT:
        raise ConfigurationRefused(
            f"Refusing to start: POSTGRES_PORT is {port}, which is `data-center` — "
            f"the production instance holding live financial data. Development uses "
            f"port 5433 (`data-center-test`). Check POSTGRES_PORT in .env "
            f"(BUILD_PLAN P-04)."
        )

    if name not in permitted:
        raise ConfigurationRefused(
            f"Refusing to start: POSTGRES_DB is '{name}', which is not a database "
            f"development may address ({', '.join(sorted(permitted))})."
        )
