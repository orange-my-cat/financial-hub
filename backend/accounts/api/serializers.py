"""Shape and type at the boundary. Business rules live in the services."""

from __future__ import annotations

from decimal import Decimal

from rest_framework import serializers

from core.currencies import CURRENCY_CODES
from core.months import MONTH_PATTERN
from accounts.models import Account, AccountStatus, AccountType, LiquidityTier

MONTH_REGEX = MONTH_PATTERN.pattern


class AccountSerializer(serializers.ModelSerializer):
    is_liability = serializers.BooleanField(read_only=True)
    #: Whether the currency is still changeable. Drives the superscript lock on
    #: the Accounts table, and the availability of Delete.
    currency_locked = serializers.SerializerMethodField()
    has_history = serializers.SerializerMethodField()
    balance_count = serializers.SerializerMethodField()

    class Meta:
        model = Account
        fields = [
            "id",
            "name",
            "account_type",
            "liquidity_tier",
            "status",
            "currency",
            "opened_month",
            "closed_month",
            "is_liability",
            "currency_locked",
            "has_history",
            "balance_count",
        ]
        read_only_fields = ["id", "status", "closed_month"]

    def get_currency_locked(self, account: Account) -> bool:
        return account.balances.exists()

    def get_has_history(self, account: Account) -> bool:
        return account.balances.exists()

    def get_balance_count(self, account: Account) -> int:
        return account.balances.count()


class AccountCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=120)
    account_type = serializers.ChoiceField(choices=AccountType.choices)
    liquidity_tier = serializers.ChoiceField(choices=LiquidityTier.choices)
    currency = serializers.ChoiceField(choices=CURRENCY_CODES)
    opened_month = serializers.RegexField(MONTH_REGEX)


class AccountUpdateSerializer(serializers.Serializer):
    """Name, classification and currency. Status changes have their own actions,
    because closing an account is not the same kind of act as renaming one."""

    name = serializers.CharField(max_length=120, required=False)
    account_type = serializers.ChoiceField(choices=AccountType.choices, required=False)
    liquidity_tier = serializers.ChoiceField(choices=LiquidityTier.choices, required=False)
    currency = serializers.ChoiceField(choices=CURRENCY_CODES, required=False)


class CloseSerializer(serializers.Serializer):
    closed_month = serializers.RegexField(MONTH_REGEX)


class BalanceSerializer(serializers.Serializer):
    # A string in, a Decimal out. Money never crosses as a JSON number (ADR-12).
    amount = serializers.DecimalField(max_digits=19, decimal_places=4)


class MonthQuerySerializer(serializers.Serializer):
    month = serializers.RegexField(MONTH_REGEX)
    currency = serializers.ChoiceField(choices=CURRENCY_CODES, required=False, default="USD")


class RangeQuerySerializer(serializers.Serializer):
    from_month = serializers.RegexField(MONTH_REGEX)
    to_month = serializers.RegexField(MONTH_REGEX)
    currency = serializers.ChoiceField(choices=CURRENCY_CODES, required=False, default="USD")

    def validate(self, attrs: dict) -> dict:
        if attrs["from_month"] > attrs["to_month"]:
            raise serializers.ValidationError("The range starts after it ends.")
        return attrs


class SliceQuerySerializer(MonthQuerySerializer):
    dimension = serializers.ChoiceField(
        choices=["type", "liquidity", "currency", "account"], default="type"
    )


__all__ = [
    "AccountSerializer",
    "AccountCreateSerializer",
    "AccountUpdateSerializer",
    "AccountStatus",
    "BalanceSerializer",
    "CloseSerializer",
    "Decimal",
    "MonthQuerySerializer",
    "RangeQuerySerializer",
    "SliceQuerySerializer",
]
