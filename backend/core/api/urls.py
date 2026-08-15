"""The API root.

No version prefix. Both ends ship in one image and change together, so a `/v1/`
would be ceremony with no second client to serve; it can be added in one place
the day one exists (ADR-12).

Module routes are included here as their stages land:

    Stage 2   accounts/    accounts, balances, month close, net worth, slices
    Stage 3   cashflow/    transactions, categories, recurring, category report
    Stage 4   investments/ holdings, transactions, open lots, realised gains
    Stage 5   dashboard/   summary, outstanding tasks, backup status, export
"""

from __future__ import annotations

from django.urls import include, path

from core.api.settings_views import SettingsView
from core.api.views import HealthView, SessionView, WhoAmIView

app_name = "api"

urlpatterns = [
    path("health/", HealthView.as_view(), name="health"),
    path("session/", SessionView.as_view(), name="session"),
    path("me/", WhoAmIView.as_view(), name="me"),
    path("settings/", SettingsView.as_view(), name="settings"),
    path("fx/", include("fx.api.urls")),
    path("cashflow/", include("cashflow.api.urls")),
    path("investments/", include("investments.api.urls")),
    path("", include("accounts.api.urls")),
]
