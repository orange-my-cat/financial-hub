# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Status

**There is no application code yet.** The repository contains documentation only, and the
git repository has no commits. Stage 0 of the build plan has not started.

## Source of truth

Three documents govern this project, in this order of authority. Read the relevant one
before making a decision; do not infer a rule that one of them already states.

| Document | Authority |
|---|---|
| `documentation/BRD_Personal_Finance_Tracker_v1.0.md` | **What** the system does. Business rules BR-01…BR-24, functional requirements FR-01…FR-55, reports REP-01…REP-15 |
| `documentation/HLD_Personal_Finance_Tracker_v1_0.md` | **How** it is built. ADR-01…ADR-18, data design, API conventions, build order |
| `documentation/BUILD_PLAN_v1_0.md` | **Sequencing, and where the HLD's assumed environment differs from the real one.** Read §1–§2 first — the runtime is not what the HLD assumes |
| `documentation/design_handoff_financial_hub/` | UI. High fidelity: colours, typography, table anatomy and state treatments are final and exact. `README.md` there is the spec; `Financial Hub.dc.html` is the design board |

When these conflict, the later document wins on its own subject: the BUILD_PLAN's §1–§2
supersede the HLD's environment assumptions, and the HLD's departures D1–D6 supersede the
BRD where they say so.

## Architecture — the load-bearing invariants

These are not style preferences. Each one is the consequence of a decision argued at
length in the HLD, and violating any of them is a defect regardless of whether a test
catches it.

- **No computed figure is ever persisted.** Not net worth, not slice totals, not
  month-on-month change, not lot remaining quantities, not cost basis, not realised gain.
  Everything is derived on read from stored facts. This is affordable because the ten-year
  dataset is ~20,000 rows, and it is what makes unrestricted historic editing (BR-23) safe
  — there is no cache to invalidate and no total to drift. (ADR-05)
- **Balances are entered, never derived.** No transaction of any kind alters an account
  balance. The four modules are decoupled by design; an incomplete cash flow ledger cannot
  corrupt net worth. (BR-01, BR-12, ADR-01)
- **One definition per calculation.** One place where net worth is defined, one where
  currency translation happens, one where FIFO is computed. A screen that computes its own
  summary lets the screen and the report disagree, with no way to tell which is right.
- **FIFO is computed by full replay.** Lot state is never stored. The replay engine is a
  pure function — transactions in date order in, lot states and realised gains out, no
  database writes. A buy *is* a lot; a split is a transaction in the sequence, not an edit
  to lots. (ADR-06)
- **Money is exact decimal, and never a float.** `NUMERIC(19,4)` for money, `(19,10)` for
  quantities and rates, `(19,8)` for unit prices. Full precision throughout, rounded once
  at display, half-up. Money crosses the API **as a string paired with a currency code**,
  never a JSON number — `JSON.parse` turns a number into a float. The TypeScript `Money`
  type has **no arithmetic defined on it**, so summing in the browser is a compile error.
  (ADR-02, ADR-12)
- **All cross-currency work goes through the one translation service.** Rate lookup
  returns four facts together: the rate, its as-at date, its provenance (`exact` /
  `carried` / `triangulated`), and whether it breaches the staleness threshold. Only
  USD-based pairs are stored; AUD↔MYR is triangulated on demand and never stored.
  (ADR-08, ADR-09)
- **A missing rate excludes, it never zeroes.** Where no rate exists on or before the
  required date, the account is excluded from the translated total and the omission is
  stated explicitly. (FR-46)
- **Aggregate responses always carry their completeness state, exclusions and rate
  provenance**, so a consumer cannot render a total without the information that qualifies
  it. (§8.2)
- **Three-layer rule, absolute.** Models hold structure and database constraints; services
  hold every business rule and calculation and are callable without HTTP; views
  authenticate, deserialise, call one service, serialise, return. (§5.2.2)
- **Deletes are soft, everywhere.** Deleted rows vanish from every screen, report, export
  and calculation, and remain recoverable through the Django admin. (ADR-03)
- **Advisories never block; errors block and say nothing was saved.** Exactly three
  advisories exist: probable-duplicate transaction, rate variance, historic restatement on
  reclassification. Retroactively invalid investment state is flagged, never blocked.
  (ADR-07, §8.3)
- **Rules that protect data integrity live in the database**, not only in application code
  — one balance per account per month, one rate per pair per date, account currency
  immutable once balances exist, referenced categories not deletable. (§9.1)

## Environment

The HLD assumes Ubuntu under WSL2 with a dedicated database container. **Neither is true.**
The real setup is Docker Desktop on Windows plus a shared local platform, `vibe-city`:

| Container | Role |
|---|---|
| `central-station` (nginx) | Reverse proxy on port 80, serves `*.localhost` vhosts. Managed by `d:\Repositories\vibe-city\compose.yaml`, config bind-mounted read-only from `nginx/conf.d/` |
| `control-tower` (Portainer) | **Publishes host port 8000 — that port is unavailable to this project** |
| `data-center` (PostgreSQL 18.4) | Production. Database `financial_hub`. Host port 5432 |
| `data-center-test` (PostgreSQL 18.4) | Development and test. Databases `financial_hub_dev` and `test_financial_hub_dev`. Host port 5433 |

Development and production are deliberately different topologies (BUILD_PLAN §2.3):

- **Development** is a local hot-reloading process on Windows — `runserver` on **port
  8001** plus the Vite dev server proxying `/api` to it, against `localhost:5433`. Only
  the database is containerised.
- **Production** is the `financial-hub` container joining `vibe-city` and **publishing no
  port**, reached only through nginx at `http://financial-hub.localhost`, against
  `data-center:5432` over the Docker network.

**Hazard:** `data-center` publishes `0.0.0.0:5432` and development wants `localhost:5433`.
One mistyped digit points a `DEBUG`-on development server at live financial data. See
BUILD_PLAN P-04.

## Commands

Platform proxy, at `d:\Repositories\vibe-city`:

```sh
docker compose up -d                                   # start or recreate nginx
docker compose exec central-station nginx -t           # validate config before reloading
docker compose exec central-station nginx -s reload    # apply a vhost change, no downtime
```

Application commands do not exist yet; they land in Stage 0. Their fixed parameters are
already decided and should not be re-chosen: Django development on **8001**, database
`financial_hub_dev` at **localhost:5433**, tests against the same instance with Django
creating and dropping `test_financial_hub_dev` per run, production reached at
`financial-hub.localhost`.

The production container entrypoint runs in this exact order, and the order is the point:
**dump → prune to 30 → migrate → start Gunicorn.** Every schema change is preceded by a
restorable snapshot taken seconds earlier. Because the database is shared with other
tenants, this dump is the only backstop against another project's teardown.

## Build order

Per HLD §11.7 and BUILD_PLAN §4. Do not build ahead of this sequence — each stage exists
because the next one cannot be tested without it.

**0** Foundations → **1** `core` + `fx` (money, rate lookup, translation, completeness —
first, because net worth cannot be tested without translation) → **2** `accounts` →
**checkpoint: close one real month using net worth alone** → **3** `cashflow` → **4**
`investments` (replay engine built in isolation first) → **5** dashboard, CSV export,
polish.

Django apps mirror the modules: `core`, `accounts`, `cashflow`, `investments`, `fx`.

## Fixed vocabulary

Use these exact terms in code, UI and tests:

- **Account types** (nine, no grouping above them): Current/Checking, Savings/Deposit,
  Investment/Brokerage, Pension/Retirement, Property, Physical Asset (assets); Credit Card,
  Loan/Mortgage, Other Liability (liabilities)
- **Liquidity tiers** (four): Instant, Short, Long, Locked
- **Account status** (three): Open, Dormant, Closed
- **Month completeness** (four, not two): Complete, Incomplete, Missing, Outside Range
- **Rate provenance** (three): exact, carried, triangulated

## Do not build

Inventing any of these makes the implementation **wrong**, not generous. The list is from
the design handoff and is deliberate:

market prices · unrealised gain · portfolio return percentage · **transfers between
accounts** · budgets · forecasting · tax computation · bank or broker connections · file or
statement import · CSV *import* · multi-user, avatars, sharing, permissions · notifications
or email · drill-down navigation · configurable dashboard widgets · audit trail or change
history · in-app backup and restore controls beyond a status readout · onboarding wizards ·
marketing or landing pages · reconciliation against external statements · mobile-optimised
data entry

Two prohibitions are stated in UI copy on the screens themselves: **unrealised gain does
not exist in this system**, and **estimated tax is a user-typed percentage, not a
calculation** — every net-of-tax figure is labelled indicative. There is **no transfer
affordance anywhere in the application**; moving money between one's own accounts is not a
transaction and appears only as two balance changes at the next close.
