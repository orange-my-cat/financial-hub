"""One event, one row.

BR-20 had two actions where users had one event: a Distribution that paid cash
and a Reinvestment that bought units with it. A dividend reinvestment plan
therefore took two entries against the same holding on the same date, and the
dev database shows exactly that — nine Distribution rows, nine Reinvestment rows,
paired one to one, noted "Distribution, reinvested" and "Distribution
reinvestment".

At the Product Owner's instruction they are now a single Reinvestment carrying
both facts, and a distribution taken as cash is not entered at all. This moves
the existing data to that shape.

**Every figure is preserved.** A merged pair keeps its cash on the surviving row,
so the holding's distributions total is unchanged, and it keeps the surviving
row's quantity, price and fees, so cost basis and the FIFO queue are untouched.
An unpaired distribution — cash that bought nothing — is converted in place with
its quantity left at zero, which opens no lot (replay drops zero-quantity lots),
so its cash survives and nothing else moves.

The merged Distribution row is deleted outright rather than soft-deleted, which
is the one place this project departs from ADR-03. A soft-deleted row would keep
an `action` the vocabulary no longer has, and restoring it would count the same
cash twice. The event is not lost — it is the row that survived. The production
entrypoint dumps before it migrates, so the pre-merge state is restorable for
thirty snapshots either way.
"""

from __future__ import annotations

from decimal import Decimal

from django.db import migrations


def merge(apps, schema_editor) -> None:
    transactions = apps.get_model("investments", "InvestmentTransaction")

    # Live rows only for pairing: a deleted distribution has no live event to
    # merge into, and pairing across the deletion mark would resurrect it.
    for dist in transactions.objects.filter(
        action="Distribution", deleted_at__isnull=True
    ).order_by("holding_id", "date", "sequence"):
        pair = (
            transactions.objects.filter(
                holding_id=dist.holding_id,
                date=dist.date,
                action="Reinvestment",
                cash_amount=Decimal("0"),
                deleted_at__isnull=True,
            )
            .order_by("sequence")
            .first()
        )

        if pair is None:
            # Cash that bought nothing. Kept, as the one action that can now
            # hold it, with no units and therefore no lot.
            dist.action = "Reinvestment"
            dist.save(update_fields=["action"])
            continue

        pair.cash_amount = dist.cash_amount
        # The surviving row's own note wins; the distribution's is taken only
        # where the reinvestment had nothing to say.
        if not pair.note and dist.note:
            pair.note = dist.note
        pair.save(update_fields=["cash_amount", "note"])
        dist.delete()

    # Already-deleted distributions are renamed where they lie. Nothing reads
    # them, but a row restored through the admin has to replay, and an action
    # outside the vocabulary would raise rather than replay.
    transactions.objects.filter(action="Distribution", deleted_at__isnull=False).update(
        action="Reinvestment"
    )


def split(apps, schema_editor) -> None:
    """Back to two rows, which is what the old vocabulary could express.

    Every reinvestment carrying cash becomes a cash Distribution plus a
    cash-free Reinvestment on the same date — the shape this migration merged,
    and the only shape the two-action model had for the event.
    """
    transactions = apps.get_model("investments", "InvestmentTransaction")

    for row in transactions.objects.exclude(cash_amount=Decimal("0")).filter(
        action="Reinvestment"
    ):
        # Cash that bought no units was a distribution and nothing else, so it
        # goes back as one rather than leaving an empty reinvestment behind.
        if row.quantity == Decimal("0"):
            row.action = "Distribution"
            row.save(update_fields=["action"])
            continue

        transactions.objects.create(
            holding_id=row.holding_id,
            action="Distribution",
            date=row.date,
            # Ahead of the reinvestment on the day, because the cash arrived
            # before it bought anything.
            sequence=max(row.sequence - 1, 0),
            quantity=Decimal("0"),
            unit_price=Decimal("0"),
            fees=Decimal("0"),
            split_ratio=Decimal("0"),
            cash_amount=row.cash_amount,
            note=row.note,
            deleted_at=row.deleted_at,
        )
        row.cash_amount = Decimal("0")
        row.save(update_fields=["cash_amount"])


class Migration(migrations.Migration):
    dependencies = [
        ("investments", "0003_alter_investmenttransaction_action"),
    ]

    operations = [migrations.RunPython(merge, split)]
