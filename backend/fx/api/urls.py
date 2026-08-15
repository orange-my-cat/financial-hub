from __future__ import annotations

from django.urls import path

from fx.api.views import (
    CurrencyRegistryView,
    RateBulkView,
    RateDetailView,
    RateListView,
    RateStatusView,
    RateTrendView,
)

app_name = "fx"

urlpatterns = [
    path("currencies/", CurrencyRegistryView.as_view(), name="currencies"),
    path("rates/", RateListView.as_view(), name="rates"),
    path("rates/bulk/", RateBulkView.as_view(), name="rates-bulk"),
    path("rates/<str:currency>/<str:rate_date>/", RateDetailView.as_view(), name="rate-detail"),
    path("trend/", RateTrendView.as_view(), name="trend"),
    path("status/", RateStatusView.as_view(), name="status"),
]
