"""Cash flow endpoints. Thin, like the rest.

Note what is absent: there is no endpoint returning cash flow figures alongside
balance figures, and there never will be. BR-12 is enforced by the shape of the
API rather than by a rule someone has to remember on each new report.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from rest_framework import serializers, status as http
from rest_framework.response import Response
from rest_framework.views import APIView

from core.api.responses import with_advisories
from core.currencies import CURRENCY_CODES
from core.months import MONTH_PATTERN
from core.services.exceptions import NotFoundError
from cashflow.models import Direction, Frequency, RecurringTemplate, Transaction
from cashflow.services import categories, recurring, reporting
from cashflow.services.entry import (
    delete_transaction,
    record_transaction,
    update_transaction,
)

MONTH_REGEX = MONTH_PATTERN.pattern


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------


class TransactionSerializer(serializers.Serializer):
    date = serializers.DateField()
    amount = serializers.DecimalField(max_digits=19, decimal_places=4, min_value=Decimal("0.0001"))
    currency = serializers.ChoiceField(choices=CURRENCY_CODES)
    category_id = serializers.IntegerField()
    note = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
    account_id = serializers.IntegerField(required=False, allow_null=True)


class TransactionUpdateSerializer(serializers.Serializer):
    date = serializers.DateField(required=False)
    amount = serializers.DecimalField(
        max_digits=19, decimal_places=4, min_value=Decimal("0.0001"), required=False
    )
    currency = serializers.ChoiceField(choices=CURRENCY_CODES, required=False)
    category_id = serializers.IntegerField(required=False)
    note = serializers.CharField(max_length=255, required=False, allow_blank=True)


class MonthSerializer(serializers.Serializer):
    month = serializers.RegexField(MONTH_REGEX)


class TrendSerializer(serializers.Serializer):
    from_month = serializers.RegexField(MONTH_REGEX)
    to_month = serializers.RegexField(MONTH_REGEX)
    category_id = serializers.IntegerField(required=False, allow_null=True)


class CategorySerializer(serializers.Serializer):
    name = serializers.CharField(max_length=64)
    parent_id = serializers.IntegerField(required=False, allow_null=True)
    direction = serializers.ChoiceField(choices=Direction.choices, required=False)


class CategoryUpdateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=64, required=False)
    is_active = serializers.BooleanField(required=False)


class TemplateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=120)
    amount = serializers.DecimalField(max_digits=19, decimal_places=4, min_value=Decimal("0.0001"))
    currency = serializers.ChoiceField(choices=CURRENCY_CODES)
    category_id = serializers.IntegerField()
    frequency = serializers.ChoiceField(choices=Frequency.choices)
    start_month = serializers.RegexField(MONTH_REGEX)
    end_month = serializers.RegexField(MONTH_REGEX, required=False, allow_null=True)


class ConfirmSerializer(serializers.Serializer):
    template_id = serializers.IntegerField()
    period = serializers.RegexField(MONTH_REGEX)
    amount = serializers.DecimalField(
        max_digits=19, decimal_places=4, min_value=Decimal("0.0001"), required=False
    )
    date = serializers.DateField(required=False)


def _validated(serializer_class, data):
    serializer = serializer_class(data=data)
    serializer.is_valid(raise_exception=True)
    return serializer.validated_data


def _transaction(pk: int) -> Transaction:
    row = Transaction.objects.filter(pk=pk).first()
    if row is None:
        raise NotFoundError(f"No transaction with id {pk}.", code="transaction_not_found")
    return row


def _payload(row: Transaction) -> dict:
    return {
        "id": row.pk,
        "date": row.date.isoformat(),
        "amount": str(row.amount.quantize(Decimal("0.01"))),
        "currency": row.currency,
        "direction": row.direction,
        "category_id": row.category_id,
        "category": row.category.name,
        "note": row.note,
    }


# ---------------------------------------------------------------------------
# Transactions
# ---------------------------------------------------------------------------


class TransactionListView(APIView):
    def get(self, request):
        query = _validated(MonthSerializer, request.query_params)
        return Response({"data": reporting.transactions_for_month(query["month"])})

    def post(self, request):
        fields = _validated(TransactionSerializer, request.data)
        result = record_transaction(
            on_date=fields["date"],
            amount=fields["amount"],
            currency=fields["currency"],
            category_id=fields["category_id"],
            note=fields.get("note", ""),
            account_id=fields.get("account_id"),
        )
        # The advisory arrives beside a saved transaction. Adding anyway is
        # always permitted (FR-23).
        return with_advisories(
            _payload(result.transaction),
            result.advisories,
            status=http.HTTP_201_CREATED,
        )


class TransactionDetailView(APIView):
    def patch(self, request, pk: int):
        fields = _validated(TransactionUpdateSerializer, request.data)
        result = update_transaction(
            _transaction(pk),
            on_date=fields.get("date"),
            amount=fields.get("amount"),
            currency=fields.get("currency"),
            category_id=fields.get("category_id"),
            note=fields.get("note"),
        )
        return with_advisories(_payload(result.transaction), result.advisories)

    def delete(self, request, pk: int):  # noqa: ARG002
        delete_transaction(_transaction(pk))
        return Response(status=http.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------


class CategoryListView(APIView):
    def get(self, request):  # noqa: ARG002
        return Response({"data": categories.taxonomy()})

    def post(self, request):
        fields = _validated(CategorySerializer, request.data)
        if fields.get("parent_id"):
            category = categories.add_child(fields["parent_id"], fields["name"])
        else:
            category = categories.add_parent(
                fields["name"], fields.get("direction", Direction.EXPENSE)
            )
        return Response(
            {"data": {"id": category.pk, "name": category.name}},
            status=http.HTTP_201_CREATED,
        )


class CategoryDetailView(APIView):
    def patch(self, request, pk: int):
        category = categories.get_category(pk)
        fields = _validated(CategoryUpdateSerializer, request.data)

        if "name" in fields:
            categories.rename(category, fields["name"])
        if "is_active" in fields:
            categories.set_active(category, fields["is_active"])

        return Response({"data": {"id": category.pk, "name": category.name}})

    def delete(self, request, pk: int):  # noqa: ARG002
        categories.delete(categories.get_category(pk))
        return Response(status=http.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Recurring
# ---------------------------------------------------------------------------


class RecurringTemplateView(APIView):
    def get(self, request):  # noqa: ARG002
        rows = RecurringTemplate.objects.select_related("category").all()
        return Response(
            {
                "data": [
                    {
                        "id": row.pk,
                        "name": row.name,
                        "amount": str(row.amount.quantize(Decimal("0.01"))),
                        "currency": row.currency,
                        "direction": row.direction,
                        "category_id": row.category_id,
                        "category": row.category.name,
                        "frequency": row.frequency,
                        "start_month": row.start_month,
                        "end_month": row.end_month,
                        "is_active": row.is_active,
                    }
                    for row in rows
                ]
            }
        )

    def post(self, request):
        fields = _validated(TemplateSerializer, request.data)
        category = categories.get_category(fields["category_id"])
        template = RecurringTemplate.objects.create(
            name=fields["name"],
            amount=fields["amount"],
            currency=fields["currency"],
            direction=category.direction,
            category=category,
            frequency=fields["frequency"],
            start_month=fields["start_month"],
            end_month=fields.get("end_month"),
        )
        return Response({"data": {"id": template.pk}}, status=http.HTTP_201_CREATED)


class ProposalListView(APIView):
    """Outstanding proposals — derived, never stored."""

    def get(self, request):
        through = request.query_params.get("through")
        proposals = recurring.outstanding_proposals(through=through)
        return Response({"data": [proposal.as_dict() for proposal in proposals]})


class ProposalConfirmView(APIView):
    def post(self, request):
        fields = _validated(ConfirmSerializer, request.data)
        result = recurring.confirm(
            fields["template_id"],
            fields["period"],
            amount=fields.get("amount"),
            on_date=fields.get("date"),
        )
        return with_advisories(
            _payload(result.transaction), result.advisories, status=http.HTTP_201_CREATED
        )


class ProposalDismissView(APIView):
    def post(self, request):
        fields = _validated(ConfirmSerializer, request.data)
        recurring.dismiss(fields["template_id"], fields["period"])
        return Response(status=http.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


class CategoryReportView(APIView):
    def get(self, request):
        query = _validated(MonthSerializer, request.query_params)
        return Response(
            {
                "data": {
                    "month": query["month"],
                    # Per currency, never translated. There is no combined
                    # total anywhere in this payload, deliberately.
                    "currencies": reporting.category_report(query["month"]),
                }
            }
        )


class CategoryTrendView(APIView):
    def get(self, request):
        query = _validated(TrendSerializer, request.query_params)
        return Response(
            {
                "data": reporting.category_trend(
                    query["from_month"],
                    query["to_month"],
                    query.get("category_id"),
                )
            }
        )


__all__ = ["date"]
