from __future__ import annotations

from django.urls import path

from investments.api.views import (
    HoldingDetailView,
    HoldingListView,
    HoldingTransactionView,
    RealisedGainsView,
    TransactionDetailView,
)

app_name = "investments"

urlpatterns = [
    path("holdings/", HoldingListView.as_view(), name="holdings"),
    path("holdings/<int:pk>/", HoldingDetailView.as_view(), name="holding"),
    path("holdings/<int:pk>/transactions/", HoldingTransactionView.as_view(), name="holding-transactions"),
    path("transactions/<int:pk>/", TransactionDetailView.as_view(), name="transaction"),
    path("realised-gains/", RealisedGainsView.as_view(), name="realised-gains"),
]
