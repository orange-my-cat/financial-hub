from __future__ import annotations

from django.urls import path

from accounts.api.views import (
    AccountCloseView,
    AccountDetailView,
    AccountDormantView,
    AccountHistoryView,
    AccountListView,
    AccountReopenView,
    BalanceView,
    MonthCloseView,
    NetWorthSliceView,
    NetWorthTrendView,
    NetWorthView,
)

app_name = "accounts"

urlpatterns = [
    # Resources — the things the user creates and edits.
    path("accounts/", AccountListView.as_view(), name="accounts"),
    path("accounts/<int:pk>/", AccountDetailView.as_view(), name="account"),
    path("accounts/<int:pk>/close/", AccountCloseView.as_view(), name="account-close"),
    path("accounts/<int:pk>/dormant/", AccountDormantView.as_view(), name="account-dormant"),
    path("accounts/<int:pk>/reopen/", AccountReopenView.as_view(), name="account-reopen"),
    path("accounts/<int:pk>/history/", AccountHistoryView.as_view(), name="account-history"),
    path("accounts/<int:pk>/balances/<str:month>/", BalanceView.as_view(), name="balance"),
    # Purpose-built queries — reporting endpoints are queries, not resources.
    path("month-close/", MonthCloseView.as_view(), name="month-close"),
    path("net-worth/", NetWorthView.as_view(), name="net-worth"),
    path("net-worth/trend/", NetWorthTrendView.as_view(), name="net-worth-trend"),
    path("net-worth/slices/", NetWorthSliceView.as_view(), name="net-worth-slices"),
]
