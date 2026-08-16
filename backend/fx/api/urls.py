from __future__ import annotations

from django.urls import path

from fx.api.views import (
    CurrencyRegistryView,
    RateBulkView,
    RateDetailView,
    RateListView,
    RateLoadView,
    RateStatusView,
    RateTrendView,
)

app_name = "fx"

urlpatterns = [
    path("currencies/", CurrencyRegistryView.as_view(), name="currencies"),
    path("rates/", RateListView.as_view(), name="rates"),
    path("rates/bulk/", RateBulkView.as_view(), name="rates-bulk"),
    # Before the <currency>/<rate_date> pattern, or "load" would be read as a
    # currency code.
    path("rates/load/", RateLoadView.as_view(), name="rates-load"),
    path("rates/<str:currency>/<str:rate_date>/", RateDetailView.as_view(), name="rate-detail"),
    path("trend/", RateTrendView.as_view(), name="trend"),
    path("status/", RateStatusView.as_view(), name="status"),
]
