"""Module 1 — Net Worth. Arrives at Stage 2.

Nothing is built here yet, and that is the sequencing rather than an oversight:
net worth cannot be tested without currency translation, so `core` and `fx`
come first and the arithmetic that matters most is never stubbed (HLD §11.7).

What lands here at Stage 2:

**Account** — nine types, four liquidity tiers, three statuses, opened and
closed dates. Currency immutable once any balance exists, enforced by a database
constraint and not only in application code (BR-08, §9.1).

**Balance** — unique on account and month, at database level. Entry is
create-or-replace, so a second balance for the same month is impossible rather
than discouraged.

No balance is ever derived from a transaction, and no transaction ever alters a
balance (BR-01, BR-12, ADR-01). Nothing computed is stored: not net worth, not
slice totals, not month-on-month change (ADR-05).
"""
