"""Slices — by type, liquidity tier, currency and account.

Every slice **partitions the net worth service's own per-account output**. None
of them re-reads a balance, re-applies a sign or re-translates anything.

That is the entire design. A slice that summed independently would be a second
definition of net worth, and the day the two disagreed the user would have no
way to tell which was right. Partitioning makes "every slice totals to net
worth" true by construction rather than by testing — though it is tested anyway,
because construction arguments have been wrong before.

Each row also states its share of **gross assets** — what is owned — and not
its share of net worth. Net worth is what remains after the two sides cancel,
so it collapses toward zero in exactly the households the column is most worth
reading, and goes negative in any of them carrying a mortgage; a share of it
inflates without bound and inverts on the sign. Against assets, the asset rows
compose to 100% and each debt is read against what stands behind it.

Toggling between slices is the whole interaction model on the Net worth screen.
There is no drill-down.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from accounts.models import LIABILITY_TYPES, AccountType, LiquidityTier
from accounts.services.net_worth import Contribution, NetWorth


CENTS = Decimal("0.01")
TENTHS = Decimal("0.1")


class SliceDimension(StrEnum):
    TYPE = "type"
    LIQUIDITY = "liquidity"
    CURRENCY = "currency"
    ACCOUNT = "account"


@dataclass(frozen=True)
class SliceRow:
    key: str
    label: str
    #: Full precision, summed from the same translated figures the total used.
    amount: Decimal
    #: True where every member is a liability — the by-type slice labels each
    #: row asset or liability, and liabilities render in Breach with a minus.
    is_liability: bool
    account_count: int
    #: Accounts excluded from the translated total, kept visible in their row.
    excluded_count: int
    #: The row as a proportion of gross. None where the balance sheet is empty.
    percent_of_gross: Decimal | None

    def as_dict(self) -> dict:
        return {
            "key": self.key,
            "label": self.label,
            "amount": str(self.amount.quantize(CENTS)),
            "is_liability": self.is_liability,
            "accounts": self.account_count,
            "excluded": self.excluded_count,
            "percent_of_gross": str(self.percent_of_gross)
            if self.percent_of_gross is not None
            else None,
        }


#: The order rows appear in, so a slice does not reshuffle between months.
_TYPE_ORDER = [choice.value for choice in AccountType]
_TIER_ORDER = [choice.value for choice in LiquidityTier]


def _key_for(contribution: Contribution, dimension: SliceDimension) -> tuple[str, str]:
    if dimension is SliceDimension.TYPE:
        return contribution.account_type, contribution.account_type
    if dimension is SliceDimension.LIQUIDITY:
        return contribution.liquidity_tier, contribution.liquidity_tier
    if dimension is SliceDimension.CURRENCY:
        return contribution.currency, contribution.currency
    return str(contribution.account_id), contribution.name


def _sort_index(dimension: SliceDimension, key: str, label: str) -> tuple:
    if dimension is SliceDimension.TYPE:
        return (_TYPE_ORDER.index(key) if key in _TYPE_ORDER else len(_TYPE_ORDER),)
    if dimension is SliceDimension.LIQUIDITY:
        return (_TIER_ORDER.index(key) if key in _TIER_ORDER else len(_TIER_ORDER),)
    return (label.lower(),)


def gross_assets(net_worth: NetWorth) -> Decimal:
    """What is owned, before anything owed against it.

    Assets only — the liability side is what the column is measuring, so it
    cannot also be in the denominator. Membership is by account type, the
    system's own asset/liability split, not by the sign of a figure: an
    overdrawn current account is an asset holding less than nothing, and
    counting it as a debt would move it between the two sides of the report
    from one month to the next.

    Excluded accounts are left out, exactly as they are left out of the total
    (FR-46). A row measured against money the system declined to count would be
    a proportion of a figure shown nowhere.
    """
    return sum(
        (c.translated for c in net_worth.included if not c.is_liability), Decimal(0)
    )


def _share(amount: Decimal, total: Decimal) -> Decimal | None:
    """A row as a proportion of gross assets, keeping its own sign.

    Assets compose: on a slice where no row mixes the two sides, they make
    100%. Liabilities are read *against* what is owned and are unbounded by
    design — a mortgage at -263% is the statement that the debt is two and a
    half times everything on the other side, which is the comparison the column
    exists to make and one net worth cannot express.

    Null against a balance sheet holding no assets, for the same reason the
    month-on-month percentage is null against a zero prior month: a proportion
    of nothing is not a figure. The amount beside it is still real.
    """
    if total == 0:
        return None
    return (amount / total * 100).quantize(TENTHS)


def slice_net_worth(net_worth: NetWorth, dimension: SliceDimension) -> tuple[SliceRow, ...]:
    """Partition, never re-sum from source."""
    buckets: dict[str, dict] = {}

    for contribution in net_worth.contributions:
        key, label = _key_for(contribution, dimension)
        bucket = buckets.setdefault(
            key,
            {
                "label": label,
                "amount": Decimal(0),
                "liability": True,
                "accounts": 0,
                "excluded": 0,
            },
        )
        bucket["accounts"] += 1
        if contribution.is_excluded:
            bucket["excluded"] += 1
        else:
            # The same translated figure that went into the total. Not a
            # recomputation of it.
            bucket["amount"] += contribution.translated
        if not contribution.is_liability:
            bucket["liability"] = False

    # Computed once from the same contributions the rows partition, so a given
    # account holds the same share in every slice.
    denominator = gross_assets(net_worth)

    rows = [
        SliceRow(
            key=key,
            label=bucket["label"],
            amount=bucket["amount"],
            is_liability=bucket["liability"],
            account_count=bucket["accounts"],
            excluded_count=bucket["excluded"],
            percent_of_gross=_share(bucket["amount"], denominator),
        )
        for key, bucket in buckets.items()
    ]

    rows.sort(key=lambda row: _sort_index(dimension, row.key, row.label))
    return tuple(rows)


def is_liability_type(account_type: str) -> bool:
    return account_type in LIABILITY_TYPES
