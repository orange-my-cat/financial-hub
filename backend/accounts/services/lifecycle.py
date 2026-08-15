"""An account's own state: dormancy, closure, reclassification, deletion.

Two rules here have consequences beyond the row being edited.

**Reclassification restates history** (BR-07). Type and liquidity tier are
properties of the account, not of a point in time, so changing either
immediately restates every historic report as though the new value had always
applied. Crossing the asset/liability boundary reverses the sign of that
account's contribution in every month it appears in — which changes historic
net worth. The user is told how many months change, and **both actions save**:
it is an advisory, not a confirmation dialogue, because confirmation dialogues
are dismissed reflexively and this is a rank-one concern.

**Deletion is narrowed** (ADR-14). An account with no recorded balance can be
removed outright — an account created in error should be removable. Once history
exists, closure is the only route, because deleting an account with years of
balances has no legitimate use that closing it does not serve better.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.db import transaction

from core.months import require_month
from core.services.advisories import Advisory, AdvisoryKind
from core.services.exceptions import BusinessRuleError, ConflictError
from accounts.models import Account, AccountStatus, Balance, is_liability


@dataclass(frozen=True)
class LifecycleResult:
    account: Account
    advisories: tuple[Advisory, ...] = ()


def _months_affected(account: Account) -> int:
    return account.balances.count()


def restatement_advisory(account: Account, new_type: str, new_tier: str) -> Advisory | None:
    """Names how many months change, and how.

    Returns None where nothing historic moves — a tier change on an account with
    no balances restates nothing, and saying otherwise trains the user to
    dismiss the advisory without reading it.
    """
    months = _months_affected(account)
    if months == 0:
        return None

    crosses_boundary = is_liability(account.account_type) != is_liability(new_type)
    type_changed = account.account_type != new_type
    tier_changed = account.liquidity_tier != new_tier

    if not type_changed and not tier_changed:
        return None

    if crosses_boundary:
        message = (
            f"{account.name} moves from "
            f"{'liability' if is_liability(account.account_type) else 'asset'} to "
            f"{'liability' if is_liability(new_type) else 'asset'}. This reverses "
            f"the sign of its balance in all {months} recorded month"
            f"{'s' if months != 1 else ''}, changing historic net worth. Saving "
            f"either way."
        )
    else:
        message = (
            f"{account.name} is reclassified. All {months} recorded month"
            f"{'s' if months != 1 else ''} are restated as though the new "
            f"classification had always applied. Net worth is unchanged."
        )

    return Advisory(
        kind=AdvisoryKind.HISTORIC_RESTATEMENT,
        message=message,
        detail={
            "account_id": account.pk,
            "account": account.name,
            "months_affected": months,
            "crosses_asset_liability_boundary": crosses_boundary,
            "from_type": account.account_type,
            "to_type": new_type,
            "from_tier": account.liquidity_tier,
            "to_tier": new_tier,
        },
    )


@transaction.atomic
def reclassify(account: Account, *, account_type: str, liquidity_tier: str) -> LifecycleResult:
    """Change type and/or tier. Always saves; advises when history moves."""
    advisory = restatement_advisory(account, account_type, liquidity_tier)

    account.account_type = account_type
    account.liquidity_tier = liquidity_tier
    account.save(update_fields=["account_type", "liquidity_tier", "updated_at"])

    return LifecycleResult(account=account, advisories=(advisory,) if advisory else ())


def set_dormant(account: Account) -> LifecycleResult:
    """Stop requiring a balance each month; carry the last one forward.

    Dormant accounts are excluded from the completeness requirement and are
    still included in net worth at their carried-forward balance, flagged stale
    (BR-03, BR-04).
    """
    if account.status == AccountStatus.CLOSED:
        raise BusinessRuleError(
            f"{account.name} is closed. A closed account cannot be made dormant.",
            code="account_closed",
        )
    if not account.balances.exists():
        raise BusinessRuleError(
            f"{account.name} has no recorded balance to carry forward, so making "
            f"it dormant would exclude it from every month while contributing "
            f"nothing. Close it instead, or record a balance first.",
            code="dormant_without_history",
        )

    account.status = AccountStatus.DORMANT
    account.save(update_fields=["status", "updated_at"])
    return LifecycleResult(account=account)


def reopen(account: Account) -> LifecycleResult:
    account.status = AccountStatus.OPEN
    account.closed_month = None
    account.save(update_fields=["status", "closed_month", "updated_at"])
    return LifecycleResult(account=account)


def close(account: Account, closed_month: str) -> LifecycleResult:
    """Close with a date. History is preserved; later months exclude it."""
    require_month(closed_month)

    if closed_month < account.opened_month:
        raise BusinessRuleError(
            f"{account.name} opened in {account.opened_month}; it cannot close in "
            f"{closed_month}.",
            code="closed_before_opened",
            field="closed_month",
        )

    latest = account.balances.order_by("-month").values_list("month", flat=True).first()
    if latest is not None and latest > closed_month:
        raise ConflictError(
            f"{account.name} has a balance recorded for {latest}, which is after "
            f"the closing month {closed_month}. Delete that balance first, or "
            f"close later.",
            code="balance_after_closure",
            field="closed_month",
        )

    account.status = AccountStatus.CLOSED
    account.closed_month = closed_month
    account.save(update_fields=["status", "closed_month", "updated_at"])
    return LifecycleResult(account=account)


def delete_account(account: Account) -> None:
    """Permitted only while the account has no recorded balance (ADR-14).

    Still a soft delete, so even this is administratively recoverable.
    """
    if account.balances.exists():
        raise BusinessRuleError(
            f"{account.name} has {account.balances.count()} recorded balance"
            f"{'s' if account.balances.count() != 1 else ''}. An account with "
            f"history is closed, never deleted — closing preserves the history "
            f"and excludes the account from later months.",
            code="account_has_history",
        )
    account.delete()


def change_currency(account: Account, currency: str) -> LifecycleResult:
    """Refused once balances exist (BR-08).

    The database refuses this too, by trigger. This exists to say why, in words,
    before the database says it in an exception.
    """
    if account.currency == currency:
        return LifecycleResult(account=account)

    if account.balances.exists():
        raise BusinessRuleError(
            f"{account.name} holds recorded balances, so its currency is fixed. "
            f"Correcting a currency mistake requires a new account.",
            code="currency_locked",
            field="currency",
        )

    account.currency = currency
    account.save(update_fields=["currency", "updated_at"])
    return LifecycleResult(account=account)


# ---------------------------------------------------------------------------
# Balances
# ---------------------------------------------------------------------------


def upsert_balance(account: Account, month: str, amount) -> Balance:
    """Create-or-replace. A second balance for the same month is impossible.

    Month Close autosaves on blur, one field at a time, and each upsert
    addresses a distinct (account, month) key — so several in flight at once
    cannot conflict (§9.5). Month Close as a whole is deliberately not a
    transaction: a partly closed month is a legitimate state, not an error
    requiring rollback (§9.6).
    """
    require_month(month)

    if month < account.opened_month:
        raise BusinessRuleError(
            f"{account.name} opened in {account.opened_month}. A balance cannot "
            f"be recorded for {month}.",
            code="balance_before_opening",
            field="month",
        )
    if account.closed_month is not None and month > account.closed_month:
        raise BusinessRuleError(
            f"{account.name} closed in {account.closed_month}. A balance cannot "
            f"be recorded for {month}.",
            code="balance_after_closure",
            field="month",
        )

    balance, _ = Balance.objects.update_or_create(
        account=account, month=month, defaults={"amount": amount}
    )
    return balance


def delete_balance(account: Account, month: str) -> None:
    balance = account.balances.filter(month=month).first()
    if balance is None:
        raise BusinessRuleError(
            f"No balance is recorded for {account.name} in {month}.",
            code="balance_not_found",
        )
    balance.delete()
