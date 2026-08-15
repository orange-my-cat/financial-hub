"""Production — the `financial-hub` container on the vibe-city network.

Publishes no port. Reached only through `central-station` at
http://financial-hub.localhost (BUILD_PLAN §2.1).
"""

from __future__ import annotations

from .base import *  # noqa: F401,F403
from .base import env_bool, env_list

# Off, so a stack trace is never rendered in the browser (§10.3). Overridable
# only to make the intent explicit in .env; it should never be true here.
DEBUG = env_bool("DJANGO_DEBUG", False)

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "financial-hub.localhost")
CSRF_TRUSTED_ORIGINS = env_list(
    "DJANGO_CSRF_TRUSTED_ORIGINS", "http://financial-hub.localhost"
)

# The database this container is permitted to address. Asserted against
# `SELECT current_database()` by the smoke test, so the assertion is about the
# connection actually established rather than about what was configured.
EXPECTED_DATABASE_NAMES = {"financial_hub"}

# nginx terminates the connection and forwards X-Forwarded-Proto, but that
# connection is plain HTTP on a loopback vhost — there is no TLS anywhere in
# this topology. SECURE_PROXY_SSL_HEADER belongs here the day central-station
# terminates TLS in front of it, and not one day before: trusting the header
# while the scheme is still http would mark cookies secure and lock the user
# out of their own application.
SECURE_PROXY_SSL_HEADER = None

X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
