"""Translation — the single cross-currency path, and what it does when it can't.

The case worth the most attention is the one where there is no rate. FR-46 says
the account is excluded, the omission is stated, and the balance is never
treated as zero. Here that is structural rather than remembered: an
untranslatable result has no amount at all, so it cannot be summed by accident.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from core.money import Money
from core.services.rate_lookup import Provenance
from core.services.translation import TranslationService
from fx.models import ExchangeRate

pytestmark = [pytest.mark.django_db, pytest.mark.invariant]

JAN_31 = date(2026, 1, 31)


def rate(currency: str, on: date, value: str) -> None:
    ExchangeRate.objects.create(currency=currency, rate_date=on, rate=Decimal(value))


def test_translating_from_aud_to_usd():
    rate("AUD", JAN_31, "0.66")

    result = TranslationService().translate(Money(Decimal("1000"), "AUD"), "USD", JAN_31)

    assert result.is_translatable
    assert result.amount == Decimal("660.00")
    assert result.money == Money(Decimal("660.00"), "USD")
    assert result.quote.provenance is Provenance.EXACT


def test_translating_from_myr_to_usd_uses_its_own_convention():
    rate("MYR", JAN_31, "4.20")

    result = TranslationService().translate(Money(Decimal("4200"), "MYR"), "USD", JAN_31)

    assert result.money.rounded() == Decimal("1000.00")


def test_translating_to_the_same_currency_is_the_identity():
    result = TranslationService().translate(Money(Decimal("123.45"), "USD"), "USD", JAN_31)

    assert result.amount == Decimal("123.45")
    assert result.quote.factor == Decimal(1)


def test_a_triangulated_translation_is_labelled_derived():
    rate("AUD", JAN_31, "0.66")
    rate("MYR", JAN_31, "4.20")

    result = TranslationService().translate(Money(Decimal("100"), "AUD"), "MYR", JAN_31)

    assert result.quote.provenance is Provenance.TRIANGULATED
    assert result.amount == Decimal("277.200")


def test_full_precision_is_carried_and_rounded_once():
    rate("AUD", JAN_31, "0.6666666666")

    result = TranslationService().translate(Money(Decimal("3"), "AUD"), "USD", JAN_31)

    assert result.amount == Decimal("1.9999999998")
    assert result.money.rounded() == Decimal("2.00")


# ---------------------------------------------------------------------------
# FR-46 — a missing rate excludes, it never zeroes
# ---------------------------------------------------------------------------


def test_an_untranslatable_amount_has_no_amount_at_all():
    result = TranslationService().translate(Money(Decimal("1000"), "AUD"), "USD", JAN_31)

    assert result.is_translatable is False
    assert result.amount is None
    assert result.quote is None


def test_an_untranslatable_amount_is_not_zero():
    """The distinction the whole design turns on: unknown is not nothing."""
    result = TranslationService().translate(Money(Decimal("1000"), "AUD"), "USD", JAN_31)

    assert result.amount is not Decimal(0)
    assert result.amount != Decimal(0)


def test_reading_the_money_of_an_untranslatable_result_raises():
    """A caller that skipped the check is a caller about to total an unknown."""
    result = TranslationService().translate(Money(Decimal("1000"), "AUD"), "USD", JAN_31)

    with pytest.raises(ValueError, match="never treated as zero"):
        _ = result.money


def test_the_exclusion_states_which_pair_and_which_date():
    result = TranslationService().translate(Money(Decimal("1000"), "AUD"), "USD", JAN_31)

    assert "AUD/USD" in result.exclusion_reason
    assert "31 Jan 2026" in result.exclusion_reason


def test_the_source_amount_survives_an_exclusion():
    """The excluded row keeps its own-currency figure and its place in the table."""
    result = TranslationService().translate(Money(Decimal("1000"), "AUD"), "USD", JAN_31)

    assert result.source == Money(Decimal("1000"), "AUD")


# ---------------------------------------------------------------------------
# Staleness and as-at
# ---------------------------------------------------------------------------


def test_a_carried_rate_reports_its_as_at_date():
    rate("AUD", date(2026, 1, 20), "0.66")

    result = TranslationService(staleness_days=30).translate(
        Money(Decimal("100"), "AUD"), "USD", JAN_31
    )

    assert result.as_at == date(2026, 1, 20)
    assert result.is_stale is False
    assert result.quote.provenance is Provenance.CARRIED


def test_a_stale_rate_is_flagged_but_still_translates():
    """Refusing would make net worth uncomputable because of a lapse in typing."""
    rate("AUD", date(2025, 6, 30), "0.66")

    result = TranslationService(staleness_days=7).translate(
        Money(Decimal("100"), "AUD"), "USD", JAN_31
    )

    assert result.is_translatable
    assert result.is_stale is True
    assert result.amount == Decimal("66.00")


def test_the_threshold_comes_from_settings():
    from core.models import Settings

    settings_row = Settings.load()
    settings_row.rate_staleness_days = 90
    settings_row.save()
    rate("AUD", date(2026, 1, 1), "0.66")

    service = TranslationService.from_settings()
    result = service.translate(Money(Decimal("100"), "AUD"), "USD", JAN_31)

    assert result.is_stale is False


def test_editing_a_historic_rate_restates_the_translation():
    """No computed figure is persisted, so there is nothing to invalidate."""
    rate("AUD", JAN_31, "0.66")
    amount = Money(Decimal("1000"), "AUD")
    assert TranslationService().translate(amount, "USD", JAN_31).amount == Decimal("660.00")

    row = ExchangeRate.objects.get(currency="AUD", rate_date=JAN_31)
    row.rate = Decimal("0.70")
    row.save()

    assert TranslationService().translate(amount, "USD", JAN_31).amount == Decimal("700.00")
