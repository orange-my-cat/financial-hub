"""Thin views. Authenticate, deserialise, call one service, serialise, return.

Not one figure in this module is computed here. Every number came from a service
in `core` or `fx.services`, which is what makes it impossible for this screen and
a report to disagree (§5.2.2).
"""

from __future__ import annotations

from datetime import date

from rest_framework import status as http
from rest_framework.response import Response
from rest_framework.views import APIView

from core.currencies import (
    BASE_CURRENCY,
    CURRENCIES,
    QUOTED_CURRENCY_CODES,
    pair_label,
)
from core.models import Settings
from core.api.responses import with_advisories
from core.services.exceptions import NotFoundError
from fx.api.serializers import (
    BulkRateEntrySerializer,
    DateRangeSerializer,
    RateEntrySerializer,
    TrendQuerySerializer,
)
from fx.services.entry import delete_rate, record_rate, record_rates_for_date
from fx.services.reporting import daily_rates, rate_status, rate_trend


def _validated(serializer_class, data):
    serializer = serializer_class(data=data)
    serializer.is_valid(raise_exception=True)
    return serializer.validated_data


class CurrencyRegistryView(APIView):
    """The currencies and how each one's rate is quoted.

    Served rather than duplicated in the front end. The quote convention is the
    single easiest thing in this system to get backwards, and two copies of it
    is one copy too many.
    """

    def get(self, request):  # noqa: ARG002
        # Wrapped in `data`, like every other read endpoint. This one was not,
        # and the inconsistency reached the browser as a blank screen: TanStack
        # Query throws when a query function resolves to undefined, which is
        # what `response.data` is when there is no `data` key.
        return Response(
            {
                "data": {
                    "base": BASE_CURRENCY,
                    "currencies": [
                        {
                            "code": definition.code,
                            "name": definition.name,
                            "convention": str(definition.convention),
                            "quote_label": definition.quote_label,
                            "example": definition.example,
                            "is_base": definition.is_base,
                            "pair": pair_label(definition.code),
                        }
                        for definition in CURRENCIES.values()
                    ],
                    "quoted": list(QUOTED_CURRENCY_CODES),
                }
            }
        )


class RateListView(APIView):
    """The daily table, and single-rate entry."""

    def get(self, request):
        window = _validated(DateRangeSerializer, request.query_params)
        staleness = Settings.load().rate_staleness_days

        rows = daily_rates(
            window["start"], window["end"], staleness_days=staleness
        )
        return Response({"data": [row.as_dict() for row in rows]})

    def post(self, request):
        entry = _validated(RateEntrySerializer, request.data)
        preferences = Settings.load()

        result = record_rate(
            entry["currency"],
            entry["rate_date"],
            entry["rate"],
            variance_percent=preferences.rate_variance_percent,
        )

        return with_advisories(
            {
                "currency": result.rate.currency,
                "pair": result.rate.pair,
                "rate_date": result.rate.rate_date.isoformat(),
                "rate": str(result.rate.rate),
            },
            result.advisories,
            status=http.HTTP_201_CREATED if result.created else http.HTTP_200_OK,
        )


class RateBulkView(APIView):
    """Bulk entry for a single date, committed as a unit."""

    def post(self, request):
        entry = _validated(BulkRateEntrySerializer, request.data)
        preferences = Settings.load()

        saved, advisories = record_rates_for_date(
            entry["rate_date"],
            entry["rates"],
            variance_percent=preferences.rate_variance_percent,
        )

        return with_advisories(
            {
                "rate_date": entry["rate_date"].isoformat(),
                "saved": [
                    {
                        "currency": row.currency,
                        "pair": row.pair,
                        "rate": str(row.rate),
                    }
                    for row in saved
                ],
            },
            advisories,
            status=http.HTTP_201_CREATED,
        )


class RateDetailView(APIView):
    def delete(self, request, currency: str, rate_date: str):  # noqa: ARG002
        try:
            parsed = date.fromisoformat(rate_date)
        except ValueError:
            raise NotFoundError(f"{rate_date!r} is not a date.") from None
        delete_rate(currency, parsed)
        return Response(status=http.HTTP_204_NO_CONTENT)


class RateTrendView(APIView):
    def get(self, request):
        query = _validated(TrendQuerySerializer, request.query_params)

        trend = rate_trend(
            query["from_currency"],
            query["to_currency"],
            query["start"],
            query["end"],
        )
        return Response({"data": trend.as_dict()})


class RateStatusView(APIView):
    """The missing-and-stale summary — one row per pair."""

    def get(self, request):
        as_of_raw = request.query_params.get("as_of")
        as_of = date.fromisoformat(as_of_raw) if as_of_raw else date.today()
        preferences = Settings.load()

        statuses = rate_status(
            as_of, staleness_days=preferences.rate_staleness_days
        )
        return Response(
            {
                "data": {
                    "as_of": as_of.isoformat(),
                    "staleness_days": preferences.rate_staleness_days,
                    "pairs": [status.as_dict() for status in statuses],
                }
            }
        )
