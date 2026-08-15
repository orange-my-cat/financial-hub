"""The dashboard, the spine, and CSV export.

The dashboard is a **fixed layout**. No configurable widgets, no drag and drop
(RISK-06): it is the most expensive screen to build and the most likely to be
rebuilt once real use reveals what is actually looked at, so it does one thing
in one order and does not invite fiddling.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.http import HttpResponse
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.services.net_worth import NetWorthService
from cashflow.services.reporting import category_report
from core.models import Settings
from core.months import descending, month_of, previous, sequence
from core.services.backup_status import backup_status
from core.services.completeness import month_completeness
from core.services.export import (
    cashflow_csv,
    fx_csv,
    investments_csv,
    net_worth_csv,
    net_worth_trend_csv,
)
from core.services.tasks import outstanding_tasks, task_counts
from investments.services.positions import positions

CENTS = Decimal("0.01")


class DashboardView(APIView):
    def get(self, request):
        currency = request.query_params.get("currency", "USD")
        # Fixed to the current month. The date range does not apply here.
        month = request.query_params.get("month") or month_of(date.today())

        preferences = Settings.load()
        service = NetWorthService(staleness_days=preferences.rate_staleness_days)
        result = service.for_month(month, currency)

        # 24 months, latest last, for the trend.
        window = list(sequence(previous_n(month, 23), month))
        trend = [
            {
                "month": point.month,
                "total": point.total.api()["amount"] if point.is_reportable else None,
                "completeness": str(point.completeness.state),
            }
            for point in service.trend(window, currency)
        ]

        previous_month = previous(month)
        prior = service.for_month(previous_month, currency)
        change = (
            (result.total.amount - prior.total.amount).quantize(CENTS)
            if result.is_reportable and prior.is_reportable
            else None
        )
        change_percent = None
        if change is not None and prior.total.amount != 0:
            change_percent = (
                (result.total.amount - prior.total.amount) / abs(prior.total.amount) * 100
            ).quantize(Decimal("0.1"))

        return Response(
            {
                "data": {
                    "month": month,
                    "currency": currency,
                    "net_worth": {
                        "total": result.total.api() if result.is_reportable else None,
                        "reportable": result.is_reportable,
                        "change": str(change) if change is not None else None,
                        "change_percent": str(change_percent)
                        if change_percent is not None
                        else None,
                        "previous_month": previous_month,
                        # Silent when every contributing rate is fresh.
                        "as_at": result.oldest_as_at.isoformat()
                        if (result.oldest_as_at and result.any_stale)
                        else None,
                        "any_stale": result.any_stale,
                    },
                    "completeness": result.completeness.as_dict(),
                    "exclusions": result.exclusion_notices(),
                    "rate_provenance": result.rate_provenance(),
                    "trend": trend,
                    # The product's conscience.
                    "tasks": [task.as_dict() for task in outstanding_tasks(month)],
                    # Per currency. Never combined, and never added to a balance.
                    "cashflow": category_report(month),
                    "investments": _investment_summary(),
                    "backup": backup_status().as_dict(),
                }
            }
        )


def previous_n(month: str, count: int) -> str:
    result = month
    for _ in range(count):
        result = previous(result)
    return result


def _investment_summary() -> list[dict]:
    """Holdings and realised gains by currency. Never combined (BR-18)."""
    blocks: dict[str, dict] = {}
    year = date.today().year

    for position in positions():
        holding = position.holding
        block = blocks.setdefault(
            holding.currency,
            {"currency": holding.currency, "holdings": 0, "cost_basis": Decimal(0), "realised_gain_this_year": Decimal(0)},
        )
        block["holdings"] += 1
        block["cost_basis"] += position.result.total_cost_basis
        for disposal in position.result.disposals_in_year(year):
            block["realised_gain_this_year"] += disposal.realised_gain

    return [
        {
            "currency": block["currency"],
            "holdings": block["holdings"],
            "cost_basis": str(block["cost_basis"].quantize(CENTS)),
            "realised_gain_this_year": str(block["realised_gain_this_year"].quantize(CENTS)),
        }
        for block in sorted(blocks.values(), key=lambda row: row["currency"])
    ]


class SpineView(APIView):
    """The ledger spine's months.

    Runs from the first month with recorded data to the current month. There is
    no month table; months are derived from the balances that exist (ADR-04).
    """

    def get(self, request):
        preferences = Settings.load()
        service = NetWorthService(staleness_days=preferences.rate_staleness_days)
        histories = service.account_histories()

        starts = [h.required_from for h in histories if h.required_from is not None]
        current = request.query_params.get("through") or month_of(date.today())

        if not starts:
            # Nothing recorded yet. The current month alone, Outside Range —
            # which is exactly what "before the first account opened" means.
            return Response(
                {
                    "data": [
                        {
                            "month": current,
                            "state": str(month_completeness(current, []).state),
                        }
                    ]
                }
            )

        first = min(starts)
        return Response(
            {
                "data": [
                    {"month": month, "state": str(service.completeness_for(month).state)}
                    for month in descending(first, current)
                ]
            }
        )


class TaskCountView(APIView):
    """Badge counts for the icon rail."""

    def get(self, request):  # noqa: ARG002
        return Response({"data": task_counts()})


# ---------------------------------------------------------------------------
# CSV export
# ---------------------------------------------------------------------------


def _csv_response(body: str, filename: str) -> HttpResponse:
    response = HttpResponse(body, content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


class ExportView(APIView):
    """One endpoint, one report per call.

    Generated from the same services the screens use, so a file can never
    disagree with the screen it came from.
    """

    def get(self, request, report: str):
        params = request.query_params
        currency = params.get("currency", "USD")
        month = params.get("month") or month_of(date.today())

        if report == "net-worth":
            return _csv_response(
                net_worth_csv(month, currency), f"net-worth-{month}-{currency}.csv"
            )
        if report == "net-worth-trend":
            start = params.get("from_month") or previous_n(month, 23)
            return _csv_response(
                net_worth_trend_csv(start, month, currency),
                f"net-worth-trend-{start}-to-{month}-{currency}.csv",
            )
        if report == "cashflow":
            return _csv_response(cashflow_csv(month), f"cash-flow-{month}.csv")
        if report == "investments":
            year = params.get("year")
            return _csv_response(
                investments_csv(int(year) if year else None),
                f"investments-{year or 'all'}.csv",
            )
        if report == "fx":
            start = date.fromisoformat(params.get("start", f"{month}-01"))
            end = date.fromisoformat(params.get("end", f"{month}-28"))
            return _csv_response(fx_csv(start, end), f"exchange-rates-{month}.csv")

        return Response({"error": {"code": "unknown_report", "message": report}}, status=404)
