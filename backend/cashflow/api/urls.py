from __future__ import annotations

from django.urls import path

from cashflow.api.views import (
    CategoryDetailView,
    CategoryFlowView,
    CategoryListView,
    CategoryReportView,
    CategoryTrendView,
    ProposalConfirmView,
    ProposalDismissView,
    ProposalListView,
    RecurringDetailView,
    RecurringEndView,
    RecurringRestartView,
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
    path("recurring/<int:pk>/", RecurringDetailView.as_view(), name="recurring-detail"),
    path("recurring/<int:pk>/end/", RecurringEndView.as_view(), name="recurring-end"),
    path(
        "recurring/<int:pk>/restart/", RecurringRestartView.as_view(), name="recurring-restart"
    ),
    path("recurring/proposals/", ProposalListView.as_view(), name="proposals"),
    path("recurring/confirm/", ProposalConfirmView.as_view(), name="proposal-confirm"),
    path("recurring/dismiss/", ProposalDismissView.as_view(), name="proposal-dismiss"),
    path("category-report/", CategoryReportView.as_view(), name="category-report"),
    path("category-flow/", CategoryFlowView.as_view(), name="category-flow"),
    path("category-trend/", CategoryTrendView.as_view(), name="category-trend"),
]
