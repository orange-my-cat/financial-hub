"""Backfill daily closing rates from the provider.

    python manage.py load_rates --from 2016-01-01
    python manage.py load_rates --from 2026-08-01 --to 2026-08-14 --dry-run
    python manage.py load_rates --from 2026-01-01 --currency AUD

A command rather than a screen, deliberately. The design handoff has no fetch
control on FX Rates, and inventing one would put a button next to hand entry
that overwrites nothing the user typed but looks exactly as though it might.
This is a backfill and a top-up: run it, read what it did.

Thin, like every other entry point (§5.2.2). It parses two dates, builds the
provider from settings, calls one service and prints the result.
"""

from __future__ import annotations

from datetime import date, datetime

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from core.services.exceptions import BusinessRuleError
from fx.services.ingest import LoadOutcome, load_daily_closes
from fx.services.providers import MassiveProvider, RateProviderError


def _parse_date(raw: str, *, flag: str) -> date:
    """ISO calendar dates only, no time and no offset (BR-24)."""
    try:
        return datetime.strptime(raw.strip(), "%Y-%m-%d").date()
    except ValueError:
        raise CommandError(
            f"{flag} must be a date as YYYY-MM-DD; got {raw!r}."
        ) from None


class Command(BaseCommand):
    help = "Load each trading day's closing exchange rate from the rate provider."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--from",
            dest="start",
            required=True,
            help="First date to load, YYYY-MM-DD. Inclusive.",
        )
        parser.add_argument(
            "--to",
            dest="end",
            default=None,
            help="Last date to load, YYYY-MM-DD. Inclusive. Defaults to today.",
        )
        parser.add_argument(
            "--currency",
            dest="currencies",
            action="append",
            default=None,
            help=(
                "Restrict to one pair, repeatable. Defaults to every quoted "
                "currency. USD is never fetched (BR-09)."
            ),
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Fetch and report without writing anything.",
        )

    def handle(self, *args, **options) -> None:
        start = _parse_date(options["start"], flag="--from")
        end = (
            _parse_date(options["end"], flag="--to")
            if options["end"]
            # `localdate`, not `date.today`: "today" is a question about the
            # configured timezone, which is the one job TIME_ZONE has (§9.4).
            else timezone.localdate()
        )

        currencies = options["currencies"]
        provider = MassiveProvider(
            settings.MASSIVE_API_KEY,
            base_url=settings.MASSIVE_BASE_URL,
            timeout=settings.MASSIVE_TIMEOUT_SECONDS,
        )

        try:
            outcome = load_daily_closes(
                provider,
                start,
                end,
                tuple(currencies) if currencies else None,
                dry_run=options["dry_run"],
            )
        except RateProviderError as exc:
            # An outage or a bad key is not a rejected request, and saying
            # "invalid" would send the reader looking in the wrong place.
            raise CommandError(str(exc)) from exc
        except BusinessRuleError as exc:
            raise CommandError(exc.message) from exc

        self._report(outcome)

    def _report(self, outcome: LoadOutcome) -> None:
        header = (
            f"{outcome.provider}, daily closes, "
            f"{outcome.start:%d %b %Y} to {outcome.end:%d %b %Y}"
        )
        self.stdout.write(header)
        self.stdout.write("-" * len(header))

        for pair in outcome.per_currency:
            if pair.fetched == 0:
                self.stdout.write(
                    self.style.WARNING(
                        f"{pair.pair}  no trading days returned for this range"
                    )
                )
                continue

            span = f"{pair.first_date:%d %b %Y} to {pair.last_date:%d %b %Y}"
            detail = f"{pair.written} of {pair.fetched} closes stored, {span}"
            if pair.replaced:
                detail += f"; {pair.replaced} replaced an earlier fetch"
            if pair.kept_manual:
                # Not a warning. This is the rule working (BRD §4.3), and the
                # count is the only place the user can see it happen.
                detail += f"; {pair.kept_manual} left as typed by hand"
            self.stdout.write(f"{pair.pair}  {detail}")

        if outcome.advisories:
            self.stdout.write("")
            self.stdout.write(
                self.style.WARNING(
                    f"{len(outcome.advisories)} rate-variance advisories — "
                    f"saved either way, but worth a look:"
                )
            )
            for advisory in outcome.advisories:
                self.stdout.write(f"  {advisory.message}")

        self.stdout.write("")
        if outcome.dry_run:
            self.stdout.write(
                self.style.WARNING(
                    f"Dry run. {outcome.written} rates would be written, "
                    f"{outcome.kept_manual} left as typed by hand. "
                    f"Nothing was saved."
                )
            )
            return
        self.stdout.write(
            self.style.SUCCESS(
                f"{outcome.written} rates stored, "
                f"{outcome.kept_manual} left as typed by hand."
            )
        )
