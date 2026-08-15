"""ASGI entry point.

Unused. Nothing in this system is asynchronous — no Celery, no Redis, no
websockets, no background work of any kind (ADR-10). The file exists because
Django expects it.
"""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.prod")

application = get_asgi_application()
