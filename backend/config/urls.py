"""Root URL configuration.

Three things live at the root, in this order: the admin at a non-obvious path,
the API under /api/, and a catch-all that hands everything else to the React
router.
"""

from __future__ import annotations

from django.conf import settings
from django.contrib import admin
from django.urls import include, path, re_path

from core.api.views import spa_index

_admin_path = settings.ADMIN_PATH

urlpatterns = [
    # A recovery tool, not an alternative interface (§10.3). It exists so that
    # ADR-03's soft-deleted rows are reachable without writing SQL.
    path(f"{_admin_path}/", admin.site.urls),
    path("api/", include("core.api.urls")),
    # Everything else is a client-side route. The lookahead keeps the API, the
    # static bundle and the admin out of it, so a mistyped API path returns a
    # 404 from the API rather than silently rendering the application shell.
    re_path(
        rf"^(?!api/|static/|{_admin_path}/).*$",
        spa_index,
        name="spa-index",
    ),
]
