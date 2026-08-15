"""Module 2 — Cash Flow. Arrives at Stage 3.

**Category** — a two-level taxonomy seeded per BR-22, Title Case. Transactions
attach to child categories only. A category that has been used is deactivated,
never deleted, and the refusal is a database constraint (§9.1).

**Transaction** — date, amount, currency, direction, exactly one child category,
optional note. Plus a nullable account reference and a nullable import-batch
reference: both captured from day one, both read by nothing in v1, and both
**one-way doors** (ADR-13). They cannot be added retrospectively to historic
rows, which is the whole argument for carrying two unused columns for a decade.

**RecurringTemplate** — proposed each period, never posted automatically
(BR-14). A confirmed transaction is thereafter independent of its template.

No transaction touches an account balance, ever. The two modules are decoupled
by design so that an incomplete ledger cannot corrupt net worth (BR-12), and no
report sums cash flow figures together with balance figures.
"""
