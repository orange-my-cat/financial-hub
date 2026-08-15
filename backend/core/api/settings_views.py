"""The Settings screen's endpoint.

Reporting currency, staleness threshold and variance threshold live in the
database rather than in `.env`, because they are user choices rather than
deployment facts, and the two thresholds in particular must be changeable
without a deploy (§9.3, OI-13).
"""

from __future__ import annotations

from rest_framework.response import Response
from rest_framework.views import APIView

from core.currencies import CURRENCY_CODES, format_rate
from core.models import Settings
from core.services.exceptions import BusinessRuleError
from fx.api.serializers import SettingsSerializer


def _payload(preferences: Settings) -> dict:
    return {
        "reporting_currency": preferences.reporting_currency,
        # Fixed, and applied to all date interpretation. Shown so the Settings
        # screen can state it rather than imply it is editable (§9.4).
        "timezone": preferences.timezone,
        "rate_staleness_days": preferences.rate_staleness_days,
        # Trimmed, so the value reads the same whether it was just written from
        # a Python default or read back from NUMERIC(19,10). Without this the
        # same setting is "10" before a reload and "10.0000000000" after.
        "rate_variance_percent": format_rate(preferences.rate_variance_percent),
    }


class SettingsView(APIView):
    def get(self, request):  # noqa: ARG002
        return Response({"data": _payload(Settings.load())})

    def patch(self, request):
        serializer = SettingsSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        changes = serializer.validated_data

        if "reporting_currency" in changes and changes["reporting_currency"] not in CURRENCY_CODES:
            raise BusinessRuleError(
                f"{changes['reporting_currency']} is not a currency this system "
                f"reports in.",
                code="unknown_currency",
                field="reporting_currency",
            )

        preferences = Settings.load()
        for field, value in changes.items():
            setattr(preferences, field, value)
        preferences.save()

        # Changing the reporting currency changes display only. No stored data
        # is rewritten, and the change is reversible at any time (BR-10).
        return Response({"data": _payload(preferences)})
