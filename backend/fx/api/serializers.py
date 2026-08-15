"""Shape and type at the boundary; nothing else (§9.1).

Rates cross the API as **strings**, exactly as money does. A rate is a decimal,
and `JSON.parse` turns a decimal into a float just as readily as it does an
amount — a rate rendered through a float would misvalue every balance in that
currency (ADR-12).
"""

from __future__ import annotations

from decimal import Decimal

from rest_framework import serializers

from core.currencies import QUOTED_CURRENCY_CODES


class RateEntrySerializer(serializers.Serializer):
    currency = serializers.ChoiceField(choices=QUOTED_CURRENCY_CODES)
    rate_date = serializers.DateField()
    # A string in, a Decimal out. `max_digits`/`decimal_places` mirror
    # NUMERIC(19,10) so a value the database would refuse is refused here first,
    # with a field error against the input rather than an integrity error.
    rate = serializers.DecimalField(max_digits=19, decimal_places=10, min_value=Decimal("0.0000000001"))


class BulkRateEntrySerializer(serializers.Serializer):
    """Bulk entry for one date, committed as a unit (§9.6)."""

    rate_date = serializers.DateField()
    rates = serializers.DictField(
        child=serializers.DecimalField(
            max_digits=19, decimal_places=10, min_value=Decimal("0.0000000001")
        ),
        allow_empty=False,
    )

    def validate_rates(self, value: dict[str, Decimal]) -> dict[str, Decimal]:
        unknown = sorted(set(value) - set(QUOTED_CURRENCY_CODES))
        if unknown:
            raise serializers.ValidationError(
                f"Not a currency this system quotes: {', '.join(unknown)}. "
                f"Expected any of {', '.join(QUOTED_CURRENCY_CODES)}."
            )
        return value


class TrendQuerySerializer(serializers.Serializer):
    from_currency = serializers.CharField(max_length=3)
    to_currency = serializers.CharField(max_length=3)
    start = serializers.DateField()
    end = serializers.DateField()

    def validate(self, attrs: dict) -> dict:
        if attrs["start"] > attrs["end"]:
            raise serializers.ValidationError("The start date is after the end date.")
        return attrs


class DateRangeSerializer(serializers.Serializer):
    start = serializers.DateField()
    end = serializers.DateField()

    def validate(self, attrs: dict) -> dict:
        if attrs["start"] > attrs["end"]:
            raise serializers.ValidationError("The start date is after the end date.")
        return attrs


class SettingsSerializer(serializers.Serializer):
    """Application preferences — user choices, not deployment facts (§9.3)."""

    reporting_currency = serializers.CharField(max_length=3, required=False)
    rate_staleness_days = serializers.IntegerField(min_value=1, max_value=3650, required=False)
    rate_variance_percent = serializers.DecimalField(
        max_digits=19, decimal_places=10, min_value=Decimal("0.0000000001"), required=False
    )
