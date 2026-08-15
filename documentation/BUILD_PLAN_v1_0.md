# Build Plan — Financial Hub v1.0

| Field | Value |
|---|---|
| Implements | BRD v1.0 (13 Aug 2026) and HLD v1.0 (13 Aug 2026) |
| Date | 15 August 2026 |
| Status | Draft for review |
| Repository | `d:\Repositories\financial-hub` — empty, no commits, `documentation/` untracked |
| Target URL | `http://financial-hub.localhost` |

This document sequences the work. It does not restate the BRD (what) or the HLD (how);
it records the deltas between the HLD's assumed environment and the real one, the
decisions that must be closed before code is written, and the stage-by-stage build order
with exit criteria.

---

## 1. Environment findings — where reality differs from the HLD

Verified on the target machine on 15 Aug 2026.

### 1.1 The existing platform

The HLD was written as though this application would arrive on a bare machine. It will
not. A shared local platform already exists, and Financial Hub is the next tenant of it
rather than a standalone stack.

| Container | Image | Network | Published | Role |
|---|---|---|---|---|
| `central-station` | `nginx:stable` | `vibe-city` | `0.0.0.0:80` | Reverse proxy. Serves `*.localhost` vhosts from `/etc/nginx/conf.d/`. Already proxies `control-tower.localhost` → `http://control-tower:9000` by Docker DNS |
| `control-tower` | `portainer/portainer-ce` | `vibe-city` | `8000`, `9000`, `9443` | Container management UI |
| `data-center` | `postgres:18.4` | `bridge` (default) | `0.0.0.0:5432` | Shared PostgreSQL, volume `data-center-data` |
| `data-center-test` | `postgres:18.4` | `bridge` (default) | `0.0.0.0:5433` | Shared test PostgreSQL, volume `data-center-test-data` |

The established pattern for adding an application is therefore: join `vibe-city`, publish
no port, and drop a vhost file into `central-station` proxying to the container by name.
`financial-hub.localhost` follows `control-tower.localhost` exactly.

### 1.2 Findings

| # | HLD position | Reality | Consequence |
|---|---|---|---|
| E1 | ADR-18 / CON-08: Ubuntu 24.04 LTS under WSL2 with Docker Engine installed in the distro | **Docker Desktop 29.7.2 on Windows** (context `desktop-linux`, Compose v5.3.1). The only WSL distro present is `docker-desktop`. No Ubuntu distro exists | The application design is unaffected — it is still `docker compose up`. Three WSL constraints change shape; see E2–E4 |
| E2 | CON-09: the project and its database volume must live inside the WSL filesystem, never on `/mnt/c` (TR-06, High) | The repository is on `d:\Repositories\financial-hub`, a Windows path | **Largely dissolved, with one hard rule retained.** Under Docker Desktop a *named volume* lives inside the Docker Desktop VM's virtual disk, not on `D:`. Source on `D:` is only a build context. The rule that survives: **never bind-mount the PostgreSQL data directory to a Windows path.** The HLD already chose a named volume (§5.4), so this holds by construction |
| E3 | CON-10: backups must be written outside the WSL virtual disk, to a Windows folder | Trivially satisfiable — a bind mount from the app container to a Windows folder | Unchanged and now easier. Destination still needs nominating (OI-12) |
| E4 | CON-11: `wsl --shutdown` kills containers with no graceful stop | Still true under Docker Desktop, and Docker Desktop can also be quit outright | Unchanged. Start-triggered backup (ADR-11) remains the primary mechanism, for the same reason |
| E5 | ADR-10 / ADR-16: one port, bound to `127.0.0.1:8000`, no proxy | Serving is via the **existing `central-station` nginx** on `financial-hub.localhost`. Separately, **port 8000 is already taken** by `control-tower` | Departure **D6**, §2.1. The app publishes no port at all, which is a stronger posture than the HLD's, not a weaker one |
| E6 | ADR-17: tests run against a containerised test database | **No Node and no Python on the host PATH** | Development runs as a local hot-reloading process (§2.3), so this is now a **Stage 0 prerequisite to install**, not an observation. Nothing can be built until Python and Node are on the host |
| E11 | — | **Host port 8000 is published by `control-tower`** (Portainer) | Django's `runserver` cannot use its default port. Development binds **8001**; see §2.3 |
| E12 | ADR-02 / TR-07: a test run must not be able to address production data | `data-center` publishes `0.0.0.0:5432`, so **the production database is reachable from the host** — the same place the development process runs. A mistyped port in a local `.env` reaches production | The hazard is created by local development, not by the shared instance as such. **Open — see §2.3** |
| E7 | — | Git repository has **zero commits**; `documentation/` is untracked | Stage 0 includes the initial commit, `.gitignore` and `.env.example` before anything else |
| E8 | §5.4: a dedicated `db` container with volume `pft-pgdata`, no published port | A shared **`data-center` PostgreSQL 18.4** already exists | A real architectural decision, not a detail. **Open — see §2.2** |
| E9 | ADR-02 / TR-07: an isolated `tmpfs` test database under a compose profile with a deliberately dissimilar connection string | **`data-center-test` on port 5433** already provides the isolation and the dissimilar DSN, though on a volume rather than `tmpfs` | Satisfies TR-07's intent. Slower than `tmpfs` and leaves state between runs; Django creates and drops its own test database per run, so this is acceptable |
| E10 | AS-01 / OI-11 / TR-01: Django 5.2's formal support for PostgreSQL 18 is unverified, with PostgreSQL 17 as the fallback | The platform is **already running PostgreSQL 18.4** | Practically settled, and the PostgreSQL 17 fallback is now expensive because it would mean abandoning the shared instance. Still worth one glance at the Django support matrix; I have not verified it and do not want to assert it |

**Naming.** The BRD and HLD call the product *Personal Finance Tracker* with a `pft-`
prefix. The design handoff and repository call it *Financial Hub*, and the platform uses
thematic names (`central-station`, `control-tower`, `data-center`, `vibe-city`) into which
`financial-hub` fits without alteration. This plan standardises on **Financial Hub** for
user-facing text and **`financial-hub`** as the container name, so the nginx vhost reads
`proxy_pass http://financial-hub:8000` exactly as `control-tower.conf` does. Worth a
one-line note in the HLD so the two documents do not drift.

---

## 2. Departure D6 — integrating with the vibe-city platform

ADR-10 rejected a reverse proxy container as "a third container and a config file
maintained for a decade in exchange for TLS termination, load balancing and multi-origin
routing". That argument was about *creating* a proxy. One already exists and is already
maintained, so its cost is zero here and the decision reverses cleanly.

### 2.1 Routing — settled

Follow the `control-tower.localhost` pattern exactly:

- The `financial-hub` container joins the **`vibe-city`** network and **publishes no port**. This is a stronger posture than ADR-10's `127.0.0.1:8000`, not a weaker one: the app is unreachable except through nginx.
- A `financial-hub.conf` in `central-station`'s `/etc/nginx/conf.d/` proxying `financial-hub.localhost` → `http://financial-hub:8000`, carrying `Host`, `X-Real-IP`, `X-Forwarded-For` and `X-Forwarded-Proto` as the existing vhost does.
- Django settings: `ALLOWED_HOSTS=financial-hub.localhost` and `CSRF_TRUSTED_ORIGINS=http://financial-hub.localhost`. If nginx ever terminates TLS in front of it, add `SECURE_PROXY_SSL_HEADER` then and not before.
- WhiteNoise continues to serve the built React bundle from inside the app container. Moving static file serving into nginx is possible but would split the deployable in two for no gain at this scale.

**Platform defect — fixed 15 Aug 2026.** `central-station` had **no bind mount**: its
`conf.d` existed only inside the running container's writable layer, so `control-tower.conf`
had no copy anywhere and would have been lost the moment the container was recreated or
the image updated. It was also created with `docker run` — no compose file, no labels,
restart policy `no`.

Resolved by giving the platform a home at **`d:\Repositories\vibe-city`**:

- `nginx/conf.d/` now holds `control-tower.conf` and `default.conf`, copied out of the container before anything was touched
- `compose.yaml` recreates `central-station` with `./nginx/conf.d` mounted **read-only**, on the external `vibe-city` network, restart policy raised from `no` to `unless-stopped` so the proxy returns with Docker
- `README.md` documents the add-an-application procedure, which `financial-hub.conf` will follow at Stage 0

Verified after recreation: `nginx -t` passes, `control-tower.localhost` returns 200,
`localhost` returns 200. The folder is not yet a git repository — `git init` and a first
commit there is yours to make.

The two PostgreSQL containers and Portainer are still ad-hoc `docker run` containers.
Adopting them into the same compose file is a sensible follow-up, but `data-center` holds
live data and recreating it deserves its own deliberate session rather than being folded
into a proxy change.

### 2.2 Database — settled: shared instances

**Decision: `data-center` (5432) for production, `data-center-test` (5433) for development
and test.** No dedicated `db` container is built. This departs from HLD §5.4 and is
recorded as part of D6.

| Environment | Instance | Database |
|---|---|---|
| Production | `data-center` | `financial_hub` |
| Development | `data-center-test` | `financial_hub_dev` |
| Test | `data-center-test` | `test_financial_hub_dev`, created and dropped per run by Django |

Three consequences follow and each needs handling at Stage 0.

**Reachability — one command, production only.** `data-center` sits on the **default
`bridge`** network, where Docker's embedded DNS does not resolve container names; that
only works on user-defined networks. The production app container joins `vibe-city`, so
without action it cannot reach the database by name. Fix is one non-destructive command —
no recreation, no downtime, and `data-center` keeps its existing `bridge` attachment and
published port, because a container may hold several network memberships:

```sh
docker network connect vibe-city data-center
```

After this the production container reaches `data-center:5432` by name. Reaching it via
`host.docker.internal:5432` would also work and is the fallback, at the cost of routing
database traffic out through the host.

**`data-center-test` needs no such change.** Development and tests run as local host
processes (§2.3) and reach it through its published `localhost:5433`. It stays on
`bridge`, unmodified.

**TR-07 by construction rather than convention.** Production is reached at
`data-center:5432`, a hostname that resolves **only inside the Docker network**;
development and test are reached at `localhost:5433`. A production DSN copied into a local
settings file therefore does not resolve at all. Django's test runner creating and dropping
its own `test_`-prefixed database keeps development data intact across runs. The residual
hazard is not the hostname but the port — see §2.3.

**Blast radius is now an accepted risk, not a mitigated one.** Quality attribute 1 ranks
durability of hand-entered data first, and a shared instance puts it behind another
project's teardown. Nothing in the application can prevent that. What stands between a
stray `docker compose down -v` and the loss of a decade of typing is ADR-11's dump on
every container start, which makes that mechanism materially more important here than the
HLD assumed. Two things follow:

- The Stage 0 entrypoint dump is **not optional and not deferrable** — it is the only backstop.
- The dashboard's backup-age warning (Stage 5) moves from useful to load-bearing.

Recorded as **P-02** in §6.

### 2.3 Development topology — local process, production in Docker

**Decision: development runs as a hot-reloading local process on Windows. Only the
development database is containerised. Production is app and database in Docker.**

| | Development | Production |
|---|---|---|
| Django | `manage.py runserver` on the host, **port 8001** (E11) | Gunicorn in the `financial-hub` container |
| React | Vite dev server with HMR, proxying `/api` to `localhost:8001` | Built bundle baked into the image, served by WhiteNoise |
| Database | `data-center-test` at `localhost:5433`, database `financial_hub_dev` | `data-center:5432`, database `financial_hub`, over `vibe-city` |
| Reached at | `localhost:<vite port>` | `financial-hub.localhost` through `central-station` |
| `DEBUG` | On | Off |
| Backup dump | None | Entrypoint, on every container start |

**This does not contradict ADR-10.** That ADR rejected running Vite's dev server *as the
deployment* — "not a thing to depend on for years". Using it as a development tool while
production ships a single image is the arrangement it assumed. ADR-10's real guarantee —
that the front end can never drift out of sync with the back end because they ship in one
image — holds for production, which is where it matters.

**Three concrete consequences.**

1. **Port 8000 is unavailable.** `control-tower` publishes it. Django development binds
   **8001**, and that number belongs in `.env.example` and the README rather than in
   anyone's memory.

2. **Same-origin in development via the Vite proxy.** Vite proxies `/api` to
   `localhost:8001` so the browser sees one origin. This keeps the session cookie working
   with no CORS layer, no `django-cors-headers` dependency, and no divergence between how
   authentication behaves in development and in production — which is exactly the kind of
   difference that produces a bug visible only after deployment.

3. **The port hazard is the one real cost of this topology (E12).** `data-center` publishes
   `0.0.0.0:5432`, so production is reachable from the host — the same place the
   development process runs. Development wants `localhost:5433`; a single mistyped digit
   in a local `.env` points a hot-reloading development server, with `DEBUG` on and
   migrations pending, at the production database. Nothing would warn.

   **Recommended: stop publishing 5432 to the host.** The production app reaches
   `data-center` over `vibe-city` and does not need the host publish; removing it makes the
   production database *physically unreachable* from any host process, which converts
   TR-07 from a discipline into an impossibility. Two caveats: it requires recreating
   `data-center` (port changes cannot be applied to a running container), and any other
   tenant or GUI tool connecting from the host would break. Data is safe across the
   recreation because it lives in the `data-center-data` volume, but this touches live data
   and is a platform change, so it is yours to call.

   **If the publish must stay**, narrow it to `127.0.0.1:5432` so at least the LAN cannot
   reach it, and add the production database name to the smoke test's assertions so a
   misdirected development process is caught by the first thing that runs.

---

## 3. Decisions to close before or during Stage 1

None of these blocks Stage 0. Each has a documented recommendation, stated here as the
assumption the build will proceed under unless overridden.

| ID | Question | Proceeding assumption | Latest point to decide |
|---|---|---|---|
| **D6-db** | Shared `data-center` or a dedicated `db` container? (§2.2) | **Closed** — shared. `data-center` for production, `data-center-test` for development and test | Closed 15 Aug 2026 |
| **D6-nginx** | Mount `central-station`'s `conf.d` from a version-controlled host folder before adding a second vhost? (§2.1) | **Closed and done** — platform now at `d:\Repositories\vibe-city`, verified | Closed 15 Aug 2026 |
| OI-11 | Does Django 5.2 LTS formally support PostgreSQL 18? (AS-01, TR-01) | Practically settled — the platform already runs PostgreSQL 18.4 (E10). **I have not verified the formal support statement and am not asserting it**; worth one glance at the Django docs. The PostgreSQL 17 fallback is now costly rather than free | Stage 0, before the first migration |
| OI-01 | Which currencies are actually held? (A9, AS-05) | USD, AUD, MYR. Each additional currency adds one stored USD pair and one more rate to type each month | Stage 1, before the rate table is seeded |
| OI-13 | Rate staleness threshold and rate-variance warning threshold | 7 days and 10%, both stored in the settings table so they are changeable without a deploy | Stage 1 |
| OI-06 | Remove `Dividends` and `Realised Investment Gains` from the seeded taxonomy? | **Recommend removing both**, retaining `Interest` alone under `Income → Gains`. Retaining categories that must never be used invites exactly the double-count BR-15 exists to prevent. One line of seed data | Stage 3 |
| OI-04 | Interest on a cash balance inside a brokerage account | Treat as cash flow interest — it is a cash return with no holding to attach to. No design impact either way | Stage 3 |
| OI-05 | Estimated tax on realised losses | Applied to gains only; losses shown gross | Stage 4 |
| OI-09 | Recurring proposals for a skipped period | Remain outstanding until confirmed or explicitly dismissed | Stage 3 |
| OI-14 | Is ADR-04's all-or-nothing month back-fill workable against the lossy spreadsheet? | Build the strict rule; relaxing it is a one-line change in one service | Stage 2, reassess after the checkpoint |
| OI-12 | Is the Windows backup destination replicated off-machine? (AS-02, TR-02, **Severe**) | **Must be answered.** A folder under OneDrive or equivalent. If the destination is not replicated, RISK-02 is only half closed and the residual exposure is total loss on a disk failure | Stage 0, when the bind mount is created |
| OI-08 | Timezone | `Asia/Kuala_Lumpur` — resolved in the HLD | Closed |

---

## 4. Build stages

Stage order follows HLD §11.7, with a Stage 0 prepended for infrastructure that the HLD
assumes rather than schedules. Each stage has explicit exit criteria; a stage is not done
until they pass.

### Stage 0 — Foundations

Nothing financial. The objective is a running, backed-up, authenticated shell at
`http://financial-hub.localhost` with the test harness proving itself against an empty
database.

**Repository and configuration**
- Initial commit; `.gitignore` covering `.env`, `__pycache__`, `node_modules`, build output, `*.dump`
- `.env.example` documenting every key (database credentials, `DJANGO_SECRET_KEY`, `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`, backup path, debug flag); `.env` git-ignored (ADR-16, §9.3)
- Layout: `backend/`, `frontend/`, `docker/`, `compose.yaml`, `compose.test.yaml`, `README.md` as the operational runbook

**Host prerequisites** (E6 — nothing can be built until these exist)
- Python on the host — Django 5.2 supports 3.10 upward; confirm the exact matrix against the release notes when pinning
- Node on the host, at a version Vite supports
- Databases created on the shared instances: `financial_hub` on `data-center`, `financial_hub_dev` on `data-center-test`, with a least-privilege role for each

**Development loop** (§2.3)
- `manage.py runserver` on **8001**, `DEBUG` on, database `localhost:5433/financial_hub_dev`
- Vite dev server with HMR, proxying `/api` → `localhost:8001` so the browser sees one origin and the session cookie behaves as it will in production
- Tests target `localhost:5433`; Django creates and drops `test_financial_hub_dev` per run, leaving development data intact
- `.env.example` documents both profiles and states the 8001 and 5433 numbers explicitly

**Production containers** (§5.4, ADR-10, as revised by §2)
- `financial-hub` — multi-stage image: Node stage builds the Vite bundle, Python stage runs Gunicorn + Django + WhiteNoise serving that bundle. **Joins `vibe-city`, publishes no port.** Reached only through `central-station`. `DEBUG` off, so a stack trace is never rendered in the browser
- `financial-hub.conf` added to `d:\Repositories\vibe-city\nginx\conf.d\`, then `nginx -t` and `nginx -s reload`
- **No `db` service** (§2.2). One command instead: `docker network connect vibe-city data-center`
- Backup bind mount to the nominated Windows folder (OI-12)
- Entrypoint, in this exact order (§11.4): **dump → prune to 30 → migrate → start Gunicorn.** The ordering is the point — every schema change is preceded by a restorable snapshot taken seconds earlier. `pg_dump` targets the `financial_hub` database alone, not the cluster. Under the shared-instance decision this dump is the only backstop against another tenant's teardown, so it ships in Stage 0 and is verified before Stage 1 begins

**Backend skeleton** (§5.2.2)
- Django project with five apps — `core`, `accounts`, `cashflow`, `investments`, `fx`
- Three-layer rule enforced from the first file: models hold structure, services hold every calculation, views are thin
- DRF with `IsAuthenticated` as the **default** permission class, so a new endpoint is protected unless deliberately opened (§10.2)
- Soft-delete abstract base (deletion flag, created/updated timestamps) with a default manager that filters deleted rows once, centrally (ADR-03)
- Single consistent error shape — field errors vs non-field errors, stable machine-readable codes (§8.3)
- Django admin enabled at a non-obvious path, as the break-glass route to soft-deleted rows only
- Session auth: HttpOnly, SameSite, 30-day lifetime, no idle timeout (ADR-16)
- Logging to stdout, json-file driver capped at 10 MB × 3 (§9.2)

**Frontend skeleton** (ADR-15, design handoff)
- Vite + TypeScript + React Router + TanStack Query + TanStack Table + Recharts
- Nocturne tokens lifted from `documentation/design_handoff_financial_hub/nocturne-styles.css`; the six semantic colours, three type faces and state treatments defined in the app's own `:root`
- App shell: 56px icon rail expanding to 208px on hover with task-count badges; header carrying reporting currency and date range, both mirrored to the URL; **the ledger spine** — 100px month rail down the right edge of every screen
- `Money` TypeScript type as a string with **no arithmetic defined on it**, so adding two amounts in the browser is a compile error (ADR-02)
- One formatting module wrapping `Intl` — two decimals, tabular numerals, currency code inseparable from the figure, minus sign never parentheses, dates as `13 Aug 2026`
- Login screen; every other route a placeholder

**Test harness** (ADR-17)
- pytest + pytest-django + coverage, gate at 80% lines, running against the tmpfs container
- Financial-invariant suite separated so it runs alone in seconds
- Smoke-test command scaffolded: app responds, database reachable, migrations current, last dump recent. The fifth assertion — a known net worth figure is unchanged — is added at Stage 2

**Exit criteria.** Both topologies work and are demonstrably distinct.

*Development:* `runserver` on 8001 plus the Vite dev server yields a login page with HMR
working on both a React edit and a Django edit, against `financial_hub_dev`.

*Production:* `docker compose up` yields a login page at `http://financial-hub.localhost`
served through `central-station`; the app container publishes no port and is unreachable
except through nginx; a timestamped dump appears in the Windows folder on every start and
prunes at 30; the smoke test passes.

*Both:* the test suite runs against `data-center-test` and cannot reach production;
`.env.example` and the nginx vhost are version-controlled, so a second machine starts from
the repository alone.

---

### Stage 1 — `core` and `fx`

Built first because net worth cannot be tested without translation, and stubbing the
arithmetic that matters most is the one thing worth avoiding (§11.7).

- **Money primitives** — amount inseparable from currency code; arithmetic between differing currencies refused at the type level. `NUMERIC(19,4)` for money, `(19,10)` for quantities and rates, `(19,8)` for unit prices. Full precision carried throughout, **rounded once at display**, half-up (ADR-02)
- **ExchangeRate** — USD-based pairs only; unique on pair + date; indexed pair + date descending, because the dominant query is "most recent rate at or before this date"; `source` and `provider` provenance captured from day one (**one-way door**, ADR-08 / §13.4)
- **Rate lookup service** — resolves a pair and date to four facts together: the rate, its as-at date, its provenance (`exact` / `carried` / `triangulated`), and whether it breaches the staleness threshold. Triangulated AUD↔MYR computed on demand and **never stored**
- **Translation service** — the single path by which any amount changes currency. The caller supplies the date. Returns the translated amount with full provenance. Where no rate exists on or before the date, returns *untranslatable*: the account is excluded, the omission stated, and the balance **never treated as zero** (FR-46)
- **Completeness service** — four states: Complete, Incomplete, Missing, Outside Range. No month table; months are derived from the balances that exist. An account is required only from the *later* of its opening date and the first month a balance was actually recorded for it (ADR-04)
- **Settings** — reporting currency, timezone (`Asia/Kuala_Lumpur`), staleness threshold (7 days), rate-variance threshold (10%)
- **API** — rates CRUD, bulk entry for a single date committing as a unit, rate trend for a pair with triangulated points labelled derived, missing-and-stale summary
- **Screens** — FX rates (bulk entry, daily table with provenance per rate, missing/stale summary, trend chart) and Settings

**Tests, by name.** Every BR-09 edge case: exact hit; carry-forward across a gap; no rate
at any earlier date; rate for base against itself is 1 and never entered; editing a
historic rate restates the reports that used it. Plus triangulation correctness, the
staleness boundary at exactly the threshold, and the rate-variance warning firing without
blocking the save.

**Exit criteria.** Rates can be entered, edited and charted; every lookup path returns
correct provenance; the BR-09 suite is green.

---

### Stage 2 — `accounts` → **checkpoint: net worth usable**

The highest-value module and the one answering the driving question (OBJ-02).

- **Account** — nine types, four liquidity tiers, three statuses, opened/closed dates. **Currency immutable once any balance exists, enforced at database level** (BR-08, §9.1) — a rule enforced only in application code is a rule that holds until something writes around it
- **Balance** — unique on account + month; entry behaves as create-or-replace so a second balance for the same month is impossible rather than discouraged
- **Net worth service** — the single implementation of BR-04. Assembles active accounts, applies dormant carry-forward with a stale flag, applies the liability sign, translates each balance, sums at full precision, rounds once. Returns the total *together with* completeness state, exclusions, and the **oldest** contributing as-at date (ADR-09)
- **Slice services** — type, liquidity tier, currency, account. Each partitions the same per-account output rather than summing independently, so every slice totals to the same net worth figure by construction
- **Lifecycle** — set dormant; close with a date; reclassification returning a **restatement advisory** naming how many months change, with both actions saving; **hard delete only for accounts with no balances**, closure otherwise (ADR-14)
- **API** — month close view for a period, trend over a range, point-in-time position, the four slices, single-account balance history
- **Screens** — Month Close, Accounts, Account detail, Net worth

**Month Close is the screen SC-01 lives or dies on.** Rates first so the whole pass runs
in one tab order; prior month's balance immediately left of the input; 28px right-aligned
mono inputs; **autosave on blur with a per-row saved indicator and deliberately no batch
save button**; Tab advances to the next account; a persistent completeness readout pinned
below the header. Month Close as a whole is **not** a transaction — a partly closed month
is a legitimate state, not an error requiring rollback (§9.6).

**Hand-worked scenario test (AS-03).** A three-currency net worth month with one
carried-forward rate, worked by hand once and encoded as fixed expected figures. This is
the actual control on correctness; coverage is only the floor. Add the same figure as the
fifth smoke-test assertion.

**Exit criteria — and the checkpoint.** Close one *real* month using net worth alone.
This is an internal milestone, not a release; BRD decision 50's single-release commitment
stands. It is the only genuine mitigation for RISK-08's indefinite drift, and it tests
SC-01 against real data months before the full system exists. Reassess OI-14 (back-fill
rigidity) and RISK-03 (completeness friction) here, with evidence.

---

### Stage 3 — `cashflow`

- **Category** — two-level taxonomy seeded per BR-22 (subject to OI-06), Title Case; add, rename, deactivate; **deletion refused once referenced**, enforced in the database
- **Transaction** — date, amount, currency, direction, exactly one child category, optional note. Plus the **optional account reference and optional import batch reference** — both captured from day one, both read by nothing in v1, both **one-way doors** (ADR-13). This is the single most consequential thing in Stage 3 that is invisible in v1
- **Duplicate warning** — non-blocking advisory on matching date, amount and category (FR-23)
- **Recurring templates** — proposed each period, **never posted automatically**; the amount is adjustable at confirmation; a confirmed transaction is thereafter independent of its template
- **Reporting** — monthly totals by child and parent category, income and expense separated, per currency and never translated; category trend over a range
- **Screens** — Cash flow with three tabs: Entry, Category report, Categories

**Two prohibitions carried into the UI copy.** There is **no transfer affordance anywhere
in the application** — a standing note states that moving money between your own accounts
is not a transaction and shows only as two balance changes at the next close. And no
report ever sums cash flow figures together with balance figures (BR-12).

**Exit criteria.** A month's transactions entered end to end, recurring proposals
confirmed and skipped, category report matching hand arithmetic, RISK-01 (entry friction)
assessed against real use.

---

### Stage 4 — `investments`

**Build the replay engine first, in isolation, before any model or screen touches it.**

- **FIFO replay engine** — a pure function: a holding's transactions in date order in, lot states / consumption / cost basis / realised gains / consistency out. **No database writes, no stored lot state, no stored cost basis, no stored realised gain** (ADR-06). A buy *is* a lot; its remaining quantity is replay output. A split is a transaction in the sequence, not an edit to lots — so a 2:1 split dated March doubles a February lot and leaves an April lot alone
- **Holding** — name, instrument type, currency, estimated tax percentage. Scoped to one account: the same instrument at two brokers is two holdings with independent queues (**one-way door**, §13.4)
- **Investment transactions** — buy, sell, split, distribution, reinvestment. Purchase fees into cost basis; sale fees off proceeds
- **Retroactive invalidity** — FR-33 rejects an over-sale *at the point of entry*; a sale invalidated later by a historic edit is **flagged, never blocked**, explained specifically, and clears itself when corrected (ADR-07). Show a before-and-after whenever a replay alters a previously reported figure (TR-08)
- **Realised gains** — grouped by holding currency, **never summed across currencies**; estimated tax applied to gains only, labelled indicative on every screen and export
- **Screens** — Investments: holdings, the open-lot FIFO queue given a full column, buy/sell entry, realised gains full width beneath

**Two absolute prohibitions stated in copy on the screen:** unrealised gain does not exist
in this system, and estimated tax is a user-typed percentage rather than a calculation.

**Tests, by name.** Every BR-16 and BR-20 edge case: partial lot consumption; a sale
spanning three lots; over-sale rejection; fee treatment on both sides; a split across
lots with a purchase either side of it; dividend reinvestment creating a lot at the
reinvestment price. **Hand-worked scenario (AS-03):** a multi-lot FIFO sale with fees and
an intervening split, verified by hand once and encoded. **Property-based tests** for
invariants that hold universally — consumed quantity never exceeds purchased quantity.

**Exit criteria.** The hand-worked scenario matches to the last decimal place; property
tests green; a holding can be made inconsistent by a historic edit, is flagged rather than
blocked, and clears on correction.

---

### Stage 5 — Dashboard, export and polish

Built last deliberately: RISK-06 notes the dashboard is the most expensive screen and the
most likely to be rebuilt once real use reveals what is actually looked at.

- **Dashboard** — fixed layout, no configurable widgets: net worth summary and 24-month trend; **outstanding tasks** (the only bordered panel on the screen, because it is the product's conscience); cash flow summary by currency; investments summary by currency; backup status strip
- **Backup status service** — newest dump's timestamp and size, compared against the newest data modification. **Warns when the newest dump predates the newest data change.** This is the control that converts RISK-02 from nominally to actually closed, because a silent backup failure is otherwise indistinguishable from success until the moment it matters
- **CSV export** — promoted to **Must** (departure D1). Generated server-side so exports carry exactly the figures the server computed, not rounded display values. A persistent secondary button in every screen header, never a tucked-away tertiary action, because it is the only route data has out of the application
- **The five designed states** — S1 first run, S2 stale rates expanded, S3 complete month (silence is the signal), S4 excluded account, S5 mid-close
- **Responsive** — reporting screens reflow to tablet with the spine becoming a horizontal ascending month strip; data entry screens are desktop-only by design and do not reflow. Note that FR-54 / NFR-09 remain **deferred** at the network level under D6 unless the alternative proxy route in §2 is taken
- **Restore rehearsal** — execute the §11.3 procedure deliberately once, end to end, before the first live close. This is the act that discharges DEP-02 and closes TR-03

**Exit criteria (OI-07, acceptance).** All acceptance criteria pass **and** one full month
is closed in live use across all four modules with no blocking defects.

---

## 5. Rules that hold across every stage

Violating any of these is a defect regardless of whether a test catches it.

1. **No computed figure is ever persisted.** Not net worth, not slice totals, not
   month-on-month change, not lot remaining quantities, not cost basis, not realised gain.
   This is what makes BR-23's unrestricted historic editing free rather than dangerous
   (ADR-05).
2. **One definition per calculation.** One place where net worth is defined, one where
   translation happens, one where FIFO is computed. A dashboard that computes its own
   summary permits the dashboard and the report to disagree, and the user has no way to
   know which is right.
3. **Money crosses the API as a string paired with a currency code, never a JSON number.**
   `JSON.parse` turns a number into a float; a string survives intact (ADR-12).
4. **Aggregate responses always carry their completeness state, exclusions and rate
   provenance**, so a consumer cannot render a total without the information that
   qualifies it (§8.2).
5. **Advisories never block; errors block and say nothing was saved.** Three advisories
   exist and no more: probable duplicate, rate variance, historic restatement.
6. **Deletes are soft, everywhere** (ADR-03).
7. **Colour is semantic only.** Every coloured state also carries a glyph or a word, so
   meaning survives without hue.
8. **Do not build what §"Explicitly out of scope" in the design handoff forbids.**
   Inventing market prices, unrealised gain, a portfolio return percentage, transfers,
   drill-down, configurable widgets or an onboarding wizard makes the implementation
   *wrong*, not generous.

---

## 6. Open risk register for the build itself

| ID | Risk | Action |
|---|---|---|
| ~~P-01~~ | ~~`central-station`'s nginx config is not persisted~~ | **Closed 15 Aug 2026.** `conf.d` now mounted read-only from `d:\Repositories\vibe-city`, verified (§2.1) |
| **P-02** | **The shared database puts a decade of hand-entered data behind another project's teardown.** Accepted by the D6-db decision; the application cannot prevent it | The start-of-session `pg_dump` (ADR-11) is the only backstop, which promotes it from good practice to load-bearing. Ship it in Stage 0, verify it before Stage 1, and treat the dashboard's backup-age warning as a Must rather than dashboard polish |
| **P-03** | **A shared instance is upgraded on someone else's schedule.** A PostgreSQL major-version bump on `data-center` is no longer this project's decision, against quality attribute 4 (running untouched for years) | The dump is version-portable in a way a volume copy is not (§11.3 already rejects volume copying). Worth agreeing that `data-center` upgrades are announced rather than incidental |
| TR-01 / OI-11 | Django 5.2's formal support statement for PostgreSQL 18 | Practically settled by the platform already running 18.4, but unverified by me. One glance at the Django docs closes it |
| TR-02 / OI-12 | The Windows backup folder may not be replicated off-machine | **Severe.** Confirm at Stage 0. Unreplicated, a disk failure takes the live database and every dump together |
| TR-03 | The restore procedure is documented but never executed | Execute once deliberately before the first live close |
| TR-04 | 80% coverage reached without the arithmetic being verified | The hand-worked scenarios at Stages 2 and 4 are the actual control, and they depend on the figures being worked by hand once |
| TR-06 (revised) | pgdata bind-mounted to a Windows path | Named volume only. Stated in the runbook as a hard rule |
| **P-04** | **A development process can reach the production database** (E12, §2.3). `data-center` publishes `0.0.0.0:5432`; development wants `localhost:5433`. One mistyped digit points a `DEBUG`-on server with pending migrations at live financial data, silently | **Severe, and the sharpest edge in this topology.** Remove the host publish so production is physically unreachable from any host process, or narrow it to `127.0.0.1` and assert the database name in the smoke test. Yours to call — it touches a live shared container |
| P-05 | Development and production diverge in ways only visible after deployment — static file serving, `DEBUG`, cookie behaviour | The Vite proxy keeps authentication same-origin in both. Deploy to the container early and often rather than at the end of a stage |
| RISK-04 | A transfer entered as an expense overstates spending and nothing detects it | Open and unmitigated by decision. Behavioural mitigation only. Adding a transfer flag later is cheap and affects no historic data |
