"""Thin views. Not one figure here is computed in this module.

Every aggregate response carries its completeness state, exclusions and rate
provenance, so a consumer cannot render a total without the information that
qualifies it (§8.2). That is why the reporting endpoints use
`core.api.responses.aggregate` rather than a plain Response.
"""

from __future__ import annotations

from decimal import Decimal

from rest_framework import status as http
from rest_framework.response import Response
from rest_framework.views import APIView

from core.api.responses import aggregate, with_advisories
from core.models import Settings
from core.months import sequence
from core.services.exceptions import NotFoundError
from accounts.api.serializers import (
    AccountCreateSerializer,
    AccountSerializer,
    AccountUpdateSerializer,
    BalanceSerializer,
    CloseSerializer,
    MonthQuerySerializer,
    RangeQuerySerializer,
    SliceQuerySerializer,
)
from accounts.models import Account
from accounts.services import lifecycle
from accounts.services.month_close import month_close
from accounts.services.net_worth import NetWorth, NetWorthService
from accounts.services.slices import SliceDimension, slice_net_worth


CENTS = Decimal("0.01")


def _validated(serializer_class, data):
    serializer = serializer_class(data=data)
    serializer.is_valid(raise_exception=True)
    return serializer.validated_data


def _account(pk: int) -> Account:
    account = Account.objects.filter(pk=pk).first()
    if account is None:
        raise NotFoundError(f"No account with id {pk}.", code="account_not_found")
    return account


def _staleness() -> int:
    return Settings.load().rate_staleness_days


def _net_worth_payload(result: NetWorth) -> dict:
    return {
        "month": result.month,
        # Null where the month has no balances at all. Not zero — see
        # NetWorth.is_reportable.
        "total": result.total.api() if result.is_reportable else None,
        "reportable": result.is_reportable,
        # Only when something is stale. When every contributing rate is fresh,
        # show nothing — silence is the signal (ADR-09).
        "as_at": result.oldest_as_at.isoformat()
        if (result.oldest_as_at and result.any_stale)
        else None,
        "any_stale": result.any_stale,
        "has_carried_balances": result.has_carried_balances,
        "accounts": [c.as_dict() for c in result.contributions],
    }


# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------


class AccountListView(APIView):
    def get(self, request):  # noqa: ARG002
        accounts = Account.objects.all()
        return Response({"data": AccountSerializer(accounts, many=True).data})

    def post(self, request):
        fields = _validated(AccountCreateSerializer, request.data)
        account = Account.objects.create(**fields)
        return Response(
            {"data": AccountSerializer(account).data}, status=http.HTTP_201_CREATED
        )


class AccountDetailView(APIView):
    def get(self, request, pk: int):  # noqa: ARG002
        return Response({"data": AccountSerializer(_account(pk)).data})

    def patch(self, request, pk: int):
        account = _account(pk)
        changes = _validated(AccountUpdateSerializer, request.data)
        advisories = []

        if "currency" in changes:
            lifecycle.change_currency(account, changes["currency"])

        if "name" in changes:
            account.name = changes["name"]
            account.save(update_fields=["name", "updated_at"])

        if "account_type" in changes or "liquidity_tier" in changes:
            result = lifecycle.reclassify(
                account,
                account_type=changes.get("account_type", account.account_type),
                liquidity_tier=changes.get("liquidity_tier", account.liquidity_tier),
            )
            advisories = list(result.advisories)

        account.refresh_from_db()
        return with_advisories(AccountSerializer(account).data, advisories)

    def delete(self, request, pk: int):  # noqa: ARG002
        lifecycle.delete_account(_account(pk))
        return Response(status=http.HTTP_204_NO_CONTENT)


class AccountCloseView(APIView):
    def post(self, request, pk: int):
        fields = _validated(CloseSerializer, request.data)
        result = lifecycle.close(_account(pk), fields["closed_month"])
        return Response({"data": AccountSerializer(result.account).data})


class AccountDormantView(APIView):
    def post(self, request, pk: int):  # noqa: ARG002
        result = lifecycle.set_dormant(_account(pk))
        return Response({"data": AccountSerializer(result.account).data})


class AccountReopenView(APIView):
    def post(self, request, pk: int):  # noqa: ARG002
        result = lifecycle.reopen(_account(pk))
        return Response({"data": AccountSerializer(result.account).data})


class AccountHistoryView(APIView):
    """Balance history for one account, in its own currency.

    The reporting-currency control does not apply to Account detail, and this is
    why: the driving question is about one account's own trend, and translating
    it would introduce rate movement into a figure the user wants to read as
    their own money.
    """

    def get(self, request, pk: int):  # noqa: ARG002
        account = _account(pk)
        rows = list(account.balances.order_by("-month"))

        history = []
        for index, balance in enumerate(rows):
            older = rows[index + 1] if index + 1 < len(rows) else None
            change = balance.amount - older.amount if older else None
            history.append(
                {
                    "month": balance.month,
                    "amount": str(balance.amount),
                    "change": str(change) if change is not None else None,
                    "previous_month": older.month if older else None,
                }
            )

        return Response(
            {
                "data": {
                    "account": AccountSerializer(account).data,
                    "history": history,
                }
            }
        )


# ---------------------------------------------------------------------------
# Balances
# ---------------------------------------------------------------------------


class BalanceView(APIView):
    """Create-or-replace for one account and month.

    Month Close autosaves on blur, one field at a time. Each call addresses a
    distinct (account, month) key, so several in flight cannot conflict (§9.5).
    """

    def put(self, request, pk: int, month: str):
        fields = _validated(BalanceSerializer, request.data)
        balance = lifecycle.upsert_balance(_account(pk), month, fields["amount"])
        return Response(
            {
                "data": {
                    "account_id": pk,
                    "month": balance.month,
                    "amount": str(balance.amount),
                }
            }
        )

    def delete(self, request, pk: int, month: str):  # noqa: ARG002
        lifecycle.delete_balance(_account(pk), month)
        return Response(status=http.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Purpose-built queries
# ---------------------------------------------------------------------------


class MonthCloseView(APIView):
    def get(self, request):
        query = _validated(MonthQuerySerializer, request.query_params)
        result = month_close(query["month"], staleness_days=_staleness())
        return Response({"data": result.as_dict()})


class NetWorthView(APIView):
    def get(self, request):
        query = _validated(MonthQuerySerializer, request.query_params)
        result = NetWorthService(staleness_days=_staleness()).for_month(
            query["month"], query["currency"]
        )

        return aggregate(
            _net_worth_payload(result),
            completeness=result.completeness.as_dict(),
            exclusions=result.exclusion_notices(),
            rate_provenance=result.rate_provenance(),
        )


class NetWorthTrendView(APIView):
    def get(self, request):
        query = _validated(RangeQuerySerializer, request.query_params)
        months = sequence(query["from_month"], query["to_month"])

        # One service instance, so the rate resolver's cache is shared across
        # every month in the range rather than rebuilt per month.
        service = NetWorthService(staleness_days=_staleness())
        series = service.trend(list(months), query["currency"])

        points = []
        previous_total = None
        for result in series:
            if not result.is_reportable:
                # No balances in this month. Emitted as a gap so the chart
                # breaks the line rather than drawing a fall to zero, and so
                # the table shows an em dash rather than a figure nobody
                # recorded.
                points.append(
                    {
                        "month": result.month,
                        "total": None,
                        "change": None,
                        "completeness": str(result.completeness.state),
                        "any_stale": False,
                        "excluded": 0,
                    }
                )
                previous_total = None
                continue

            total = result.total.amount
            change = total - previous_total if previous_total is not None else None
            points.append(
                {
                    "month": result.month,
                    "total": result.total.api(),
                    # Month-on-month, computed from the full-precision totals
                    # and rounded once here for display.
                    "change": str(change.quantize(CENTS)) if change is not None else None,
                    "completeness": str(result.completeness.state),
                    "any_stale": result.any_stale,
                    "excluded": len(result.exclusions),
                }
            )
            previous_total = total

        return Response({"data": {"currency": query["currency"], "points": points}})


class NetWorthSliceView(APIView):
    def get(self, request):
        query = _validated(SliceQuerySerializer, request.query_params)
        result = NetWorthService(staleness_days=_staleness()).for_month(
            query["month"], query["currency"]
        )
        rows = slice_net_worth(result, SliceDimension(query["dimension"]))

        return aggregate(
            {
                "month": result.month,
                "dimension": query["dimension"],
                "total": result.total.api(),
                "rows": [row.as_dict() for row in rows],
            },
            completeness=result.completeness.as_dict(),
            exclusions=result.exclusion_notices(),
            rate_provenance=result.rate_provenance(),
        )
