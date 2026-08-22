"""Recurring arrangements move from a month key to an anchor date.

Weekly and fortnightly frequencies are the reason. A month key can name which
month a payment falls in but not which Thursday, and a weekly arrangement has
four or five occurrences in a month that all need deciding separately. So the
identity of an occurrence becomes the date it falls on, and a template's start
month plus day-of-month collapse into the one anchor date they were describing
between them.

The order here is deliberate: the new columns are added and filled from the old
ones before anything is dropped. Un-applying does not restore the month keys —
`start_month` was non-nullable, so reversing the drop could not have produced a
usable value anyway.
"""

from __future__ import annotations

import calendar
from datetime import date

from django.db import migrations, models


def _month_last_day(month: str) -> date:
    year, mon = (int(part) for part in month.split("-"))
    return date(year, mon, calendar.monthrange(year, mon)[1])


def _anchor_within(month: str, anchor_day: int | None) -> date:
    """The date a month-keyed period actually fell on, under the old rules."""
    end = _month_last_day(month)
    if anchor_day is None:
        return end
    return end.replace(day=min(anchor_day, end.day))


def forwards(apps, schema_editor):  # noqa: ARG001
    Template = apps.get_model("cashflow", "RecurringTemplate")
    Transaction = apps.get_model("cashflow", "Transaction")
    Dismissal = apps.get_model("cashflow", "RecurringDismissal")

    for template in Template.objects.all():
        template.anchor_date = _anchor_within(template.start_month, template.anchor_day)
        template.end_date = (
            _month_last_day(template.end_month) if template.end_month else None
        )
        template.save(update_fields=["anchor_date", "end_date"])

    # A confirmed transaction's own date *is* the occurrence it satisfied, and it
    # is a better answer than re-deriving one: the user may have moved it.
    for row in Transaction.objects.exclude(recurring_period=None):
        row.recurring_occurrence = row.date
        row.save(update_fields=["recurring_occurrence"])

    for row in Dismissal.objects.select_related("template"):
        row.occurrence = _anchor_within(row.period, row.template.anchor_day)
        row.save(update_fields=["occurrence"])


class Migration(migrations.Migration):

    dependencies = [
        ("cashflow", "0004_recurring_anchor_day"),
    ]

    operations = [
        # -- the new shape, alongside the old ------------------------------
        migrations.AddField(
            model_name="recurringtemplate",
            name="anchor_date",
            field=models.DateField(null=True),
        ),
        migrations.AddField(
            model_name="recurringtemplate",
            name="end_date",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="transaction",
            name="recurring_occurrence",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="recurringdismissal",
            name="occurrence",
            field=models.DateField(null=True),
        ),
        migrations.RunPython(forwards, migrations.RunPython.noop),
        # -- and now the old shape goes -----------------------------------
        migrations.RemoveConstraint(
            model_name="recurringdismissal",
            name="cashflow_one_dismissal_per_period",
        ),
        migrations.RemoveConstraint(
            model_name="recurringtemplate",
            name="cashflow_template_start_is_a_month",
        ),
        migrations.RemoveConstraint(
            model_name="recurringtemplate",
            name="cashflow_template_anchor_is_a_day_of_the_month",
        ),
        migrations.RemoveConstraint(
            model_name="transaction",
            name="cashflow_recurring_period_is_a_month",
        ),
        migrations.RemoveIndex(
            model_name="transaction",
            name="cashflow_txn_recurring",
        ),
        migrations.RemoveField(model_name="recurringdismissal", name="period"),
        migrations.RemoveField(model_name="recurringtemplate", name="anchor_day"),
        migrations.RemoveField(model_name="recurringtemplate", name="end_month"),
        migrations.RemoveField(model_name="recurringtemplate", name="start_month"),
        migrations.RemoveField(model_name="transaction", name="recurring_period"),
        # -- nothing is null any more, so say so --------------------------
        migrations.AlterField(
            model_name="recurringtemplate",
            name="anchor_date",
            field=models.DateField(),
        ),
        migrations.AlterField(
            model_name="recurringdismissal",
            name="occurrence",
            field=models.DateField(),
        ),
        migrations.AlterField(
            model_name="recurringtemplate",
            name="frequency",
            field=models.CharField(
                choices=[
                    ("Weekly", "Weekly"),
                    ("Fortnightly", "Fortnightly"),
                    ("Monthly", "Monthly"),
                ],
                max_length=12,
            ),
        ),
        migrations.AddIndex(
            model_name="transaction",
            index=models.Index(
                fields=["recurring_template", "recurring_occurrence"],
                name="cashflow_txn_recurring",
            ),
        ),
        migrations.AddConstraint(
            model_name="recurringdismissal",
            constraint=models.UniqueConstraint(
                condition=models.Q(("deleted_at__isnull", True)),
                fields=("template", "occurrence"),
                name="cashflow_one_dismissal_per_occurrence",
            ),
        ),
    ]
