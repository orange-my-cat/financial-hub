"""Investments endpoints. Thin, and computing nothing.

Every figure returned came out of the replay engine, which is a pure function
over the transactions. There is no cached position, no stored cost basis and no
stored gain to go stale.
"""

from __future__ import annotations

from decimal import Decimal

from rest_framework import serializers, status as http
from rest_framework.response import Response
from rest_framework.views import APIView

from core.currencies import CURRENCY_CODES
from investments.models import Holding, InstrumentType, InvestmentTransaction
from investments.replay import Action
from investments.services.positions import (
    HoldingPosition,
    get_holding,
    positions,
    realised_gains_by_currency,
    record,
    replay_holding,
)

#: Stated in copy on the screen, and returned by the API so the screen cannot
#: forget them (BR-17, BR-21).
PROHIBITIONS = {
    "unrealised_gain": (
        "Unrealised gain does not exist in this system. No market prices are "
        "held, so there is no paper gain, no portfolio return percentage and no "
        "total return anywhere."
    ),
    "estimated_tax": (
        "Estimated tax is a percentage you typed, not a calculation. No "
        "jurisdiction's rules, holding periods, allowances or thresholds are "
        "applied. Every net figure is indicative."
    ),
}


class HoldingSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=120)
    symbol = serializers.CharField(max_length=32, required=False, allow_blank=True, default="")
    instrument_type = serializers.ChoiceField(
        choices=InstrumentType.choices, default=InstrumentType.EQUITY
    )
    currency = serializers.ChoiceField(choices=CURRENCY_CODES)
    account_id = serializers.IntegerField()
    estimated_tax_percent = serializers.DecimalField(
        max_digits=19, decimal_places=10, min_value=Decimal("0"), required=False, allow_null=True
    )


class HoldingUpdateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=120, required=False)
    symbol = serializers.CharField(max_length=32, required=False, allow_blank=True)
    instrument_type = serializers.ChoiceField(choices=InstrumentType.choices, required=False)
    estimated_tax_percent = serializers.DecimalField(
        max_digits=19, decimal_places=10, min_value=Decimal("0"), required=False, allow_null=True
    )


class TransactionSerializer(serializers.Serializer):
    action = serializers.ChoiceField(choices=[a.value for a in Action])
    date = serializers.DateField()
    quantity = serializers.DecimalField(max_digits=19, decimal_places=10, required=False, default=Decimal(0))
    unit_price = serializers.DecimalField(max_digits=19, decimal_places=8, required=False, default=Decimal(0))
    fees = serializers.DecimalField(max_digits=19, decimal_places=4, required=False, default=Decimal(0))
    split_ratio = serializers.DecimalField(max_digits=19, decimal_places=10, required=False, default=Decimal(0))
    cash_amount = serializers.DecimalField(max_digits=19, decimal_places=4, required=False, default=Decimal(0))
    note = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")


def _validated(serializer_class, data):
    serializer = serializer_class(data=data)
    serializer.is_valid(raise_exception=True)
    return serializer.validated_data


class HoldingListView(APIView):
    def get(self, request):  # noqa: ARG002
        return Response(
            {
                "data": {
                    "holdings": [position.as_dict() for position in positions()],
                    "prohibitions": PROHIBITIONS,
                }
            }
        )

    def post(self, request):
        fields = _validated(HoldingSerializer, request.data)
        holding = Holding.objects.create(**fields)
        return Response(
            {"data": HoldingPosition(holding, replay_holding(holding)).as_dict()},
            status=http.HTTP_201_CREATED,
        )


class HoldingDetailView(APIView):
    def get(self, request, pk: int):  # noqa: ARG002
        holding = get_holding(pk)
        result = replay_holding(holding)
        return Response(
            {
                "data": {
                    **HoldingPosition(holding, result).as_dict(),
                    "transactions": [
                        {
                            "id": row.pk,
                            "action": row.action,
                            "date": row.date.isoformat(),
                            "quantity": str(row.quantity),
                            "unit_price": str(row.unit_price),
                            "fees": str(row.fees),
                            "split_ratio": str(row.split_ratio),
                            "cash_amount": str(row.cash_amount),
                            "note": row.note,
                        }
                        for row in holding.transactions.all()
                    ],
                }
            }
        )

    def patch(self, request, pk: int):
        holding = get_holding(pk)
        fields = _validated(HoldingUpdateSerializer, request.data)
        for field, value in fields.items():
            setattr(holding, field, value)
        holding.save()
        # Changing the percentage restates the net figure on all historic sales,
        # including sales already reported (BR-21). Free, because nothing was
        # stored.
        return Response({"data": HoldingPosition(holding, replay_holding(holding)).as_dict()})

    def delete(self, request, pk: int):  # noqa: ARG002
        get_holding(pk).delete()
        return Response(status=http.HTTP_204_NO_CONTENT)


class HoldingTransactionView(APIView):
    def post(self, request, pk: int):
        holding = get_holding(pk)
        fields = _validated(TransactionSerializer, request.data)

        row = record(
            holding,
            action=fields["action"],
            on_date=fields["date"],
            quantity=fields["quantity"],
            unit_price=fields["unit_price"],
            fees=fields["fees"],
            split_ratio=fields["split_ratio"],
            cash_amount=fields["cash_amount"],
            note=fields["note"],
        )

        return Response(
            {
                "data": {
                    "id": row.pk,
                    "position": HoldingPosition(holding, replay_holding(holding)).as_dict(),
                }
            },
            status=http.HTTP_201_CREATED,
        )


class TransactionDetailView(APIView):
    def delete(self, request, pk: int):  # noqa: ARG002
        row = InvestmentTransaction.objects.filter(pk=pk).first()
        if row is None:
            return Response(status=http.HTTP_404_NOT_FOUND)
        row.delete()
        return Response(status=http.HTTP_204_NO_CONTENT)


class RealisedGainsView(APIView):
    def get(self, request):
        year = request.query_params.get("year")
        return Response(
            {
                "data": {
                    "currencies": realised_gains_by_currency(int(year) if year else None),
                    "prohibitions": PROHIBITIONS,
                }
            }
        )
