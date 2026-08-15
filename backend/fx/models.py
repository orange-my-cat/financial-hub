"""Module 4 — FX Rates. Arrives at Stage 1, alongside `core`.

Built first, with `core`, because net worth cannot be tested without
translation (HLD §11.7).

**ExchangeRate** — USD-based pairs only. Unique on pair and date at database
level; indexed on pair and date descending, because the dominant query in this
system is "the most recent rate at or before this date". `source` and `provider`
provenance are captured from day one and that is a **one-way door** (ADR-08,
§13.4): a rate stored without knowing where it came from cannot be told apart
later from one that was typed.

AUD↔MYR is triangulated through USD on demand and **never stored**. Storing a
derived rate would create a second thing that has to agree with the first.
"""
