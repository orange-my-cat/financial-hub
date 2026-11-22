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
from core.currencies import BASE_CURRENCY, CURRENCY_CODES, REPORTING_CURRENCY_CODES
from core.months import MONTH_PATTERN
from core.services.exceptions import NotFoundError
from cashflow.models import Direction, Frequency, RecurringTemplate, Transaction
from cashflow.services import categories, recurring, reporting, summary
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


class MonthCurrencySerializer(serializers.Serializer):
    """A month, and the currency to state it in.

    The reporting currencies only. Gold denominates a balance and is never a
    unit a report is stated in (OI-01), so a month recorded in XAU is
    translated like any other currency and never stated as one.
    """

    month = serializers.RegexField(MONTH_REGEX)
    currency = serializers.ChoiceField(
        choices=REPORTING_CURRENCY_CODES, default=BASE_CURRENCY
    )


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
    #: The first occurrence. Every later one is counted from it.
    anchor_date = serializers.DateField()
    end_date = serializers.DateField(required=False, allow_null=True)


class TemplateUpdateSerializer(serializers.Serializer):
    amount = serializers.DecimalField(
        max_digits=19, decimal_places=4, min_value=Decimal("0.0001"), required=False
    )
    category_id = serializers.IntegerField(required=False)
    #: Moves forward only — the old rhythm keeps every date before it.
    anchor_date = serializers.DateField(required=False)


class RestartTemplateSerializer(serializers.Serializer):
    anchor_date = serializers.DateField()
    frequency = serializers.ChoiceField(choices=Frequency.choices)


class EndTemplateSerializer(serializers.Serializer):
    #: Optional. Omitted, the template stops proposing from now on.
    end_date = serializers.DateField(required=False, allow_null=True)


class ConfirmSerializer(serializers.Serializer):
    template_id = serializers.IntegerField()
    #: Which occurrence is being decided, by the date it falls on.
    occurrence = serializers.DateField()
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
    # One serialiser for the month list, entry and edit alike, so the row the
    # client renders after saving is the row it would have refetched.
    return reporting.transaction_row(row)


# ---------------------------------------------------------------------------
# Transactions
# ---------------------------------------------------------------------------


class TransactionListView(APIView):
    def get(self, request):
        # The currency is the reporting one the header is set to, and it is what
        # the restated column beside each amount is stated in. Every row keeps
        # the currency it was entered in either way; naming this one adds a
        # column, it never rewrites a figure.
        query = _validated(MonthCurrencySerializer, request.query_params)
        return Response(
            {"data": summary.transaction_list(query["month"], query["currency"])}
        )

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


def _template_payload(row: RecurringTemplate) -> dict:
    # One shape for the list and for whatever an action returns, so the row the
    # client renders after ending a template is the row it would have refetched.
    return {
        "id": row.pk,
        "name": row.name,
        "amount": str(row.amount.quantize(Decimal("0.01"))),
        "currency": row.currency,
        "direction": row.direction,
        "category_id": row.category_id,
        "category": row.category.name,
        "parent": row.category.parent.name if row.category.parent_id else row.category.name,
        "frequency": row.frequency,
        "anchor_date": row.anchor_date.isoformat(),
        "end_date": row.end_date.isoformat() if row.end_date else None,
        # Read from the end date, not the stored flag, which goes stale once a
        # future end date passes.
        "is_active": not recurring.has_ended(row),
    }


class RecurringTemplateView(APIView):
    def get(self, request):  # noqa: ARG002
        return Response({"data": [_template_payload(row) for row in recurring.templates()]})

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
            anchor_date=fields["anchor_date"],
            end_date=fields.get("end_date"),
        )
        return Response({"data": {"id": template.pk}}, status=http.HTTP_201_CREATED)


class RecurringDetailView(APIView):
    """Amend amount, category or anchor. Confirmed transactions never change."""

    def patch(self, request, pk: int):
        fields = _validated(TemplateUpdateSerializer, request.data)
        template = recurring.update_template(recurring.get_template(pk), **fields)
        return Response({"data": _template_payload(template)})


class RecurringRestartView(APIView):
    """Start an ended template again on a new anchor and cadence."""

    def post(self, request, pk: int):
        fields = _validated(RestartTemplateSerializer, request.data)
        template = recurring.restart_template(recurring.get_template(pk), **fields)
        return Response({"data": _template_payload(template)})


class RecurringEndView(APIView):
    """Stop future proposals. History is untouched (BR-14)."""

    def post(self, request, pk: int):
        fields = _validated(EndTemplateSerializer, request.data)
        template = recurring.end_template(
            recurring.get_template(pk), end_date=fields.get("end_date")
        )
        return Response({"data": _template_payload(template)})


class ProposalListView(APIView):
    """The month's outstanding proposals — derived, never stored.

    The month is required rather than defaulted. This screen always knows which
    month it is showing, and a request that omitted it would be answered with a
    list about some other month, which is the failure the parameter exists to
    prevent. Occurrences outside it are not lost: the dashboard's tasks panel
    counts every one still awaiting a decision (OI-09).
    """

    def get(self, request):
        query = _validated(MonthSerializer, request.query_params)
        proposals = recurring.proposals_for_month(query["month"])
        return Response({"data": [proposal.as_dict() for proposal in proposals]})


class ProposalConfirmView(APIView):
    def post(self, request):
        fields = _validated(ConfirmSerializer, request.data)
        result = recurring.confirm(
            fields["template_id"],
            fields["occurrence"],
            amount=fields.get("amount"),
            on_date=fields.get("date"),
        )
        return with_advisories(
            _payload(result.transaction), result.advisories, status=http.HTTP_201_CREATED
        )


class ProposalDismissView(APIView):
    def post(self, request):
        fields = _validated(ConfirmSerializer, request.data)
        recurring.dismiss(fields["template_id"], fields["occurrence"])
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


class CategoryFlowView(APIView):
    """The month's categories combined into one currency.

    A separate endpoint rather than a parameter on the category report, because
    the two answer different questions and only one of them translates. A
    response that could do either would need a reader to check which it had
    done before trusting a total.
    """

    def get(self, request):
        query = _validated(MonthCurrencySerializer, request.query_params)
        return Response(
            {"data": summary.category_flow(query["month"], query["currency"])}
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
