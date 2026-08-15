from __future__ import annotations

from django.urls import path

from cashflow.api.views import (
    CategoryDetailView,
    CategoryListView,
    CategoryReportView,
    CategoryTrendView,
    ProposalConfirmView,
    ProposalDismissView,
    ProposalListView,
    RecurringTemplateView,
    TransactionDetailView,
    TransactionListView,
)

app_name = "cashflow"

urlpatterns = [
    path("transactions/", TransactionListView.as_view(), name="transactions"),
    path("transactions/<int:pk>/", TransactionDetailView.as_view(), name="transaction"),
    path("categories/", CategoryListView.as_view(), name="categories"),
    path("categories/<int:pk>/", CategoryDetailView.as_view(), name="category"),
    path("recurring/", RecurringTemplateView.as_view(), name="recurring"),
    path("recurring/proposals/", ProposalListView.as_view(), name="proposals"),
    path("recurring/confirm/", ProposalConfirmView.as_view(), name="proposal-confirm"),
    path("recurring/dismiss/", ProposalDismissView.as_view(), name="proposal-dismiss"),
    path("category-report/", CategoryReportView.as_view(), name="category-report"),
    path("category-trend/", CategoryTrendView.as_view(), name="category-trend"),
]
