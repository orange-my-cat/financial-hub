"""Module 3 — Investments. Arrives at Stage 4.

The replay engine is built first, in isolation, before any model or screen
touches it.

**Holding** — name, instrument type, currency, estimated tax percentage. Scoped
to one account: the same instrument at two brokers is two holdings with
independent FIFO queues, and that is a **one-way door** (§13.4).

**InvestmentTransaction** — buy, sell, split, distribution, reinvestment.
Purchase fees into cost basis; sale fees off proceeds.

What is deliberately absent from this module is the important part. **No lot
table.** No stored cost basis, no stored remaining quantity, no stored realised
gain (ADR-06). A buy *is* a lot, and its remaining quantity is output from
replaying the holding's transactions in date order through a pure function. A
split is a transaction in that sequence rather than an edit to lots — which is
why a 2:1 split dated March doubles a February lot and leaves an April lot
untouched, with no migration and nothing to correct.

And there is no market price anywhere, therefore no unrealised gain and no
portfolio return percentage. Inventing them makes the implementation wrong.
"""
