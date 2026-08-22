"""Seed a plausible history of past months into the development database.

    python manage.py seed_history                        # 24 months back, writing
    python manage.py seed_history --months 12 --dry-run
    python manage.py seed_history --seed 7

Development data only. Two months of balances make every trend chart a pair of
points and every month-on-month figure a comparison against nothing, so the
screens cannot be judged until there is a history behind them. This invents one.

**It writes only where nothing is recorded.** Balances are seeded for months an
account has none, and a month that already holds any transaction is left entirely
alone. So the real figures already entered are never overwritten, re-running is
safe, and a second run fills only what the first one could not.

**Balances are walked backwards from the figures that exist**, never generated
from nothing. Each account's earliest recorded balance is the anchor, and each
earlier month is that month's figure scaled by a per-type drift and jittered:
savings and pensions were smaller a year ago, a loan was larger, a current
account was much the same, gold is a count of ounces that steps rather than
drifts. Money that walks randomly away from a real anchor looks like a history;
money drawn from a uniform range looks like noise, and noise is no use for
judging a chart.

Two things this deliberately does not do:

  * **It does not invent exchange rates.** Where a month has no rate the account
    is excluded from the translated total and the omission is stated (FR-46) --
    correct behaviour, but a poor demonstration. Rates come from the provider
    over the same window, and this run reports the months it found uncovered so
    the gap is a stated fact rather than a surprise on the screen:

        python manage.py load_rates --from 2024-08-01

  * **It does not touch investments.** Lot state is replayed from transactions
    (ADR-06), so a seeded buy would restate realised gains computed from real
    ones -- and holdings are not what an empty trend chart is short of.

It refuses to run against anything but a development database. `manage.py` can be
pointed at production with one environment variable, and this command writes
fabricated financial figures -- one of the few things in the system that must
never reach `financial_hub` (BUILD_PLAN P-04).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from random import Random

from django.core.management.base import BaseCommand, CommandError
from django.db import connection

from core.months import month_end, month_of, previous, sequence, shift

#: Databases this command may write to. Names prefixed `test_` are added by
#: Django's test runner, which creates and drops them per run.
PERMITTED_DATABASES = frozenset({"financial_hub_dev", "financial_hub_ci"})

CENTS = Decimal("0.01")
UNITS = Decimal("1")


def day_in(month: str, day: int) -> date:
    year, mon = (int(part) for part in month.split("-"))
    return date(year, mon, day)


# ---------------------------------------------------------------------------
# Balances
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Walk:
    """How one account type behaves, read *backwards* in time.

    `factor` applies for each month further into the past, so a figure that grows
    through time has a factor below 1 and a liability that amortises has one
    above it. `noise` is the standard deviation of the multiplicative jitter, as
    a fraction. `floor` stops a random walk wandering through zero into a figure
    nobody would enter.
    """

    factor: Decimal
    noise: float
    floor: Decimal
    #: "drift" scales; "flat" holds still and revalues occasionally; "units"
    #: counts whole things and steps when one of them was bought.
    mode: str = "drift"


#: One entry per account type in the fixed vocabulary. A type absent from this
#: table is a type the command cannot invent a past for, and it says so rather
#: than falling back on a default that would look like data.
WALKS = {
    "Current/Checking": Walk(Decimal("1.000"), 0.14, Decimal("25")),
    "Savings/Deposit": Walk(Decimal("0.985"), 0.05, Decimal("100")),
    "Investment/Brokerage": Walk(Decimal("0.988"), 0.045, Decimal("250")),
    "Pension/Retirement": Walk(Decimal("0.981"), 0.012, Decimal("250")),
    "Property": Walk(Decimal("1.000"), 0.0, Decimal("1"), mode="flat"),
    "Physical Asset": Walk(Decimal("1.000"), 0.0, Decimal("1"), mode="units"),
    "Credit Card": Walk(Decimal("1.000"), 0.30, Decimal("0")),
    "Loan/Mortgage": Walk(Decimal("1.006"), 0.002, Decimal("0")),
    "Other Liability": Walk(Decimal("1.008"), 0.003, Decimal("0")),
}


def _jitter(rng: Random, noise: float) -> Decimal:
    """A multiplier around 1, clamped so one draw cannot halve a net worth."""
    if noise <= 0:
        return Decimal("1")
    draw = max(0.55, min(1.45, 1.0 + rng.gauss(0.0, noise)))
    return Decimal(str(round(draw, 6)))


def _step_back(rng: Random, amount: Decimal, walk: Walk) -> Decimal:
    """One month further into the past, for one account."""
    if walk.mode == "units":
        # A count of whole things -- ounces of gold, not a balance. Read
        # backwards it steps down each time one was bought, and holds otherwise.
        if amount > walk.floor and rng.random() < 0.06:
            return (amount - UNITS).quantize(UNITS)
        return amount.quantize(UNITS)

    if walk.mode == "flat":
        # A bond or a valuation: unchanged for long stretches, then restated.
        if rng.random() < 0.08:
            move = Decimal(str(round(rng.uniform(-0.02, 0.02), 6)))
            return max(walk.floor, (amount * (Decimal("1") + move)).quantize(UNITS))
        return amount.quantize(UNITS)

    stepped = amount * walk.factor * _jitter(rng, walk.noise)
    return max(walk.floor, stepped).quantize(CENTS, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Cash flow
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Entry:
    """One transaction to record, before it is one."""

    on_date: date
    amount: Decimal
    currency: str
    #: A key into SLOTS, not a category name. Which category it resolves to
    #: depends on the taxonomy in front of it.
    slot: str


#: What each generated line needs from the taxonomy: a direction, and the child
#: categories that will do, best first.
#:
#: A name alone is not enough. Child names are not unique across directions --
#: the migration files Gifts under Income/Other -- and `record_transaction` takes
#: the direction from the category rather than from its caller, so resolving by
#: name would record a Christmas present as income. The second name is the answer
#: for a taxonomy left as the migration seeded it; the first is this one.
SLOTS = {
    "salary": ("Income", ("Salary",)),
    "bonus": ("Income", ("Bonus",)),
    "interest": ("Income", ("Interest",)),
    "other_income": ("Income", ("Other Income", "Miscellaneous")),
    "rent": ("Expense", ("Rent",)),
    "energy": ("Expense", ("Energy",)),
    "internet": ("Expense", ("Internet",)),
    "mobile": ("Expense", ("Mobile",)),
    "software": ("Expense", ("Software",)),
    "groceries": ("Expense", ("Groceries",)),
    "eating_out": ("Expense", ("Eating Out",)),
    "transport": ("Expense", ("Transport",)),
    "holidays": ("Expense", ("Holidays",)),
    "events": ("Expense", ("Events",)),
    "hobbies": ("Expense", ("Hobbies",)),
    "medical": ("Expense", ("Medical",)),
    "fitness": ("Expense", ("Fitness",)),
    "insurance": ("Expense", ("Insurance",)),
    "clothing": ("Expense", ("Clothing",)),
    "household": ("Expense", ("Household",)),
    "electronics": ("Expense", ("Electronics",)),
    "gifts": ("Expense", ("Gifts", "Miscellaneous")),
    "other_expense": ("Expense", ("Other Expenses", "Miscellaneous")),
}


def _money(rng: Random, low: float, high: float) -> Decimal:
    return Decimal(str(round(rng.uniform(low, high), 2))).quantize(CENTS)


def _rent_for(months_back: int) -> Decimal:
    """Rent steps at a lease review; it does not drift by a few dollars a month."""
    if months_back <= 6:
        return Decimal("550.00")
    if months_back <= 18:
        return Decimal("530.00")
    return Decimal("505.00")


def _entries_for(rng: Random, month: str, months_back: int) -> list[Entry]:
    """One month of income and expense, in the shape the real months have.

    Mostly AUD, because that is where the salary lands, with a monthly MYR
    interest line and the occasional trip home paid for in ringgit. Amounts drift
    with `months_back` where a real one would -- pay rises, rent reviews -- and
    are otherwise drawn per month, so no two months read as copies.
    """
    entries: list[Entry] = []
    last = month_end(month).day
    mon = int(month.split("-")[1])

    def add(day: int, amount: Decimal, slot: str, currency: str = "AUD") -> None:
        entries.append(
            Entry(day_in(month, max(1, min(last, day))), amount, currency, slot)
        )

    # -- income -----------------------------------------------------------
    # A pay rise looks like one, read backwards: earlier months pay slightly less.
    salary = Decimal("3246.38") * (Decimal("0.9975") ** months_back)
    for payday in (3, 17):
        add(
            payday + rng.randint(-2, 2),
            (salary * _jitter(rng, 0.02)).quantize(CENTS, rounding=ROUND_HALF_UP),
            "salary",
        )
    if mon in (6, 12) and rng.random() < 0.7:
        add(rng.randint(10, 20), _money(rng, 2800, 8200), "bonus")

    add(1, _money(rng, 18, 95), "interest")
    add(1, _money(rng, 55, 305), "interest")
    add(rng.randint(2, 26), _money(rng, 1.0, 5.5), "interest", "MYR")
    if rng.random() < 0.15:
        add(rng.randint(4, 24), _money(rng, 90, 1650), "other_income")

    # -- expenses ---------------------------------------------------------
    rent = _rent_for(months_back)
    payment = rng.randint(1, 7)
    while payment <= last:
        add(payment, rent, "rent")
        payment += 7

    for _ in range(rng.randint(4, 6)):
        add(rng.randint(1, last), _money(rng, 58, 215), "groceries")
    for _ in range(rng.randint(4, 10)):
        add(rng.randint(1, last), _money(rng, 11, 96), "eating_out")
    for _ in range(rng.randint(3, 8)):
        add(rng.randint(1, last), _money(rng, 4.5, 62), "transport")

    add(rng.randint(12, 22), _money(rng, 58, 195), "energy")
    add(rng.randint(1, 6), Decimal("85.00") if months_back <= 9 else Decimal("79.00"), "internet")
    add(rng.randint(1, 8), _money(rng, 25, 45), "mobile")
    add(rng.randint(1, 28), _money(rng, 40, 92), "fitness")
    add(rng.randint(1, 28), _money(rng, 31, 142), "insurance")
    for _ in range(rng.randint(1, 3)):
        add(rng.randint(1, last), _money(rng, 7.5, 36), "software")

    occasional = (
        ("household", 0.45, 15, 265),
        ("hobbies", 0.45, 19, 185),
        ("clothing", 0.35, 38, 355),
        ("events", 0.30, 28, 225),
        ("medical", 0.25, 24, 320),
        ("other_expense", 0.20, 9, 155),
        ("holidays", 0.12, 295, 2650),
        ("electronics", 0.12, 78, 1250),
    )
    for slot, chance, low, high in occasional:
        if rng.random() < chance:
            add(rng.randint(1, last), _money(rng, low, high), slot)

    # December is not an average month, and a chart that pretends otherwise hides
    # the one seasonal effect this data has.
    if rng.random() < (0.75 if mon == 12 else 0.22):
        add(rng.randint(1, last), _money(rng, 22, 310), "gifts")

    # A trip home, paid for in ringgit.
    if rng.random() < 0.18:
        start = rng.randint(1, max(1, last - 8))
        for slot in rng.sample(
            ["groceries", "eating_out", "transport", "gifts", "household"],
            rng.randint(3, 5),
        ):
            add(start + rng.randint(0, 8), _money(rng, 18, 420), slot, "MYR")

    return entries


# ---------------------------------------------------------------------------
# The command
# ---------------------------------------------------------------------------


class Command(BaseCommand):
    help = (
        "Seed plausible balances and transactions for past months. "
        "Development databases only; writes nothing where a figure exists."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--months",
            type=int,
            default=24,
            help=(
                "How many months to seed, counting back from the last month that "
                "has ended. Default 24, which is the trend window."
            ),
        )
        parser.add_argument(
            "--seed",
            type=int,
            default=20260819,
            help="Random seed. The same seed against the same data gives the same figures.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be written without writing it.",
        )

    def handle(self, *args, **options) -> None:
        from accounts.models import Account, Balance
        from accounts.services.lifecycle import upsert_balance
        from cashflow.models import Category, Transaction
        from cashflow.services.entry import record_transaction

        self._refuse_unless_development()

        months = options["months"]
        if months < 1:
            raise CommandError("--months must be at least 1.")
        dry_run = options["dry_run"]
        rng = Random(options["seed"])

        # The last month that has ended. Nothing can be recorded against the one
        # still running (BR-24), and seeding it would put a figure on the
        # dashboard for a month whose real balances are not in yet.
        last_closed = previous(month_of(date.today()))
        window = sequence(shift(last_closed, -(months - 1)), last_closed)

        accounts = list(Account.objects.all())
        if not accounts:
            raise CommandError(
                "No accounts exist. Balances are walked backwards from the figures "
                "already entered, so create the accounts and close one month first."
            )

        unknown = sorted({account.account_type for account in accounts} - set(WALKS))
        if unknown:
            raise CommandError(
                f"No walk is defined for account type(s) {', '.join(unknown)}. Add "
                f"one to WALKS rather than letting this invent a default."
            )

        # -- plan the balances ---------------------------------------------
        planned: list[tuple[Account, str, Decimal]] = []
        reopened: list[tuple[Account, str]] = []
        anchorless: list[str] = []

        for account in sorted(accounts, key=lambda account: account.name):
            recorded = dict(
                Balance.objects.filter(account=account, month__lte=last_closed)
                .order_by("month")
                .values_list("month", "amount")
            )
            if not recorded:
                anchorless.append(account.name)
                continue

            anchor_month = min(recorded)
            amount = recorded[anchor_month]
            walk = WALKS[account.account_type]

            # Backwards from the anchor, one month at a time. Months at or after
            # it hold the user's own figures and are never revisited.
            for month in reversed([m for m in window if m < anchor_month]):
                amount = _step_back(rng, amount, walk)
                planned.append((account, month, amount))

            first = min(window[0], anchor_month)
            if first < account.opened_month:
                # No service owns this field -- the account serializer writes it
                # directly, there being no rule here beyond the constraint the
                # database already holds. A balance cannot precede the opening
                # month, so the seeded history would be refused without this.
                reopened.append((account, first))

        # -- plan the transactions -----------------------------------------
        # Month by month, and only where the month is empty: a month holding one
        # real transaction is a month someone has started, and adding forty
        # invented ones to it would make the real one unfindable.
        entries: list[Entry] = []
        occupied: list[str] = []
        for index, month in enumerate(window):
            if Transaction.objects.filter(
                date__range=(day_in(month, 1), month_end(month))
            ).exists():
                occupied.append(month)
                continue
            entries.extend(_entries_for(rng, month, len(window) - 1 - index))

        # Active child categories only: `record_transaction` refuses a parent and
        # refuses a deactivated one, and both refusals are right.
        available = {
            (direction, name): pk
            for name, direction, pk in Category.objects.filter(
                parent__isnull=False, is_active=True
            ).values_list("name", "direction", "id")
        }
        resolved: dict[str, int] = {}
        for slot, (direction, candidates) in SLOTS.items():
            for name in candidates:
                if (direction, name) in available:
                    resolved[slot] = available[(direction, name)]
                    break

        # Dropped rather than fatal: the taxonomy is the user's to reorganise, and
        # a seeder that dies because one category was renamed is a seeder nobody
        # runs. What it drops, it names.
        # A run that finds nothing to do is the ordinary second run, not a
        # failure: it reports two zeroes and writes nothing.
        unresolved = sorted({entry.slot for entry in entries} - set(resolved))
        if unresolved:
            entries = [entry for entry in entries if entry.slot in resolved]

        # -- report ---------------------------------------------------------
        self.stdout.write(
            f"{window[0]} to {window[-1]}, seed {options['seed']}"
            f"{' (dry run)' if dry_run else ''}"
        )
        self.stdout.write("-" * 60)
        self.stdout.write(
            f"balances      {len(planned):>5}  across "
            f"{len(accounts) - len(anchorless)} accounts"
        )
        self.stdout.write(f"transactions  {len(entries):>5}")
        if reopened:
            self.stdout.write(
                f"opened_month  {len(reopened):>5}  accounts moved back to {window[0]}"
            )
        if occupied:
            self.stdout.write(
                f"left alone    {len(occupied):>5}  months already holding "
                f"transactions ({', '.join(occupied)})"
            )
        if unresolved:
            self.stdout.write(
                self.style.WARNING(
                    f"dropped       {len(unresolved):>5}  kinds of line the taxonomy "
                    f"has no category for ({', '.join(unresolved)})"
                )
            )
        if anchorless:
            self.stdout.write(
                self.style.WARNING(
                    f"no anchor     {len(anchorless):>5}  accounts have no balance to "
                    f"walk back from ({', '.join(anchorless)})"
                )
            )

        uncovered = self._months_without_rates(accounts, window)
        if uncovered:
            self.stdout.write(
                self.style.WARNING(
                    f"\nNo month-end rate for {len(uncovered)} of these months "
                    f"({uncovered[0]} to {uncovered[-1]}). Accounts in those "
                    f"currencies stay excluded from the translated total until the "
                    f"rates are loaded:\n"
                    f"    python manage.py load_rates --from {day_in(window[0], 1)}"
                )
            )

        if dry_run:
            self.stdout.write("\nDry run. Nothing was saved.")
            return

        # -- write ----------------------------------------------------------
        for account, first in reopened:
            account.opened_month = first
            account.save(update_fields=["opened_month"])

        for account, month, amount in planned:
            upsert_balance(account, month, amount)

        for entry in entries:
            record_transaction(
                on_date=entry.on_date,
                amount=entry.amount,
                currency=entry.currency,
                category_id=resolved[entry.slot],
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"\nWrote {len(planned)} balances and {len(entries)} transactions."
            )
        )

    # -- guards -------------------------------------------------------------

    def _refuse_unless_development(self) -> None:
        """The tripwire under P-04, asked of the server actually connected to.

        `config.settings.dev` refuses to start against production, but this
        command runs under whatever settings module it was given. It writes
        fabricated financial figures, so it asks the database its own name first.
        """
        name = connection.settings_dict["NAME"]
        port = str(connection.settings_dict["PORT"])

        if name in PERMITTED_DATABASES or name.startswith("test_"):
            return

        raise CommandError(
            f"Refusing to seed: the connected database is '{name}' on port {port}, "
            f"which is not a development database "
            f"({', '.join(sorted(PERMITTED_DATABASES))}). This command writes "
            f"fabricated figures (BUILD_PLAN P-04)."
        )

    def _months_without_rates(self, accounts, window) -> list[str]:
        """Which seeded months have no month-end rate for a currency in use.

        Stated, never filled in: a missing rate excludes an account from the
        translated total and says so (FR-46), and a rate invented here would sit
        under a real month's figures looking exactly like one that was quoted.
        """
        from core.currencies import BASE_CURRENCY
        from fx.models import ExchangeRate

        needed = {account.currency for account in accounts} - {BASE_CURRENCY}
        if not needed:
            return []

        uncovered = []
        for month in window:
            as_at = month_end(month)
            for currency in needed:
                if not ExchangeRate.objects.filter(
                    currency=currency, rate_date__lte=as_at
                ).exists():
                    uncovered.append(month)
                    break
        return uncovered
