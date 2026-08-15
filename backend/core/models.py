"""The soft-delete base every model in this system inherits from.

Deletes are soft, everywhere (ADR-03). A deleted row vanishes from every screen,
report, export and calculation, and stays recoverable through the Django admin.
There is no audit trail and no change history — the design decided against both
— so soft delete is the entire safety net under an accidental deletion, and it
is centralised here rather than reimplemented per model.
"""

from __future__ import annotations

from decimal import Decimal

from django.db import models
from django.utils import timezone

# ---------------------------------------------------------------------------
# Precision — ADR-02
# ---------------------------------------------------------------------------
# Money is exact decimal and never a float, at full precision throughout,
# rounded once at display, half-up. These are the only three shapes a number
# takes in this system; anything that does not fit one of them is not a number
# this system stores.

MONEY_DIGITS, MONEY_PLACES = 19, 4        # amounts
QUANTITY_DIGITS, QUANTITY_PLACES = 19, 10  # unit quantities and FX rates
PRICE_DIGITS, PRICE_PLACES = 19, 8         # unit prices

ZERO = Decimal("0")


def money_field(**kwargs) -> models.DecimalField:
    """NUMERIC(19,4). Never a FloatField, and the helper exists so it cannot be."""
    kwargs.setdefault("max_digits", MONEY_DIGITS)
    kwargs.setdefault("decimal_places", MONEY_PLACES)
    return models.DecimalField(**kwargs)


def quantity_field(**kwargs) -> models.DecimalField:
    """NUMERIC(19,10). Unit quantities and exchange rates."""
    kwargs.setdefault("max_digits", QUANTITY_DIGITS)
    kwargs.setdefault("decimal_places", QUANTITY_PLACES)
    return models.DecimalField(**kwargs)


def price_field(**kwargs) -> models.DecimalField:
    """NUMERIC(19,8). Unit prices."""
    kwargs.setdefault("max_digits", PRICE_DIGITS)
    kwargs.setdefault("decimal_places", PRICE_PLACES)
    return models.DecimalField(**kwargs)


# ---------------------------------------------------------------------------
# Soft delete
# ---------------------------------------------------------------------------


class SoftDeleteQuerySet(models.QuerySet):
    """A queryset whose ``delete()`` marks rather than removes."""

    def delete(self):
        return self.update(deleted_at=timezone.now())

    def hard_delete(self):
        """Genuinely remove the rows.

        Used by exactly one rule in this system: an account may be removed
        outright while it has no recorded balances, because an account created
        in error should be removable. Once history exists, closure is the only
        route (ADR-14).
        """
        return super().delete()

    def alive(self):
        return self.filter(deleted_at__isnull=True)

    def dead(self):
        return self.filter(deleted_at__isnull=False)

    def restore(self):
        return self.update(deleted_at=None)


class LiveManager(models.Manager.from_queryset(SoftDeleteQuerySet)):
    """The default manager. Deleted rows are simply not there."""

    def get_queryset(self) -> SoftDeleteQuerySet:
        return super().get_queryset().filter(deleted_at__isnull=True)


class AllObjectsManager(models.Manager.from_queryset(SoftDeleteQuerySet)):
    """Unfiltered. The admin's view, and the base manager."""


class SoftDeleteModel(models.Model):
    """Timestamps plus a deletion mark. Every model in this system inherits it."""

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(null=True, blank=True, default=None, db_index=True)

    # `objects` is declared first, so it is the default manager: every query
    # written without thinking about deletion excludes deleted rows, which is
    # the behaviour that has to be free.
    objects = LiveManager()
    all_objects = AllObjectsManager()

    class Meta:
        abstract = True
        # Deliberately the unfiltered manager. Django uses the base manager for
        # related-object traversal, and a filtered base manager turns a
        # soft-deleted parent into a DoesNotExist raised from somewhere
        # unrelated — the class of bug the Django documentation warns about
        # specifically. Filtering is the services' job, on explicit querysets;
        # it is not something to smuggle into the ORM's internals.
        base_manager_name = "all_objects"

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None

    def delete(self, using=None, keep_parents=False):  # noqa: ARG002
        self.deleted_at = timezone.now()
        self.save(using=using, update_fields=["deleted_at", "updated_at"])
        return (1, {self._meta.label: 1})

    def hard_delete(self, using=None, keep_parents=False):
        return super().delete(using=using, keep_parents=keep_parents)

    def restore(self, using=None):
        self.deleted_at = None
        self.save(using=using, update_fields=["deleted_at", "updated_at"])
