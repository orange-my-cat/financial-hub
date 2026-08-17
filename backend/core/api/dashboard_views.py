"""The dashboard, the spine, and CSV export.

The dashboard is a **fixed layout**. No configurable widgets, no drag and drop
(RISK-06): it is the most expensive screen to build and the most likely to be
rebuilt once real use reveals what is actually looked at, so it does one thing
in one order and does not invite fiddling.
"""

from __future__ import annotations

from datetime import date

from django.http import HttpResponse
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.services.net_worth import NetWorthService
from cashflow.services.summary import summary_trend, summary_with_change
from core.currencies import BASE_CURRENCY
from core.models import Settings
from core.months import descending, month_of, previous, sequence
from core.services.backup_status import backup_status
from core.services.export import (
    cashflow_csv,
    fx_csv,
    investments_csv,
    net_worth_csv,
    net_worth_trend_csv,
)
from core.services.movement import movement
from core.services.reporting_month import MonthBasis, ReportingMonth, latest_closed_month
from core.services.tasks import outstanding_tasks, task_counts
from investments.services.positions import held_summary, held_trend


class DashboardView(APIView):
    def get(self, request):
        # The base currency, not the user's default currency setting — the
        # client sends its resolved default explicitly, so a URL keeps fully
        # determining its response (§8.2).
        currency = request.query_params.get("currency", BASE_CURRENCY)

        preferences = Settings.load()
        service = NetWorthService(staleness_days=preferences.rate_staleness_days)

        # The last month that has ended and has balances recorded — not the month
        # in progress, which holds nothing until it closes (see
        # core.services.reporting_month). The date range does not apply here.
        #
        # An explicit `month` still wins, so a URL keeps fully determining its
        # response (§8.2); the response says which of the two happened.
        requested = request.query_params.get("month")
        reporting = (
            ReportingMonth(requested, MonthBasis.REQUESTED, month_of(date.today()))
            if requested
            else latest_closed_month(service)
        )
        month = reporting.month

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
        # Both months or neither: a month with no balances is not a month worth
        # zero, so there is nothing to subtract from.
        reportable = result.is_reportable and prior.is_reportable
        change = movement(
            result.total.amount if reportable else None,
            prior.total.amount if reportable else None,
        )

        return Response(
            {
                "data": {
                    "month": month,
                    # Why that month, so the screen states the period it covers
                    # instead of appearing to report the present.
                    "reporting_month": reporting.as_dict(),
                    "currency": currency,
                    "net_worth": {
                        "total": result.total.api() if result.is_reportable else None,
                        "reportable": result.is_reportable,
                        **change,
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
                    # The product's conscience — and the one panel here that is
                    # about now rather than about the month reported above.
                    #
                    # Anchored to the current month deliberately, and called with
                    # no argument to say so. FR-51 scopes this panel to what is
                    # blocking the current month and the one before it; passing
                    # the reported month would make it fall silent about the close
                    # that is actually due, and disagree with the rail badge,
                    # which counts the same tasks as at today.
                    "tasks": [task.as_dict() for task in outstanding_tasks()],
                    # In the reporting currency, and never added to a balance.
                    # The per-currency breakdown lives on the Category report,
                    # where the currency a thing was bought in is the point.
                    "cashflow": summary_with_change(
                        month, currency, service.translation
                    ),
                    # The same 24-month window as the net worth trend, and the
                    # same window deliberately: the three plots on this screen
                    # share one x axis, so a month sits at the same horizontal
                    # position in all of them. Two windows would put a bar and
                    # a point at the same place on screen while meaning two
                    # different months, which is worse than not aligning them.
                    "cashflow_trend": summary_trend(window, currency, service.translation),
                    # A position, not a month: what is held *now*, valued at the
                    # last price each holding was transacted at. Deliberately not
                    # stated as at the reported month — "currently held" is the
                    # question this panel answers — and its own labels carry the
                    # dates it rests on. Borrows the request's translation service,
                    # so the rate lookups are cached across the whole response.
                    "investments": held_summary(currency, service.translation).as_dict(),
                    # The same 24-month window as the two trends above, for the
                    # same reason: four plots, one x axis, one horizontal position
                    # per month down the whole screen. Each point is the position
                    # as at that month rather than today's plotted backwards, so a
                    # sale lands in the month it happened.
                    "investments_trend": held_trend(window, currency, service.translation),
                    "backup": backup_status().as_dict(),
                }
            }
        )


def previous_n(month: str, count: int) -> str:
    result = month
    for _ in range(count):
        result = previous(result)
    return result


#: How far before the first recorded month the spine may be extended. Ten
#: years is the dataset the whole design is sized for (ADR-05); past that the
#: rail is showing months that could not contain anything.
MAX_EXTEND_MONTHS = 120


class SpineView(APIView):
    """The ledger spine's months.

    Runs from the first month with recorded data to the current month. There is
    no month table; months are derived from the balances that exist (ADR-04).

    `extend` pushes the start back by that many months beyond the first
    recorded one. Those months are Outside Range — a fact about them, not a gap
    to be filled — and their state is computed by the same service as every
    other month rather than assumed by the caller.
    """

    def get(self, request):
        preferences = Settings.load()
        service = NetWorthService(staleness_days=preferences.rate_staleness_days)
        histories = service.account_histories()

        starts = [h.required_from for h in histories if h.required_from is not None]
        current = request.query_params.get("through") or month_of(date.today())

        try:
            extend = max(0, int(request.query_params.get("extend", 0)))
        except ValueError:
            extend = 0
        granted = min(extend, MAX_EXTEND_MONTHS)

        # Nothing recorded yet means the current month alone — which is exactly
        # what "before the first account opened" means — but it can still be
        # extended backwards from there.
        first = previous_n(min(starts) if starts else current, granted)

        return Response(
            {
                "data": [
                    {"month": month, "state": str(service.completeness_for(month).state)}
                    for month in descending(first, current)
                ],
                # Whether another press of Earlier would show anything new, so
                # the control can retire itself rather than going dead.
                "extendable": granted < MAX_EXTEND_MONTHS,
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
        # See DashboardView: the base currency, not the default currency setting.
        currency = params.get("currency", BASE_CURRENCY)
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
