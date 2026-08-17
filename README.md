# Financial Hub

A locally hosted, single-user net worth tracker. One person uses it: someone living
between Australia and Malaysia, holding money in several currencies and reporting in USD.

The system's spine is net worth. It exists to answer one question with confidence — *is
the balance of this account increasing, and what is its trend?* — for any single account,
in under thirty seconds.

**Account balances are manually entered monthly snapshots, never derived from
transactions.** The system can show *that* a balance moved; it generally cannot explain
*why*. Nothing in the interface may imply otherwise.

Three documents govern the work, and this file governs none of it — see
[`documentation/`](documentation/) for the BRD (what), the HLD (how) and the BUILD_PLAN
(sequencing, and where the HLD's assumed environment differs from the real one).

---

## Status — Stage 0

Foundations. Nothing financial. The objective is a running, backed-up, authenticated
shell at `http://financial-hub.localhost` with the test harness proving itself against an
empty database.

| Stage | Contents | State |
|---|---|---|
| **0** | Repository, configuration, both topologies, auth, test harness, backup entrypoint | built |
| **1** | `core` + `fx` — money, rate lookup, translation, completeness | built |
| **2** | `accounts` — Month Close, net worth, slices | built |
| **⟶** | **Checkpoint: close one real month using net worth alone** | **outstanding — yours** |
| **3** | `cashflow` | built |
| **4** | `investments` — replay engine built in isolation first | built |
| **5** | Dashboard, CSV export, backup status, the spine | built |

493 tests, 95% line coverage. The invariant suite runs alone in under three seconds
(`pytest -m invariant`).

### What is not done

| | |
|---|---|
| **The checkpoint** | One real month closed end to end. It is the only genuine mitigation for RISK-08's indefinite drift, and BUILD_PLAN wants OI-14 (back-fill rigidity) and RISK-03 (completeness friction) reassessed against it **with evidence**. Nobody but the Product Owner can produce that evidence |
| **TR-03 — restore rehearsal** | The §11.3 procedure has never been executed. Do it once, deliberately, before the first live close. That act is what discharges DEP-02 |
| **OI-12** | Backups land on a local disk rather than a replicated one. Partly closed, not closed |
| **Responsive** | Reporting screens reflow at tablet width and the spine becomes a horizontal strip; data-entry screens are desktop-only by design. Built, but only verified at 1440px |
| **The five designed states** | S1–S5 emerge from real data rather than being separately built. S1 (first run) and S3 (silence) are verified; S2, S4 and S5 have backend tests but no visual check |

---

## The two numbers

Everything else in this file is detail. These two are the ones that cause damage when
confused:

| | Development | Production |
|---|---|---|
| Django | **port 8001** (8000 belongs to `control-tower`) | container port 8000, published nowhere |
| Database | `localhost:**5433**` → `financial_hub_dev` | `data-center:5432` → `financial_hub` |

`data-center` publishes `0.0.0.0:5432` on this host, which is the same host the
development server runs on. One mistyped digit in `.env` points a hot-reloading server,
with `DEBUG` on and migrations pending, at a decade of real financial data.

`config.settings.dev` refuses to start if it finds itself pointed at the production
database or the production port, and `manage.py smoke_test` asks the server it actually
connected to what its name is. Neither is a licence to be careless — see BUILD_PLAN P-04.

---

## Prerequisites

Installed on the host, once:

- **Python 3.14.** Installed and verified — Django 5.2.17 declares 3.10 through 3.14 in
  its own classifiers. The production image uses the same minor version.
- **Node 24.19.0** with npm 11. Installed and verified against Vite 6.

  A shell started before an install inherits the old `PATH`, so `node --version` can fail
  in a terminal that was already open while working perfectly in a new one. Refresh with
  `$env:Path = [Environment]::GetEnvironmentVariable("Path","Machine") + ";" +
  [Environment]::GetEnvironmentVariable("Path","User")` before concluding anything is
  missing.
- **Docker Desktop**, already present, with the `vibe-city` network and the two PostgreSQL
  containers running.

Databases and roles, created once on the shared instances:

```sh
# Development — data-center-test, port 5433
docker exec -it data-center-test psql -U postgres -c "CREATE ROLE financial_hub LOGIN PASSWORD 'choose-one';"
docker exec -it data-center-test psql -U postgres -c "CREATE DATABASE financial_hub_dev OWNER financial_hub;"

# Django creates and drops test_financial_hub_dev itself, per run. The role needs to be
# allowed to do so.
docker exec -it data-center-test psql -U postgres -c "ALTER ROLE financial_hub CREATEDB;"

# Production — data-center, port 5432. Take the extra second to read the container name.
docker exec -it data-center psql -U postgres -c "CREATE ROLE financial_hub LOGIN PASSWORD 'choose-another';"
docker exec -it data-center psql -U postgres -c "CREATE DATABASE financial_hub OWNER financial_hub;"
```

---

## Development

A local hot-reloading process on Windows. Only the database is containerised.

### First time

Already done for the development profile — `.venv` exists, `.env` is written, the
`financial_hub` role and `financial_hub_dev` database are created, migrations are applied
and the single user exists. To repeat it on another machine:

```sh
cp .env.example .env
# Fill in DJANGO_SECRET_KEY and POSTGRES_PASSWORD. Confirm POSTGRES_PORT is 5433.
python -c "from django.core.management.utils import get_random_secret_key as k; print(k())"

python -m venv .venv
.venv\Scripts\Activate.ps1                  # PowerShell
pip install -r backend/requirements-dev.txt

cd backend
python manage.py migrate
python manage.py createsuperuser            # the single user
cd ../frontend
npm install
```

### Every day

Two terminals.

```sh
# Terminal 1 — Django on 8001
cd backend && python manage.py runserver 8001

# Terminal 2 — Vite, with HMR
cd frontend && npm run dev
```

Open the **Vite** URL, not 8001. Vite proxies `/api` to Django so the browser sees one
origin, which keeps the session cookie behaving in development exactly as it will in
production — no CORS layer, no `django-cors-headers`, and no class of bug that appears
only after deployment. Opening 8001 directly gets a 501 page explaining this.

### Loading Rates

Rates are typed by hand on the FX Rates screen, and that stays true. `load_rates` is a
backfill and a top-up on top of it — the second implementation of ADR-08's ingestion
seam, fetching each **trading day's closing rate** from Massive.

```sh
cd backend
python manage.py load_rates --from 2016-01-01                       # to today
python manage.py load_rates --from 2026-08-01 --dry-run             # fetch, report, save nothing
python manage.py load_rates --from 2026-01-01 --currency AUD        # one pair
```

Three pairs are loaded by default: `AUD/USD`, `USD/MYR` and `XAU/USD`. Gold is in the
registry as a currency, not as a price — an account denominated in XAU holds a balance of
troy ounces, entered and never derived, and translates through the one translation service
exactly as a foreign-currency balance does. It is the only currency that does **not**
report: a balance may be *held* in ounces, but net worth is not *stated* in them, so the
reporting-currency toggle excludes it (`can_report` on `CurrencyDefinition`, served by
`/api/fx/currencies/` so the Settings screen does not decide it for itself).

Needs `MASSIVE_API_KEY` in `.env`; without it the command says so and everything else
works exactly as before. Three things it does that are not obvious:

- **A rate you typed is never overwritten.** BRD §4.3, and the reason `source` and
  `provider` were captured from day one. Rows from an earlier fetch *are* replaced, so
  re-running a range is safe. The output counts what it left alone.
- **Weekend bars are dropped.** The FX week opens Sunday evening UTC, so the provider
  emits a two-hour Sunday bar whose close is a partial session, not a daily close.
- **Closes are read as `Decimal`, never through `float`.** The wire format is a JSON
  number; `parse_float` is what keeps ADR-02 true through the one door that is not a
  form field.

Only the close is read. Open, high, low, volume and live quotes are all available and
none of them is fetched — this system stores one rate per pair per date, and a second
figure would only ever disagree with the first.

### Tests

```sh
cd backend && pytest
```

Runs against `data-center-test` at `localhost:5433`. Django creates and drops
`test_financial_hub_dev` per run, so development data survives untouched.

```sh
pytest -m invariant        # the financial invariant suite, alone, in seconds
pytest --no-cov            # skip the 80% gate while iterating
```

80% line coverage is the **floor**, not the goal. Coverage measures lines executed, not
arithmetic proven: a FIFO replay can reach 100% from a single simple sale while never
testing a partial lot consumption. The real controls are the named edge cases (BR-09,
BR-16, BR-20) and the hand-worked scenarios at Stages 2 and 4.

A faster, throwaway alternative to `data-center-test`:

```sh
docker compose -f compose.test.yaml up -d
cd backend && POSTGRES_PORT=5434 POSTGRES_DB=financial_hub_ci pytest
docker compose -f compose.test.yaml down
```

---

## Production

The `financial-hub` container joins `vibe-city`, **publishes no port**, and is reached
only through `central-station` at `http://financial-hub.localhost`.

It is a **standalone container, not a compose stack**, matching every other tenant of this
platform. `vibe-city` is a Docker network and a naming theme, not a compose project:
`central-station`, `control-tower`, `data-center` and `data-center-test` are each their own
container and share nothing but the network. The run arguments live in
`scripts/deploy.ps1` rather than in a compose file, which is the same reason
`d:\Repositories\vibe-city\start.ps1` exists — version control, not the Docker daemon, is
where they belong. The healthcheck is baked into the image for the same reason.

### One-time platform changes

```sh
# 1. data-center sits on the default bridge network, where Docker's embedded DNS does not
#    resolve container names. Non-destructive: no recreation, no downtime, and it keeps
#    its existing bridge attachment and published port.
docker network connect vibe-city data-center

# 2. Install the vhost. NOT BEFORE the financial-hub container exists — proxy_pass to a
#    literal hostname is resolved at nginx start, so an absent upstream stops nginx and
#    takes control-tower.localhost down with it.
cp docker/nginx/financial-hub.conf d:/Repositories/vibe-city/nginx/conf.d/
docker exec central-station nginx -t
docker exec central-station nginx -s reload
```

`central-station` is a standalone container, not a compose service — it fronts every
application on this machine and belongs to none of them. Its run arguments live in
`d:\Repositories\vibe-city\start.ps1`; a vhost change needs neither that script nor any
downtime, only the two `docker exec` lines above.

### Deploy

Switch `.env` to the production profile (both blocks are documented in `.env.example`),
then:

```powershell
.\scripts\deploy.ps1            # build, recreate, wait for healthy, smoke test
.\scripts\deploy.ps1 -NoBuild   # recreate from the image already built
```

The script refuses to run against anything but `config.settings.prod` on
`data-center:5432`/`financial_hub`, and refuses to start without an existing
`BACKUP_HOST_DIR`. P-04 is enforced there rather than trusted to the person deploying.

Afterwards:

```sh
docker logs -f financial-hub
docker exec financial-hub python manage.py smoke_test
```

Recreating is safe and is the normal way to deploy a change: the container holds no state,
because the database is in `data-center` and the dumps are on a bind mount.

### What the entrypoint does, in this order

**dump → prune to 30 → migrate → start Gunicorn.**

The ordering is the point. Every schema change is preceded by a restorable snapshot taken
seconds earlier, so a failed migration leaves the application down with the data intact
and a fresh dump beside it.

Under the shared-instance decision this dump is not merely good practice. `data-center`
holds other tenants' databases, and nothing in this application can prevent someone
else's `docker compose down -v`. The dump is the only backstop, which is why a dump
failure stops the container rather than being logged and shrugged off.

---

## Backups and restore

Dumps are compressed `pg_dump` custom-format files, one per container start, newest 30
retained, written to the Windows folder named by `BACKUP_HOST_DIR`.

**That folder must be replicated off-machine.** Unreplicated, one disk failure takes the
live database and every dump together, and OI-12 stays open at Severe.

### Restore, and machine migration — the same procedure

1. Copy the repository to the target machine.
2. Copy `.env` by hand. It does not travel with the repository.
3. Copy the most recent dump.
4. `.\scripts\deploy.ps1`.
5. `docker exec -i financial-hub pg_restore --clean --if-exists --no-owner -h "$POSTGRES_HOST" -U "$POSTGRES_USER" -d "$POSTGRES_DB" < /backups/<file>.dump`
6. `docker exec financial-hub python manage.py smoke_test`, and confirm a known
   net worth figure is unchanged.

Because disaster recovery and machine migration are the same procedure, every machine
move rehearses the restore. **Execute it once deliberately before the first live close.**
That act is what discharges DEP-02 and closes TR-03, and it is currently outstanding.

---

## Layout

```
backend/
  config/          Django project. settings/{base,dev,prod,test}.py, guards.py
  core/            money precision, soft delete, error shape, advisories, smoke test
  accounts/        Stage 2 — Account, Balance, net worth, slices
  cashflow/        Stage 3 — Category, Transaction, recurring
  investments/     Stage 4 — Holding, transactions, FIFO replay engine
  fx/              Stage 1 — ExchangeRate, rate lookup, triangulation
frontend/
  src/lib/         Money type, formatting, API client, view state
  src/shell/       icon rail, header, ledger spine
  src/screens/     Login, and placeholders until each stage lands
docker/            Dockerfile, entrypoint.sh, nginx vhost
documentation/     BRD, HLD, BUILD_PLAN, design handoff
```

**The three-layer rule is absolute.** Models hold structure and database constraints;
services hold every business rule and calculation and are callable without HTTP; views
authenticate, deserialise, call one service, serialise, return. There is exactly one place
where net worth is defined, one where translation happens, one where FIFO is computed.

---

## Pinning dependencies

`requirements.txt` and `package.json` carry ranges; the pins live in lock files (CON-13).
After the first install, and after any deliberate upgrade:

```sh
pip freeze > backend/requirements.lock.txt      # the Dockerfile prefers this when present
# package-lock.json is written by npm install and is committed
```

Rollback depends on those pins, and on the previous image tag being retained — `deploy.ps1`
names the tag in one place, so reverting is editing `$image` and rerunning it with
`-NoBuild`.

---

## Known-outstanding at Stage 0

| | |
|---|---|
| **OI-12** (partly open) | `BACKUP_HOST_DIR` is `D:/Backups/Financial Hub` — nominated, created, and on a local disk. That closes the likely failure (P-02: another tenant's teardown, a bad migration, a lost Docker VM) and leaves the unlikely one open (losing the machine). Syncing that folder later is a one-line change and moves no data |
| **TR-03** | The restore procedure has never been executed. Do it once before the first live close |
| **OI-11** | Closed on the Python side: Django 5.2.17 declares 3.14 support in its classifiers. On the PostgreSQL side Django 5.2 supports 13 and higher, and migrations have now run against 18.4 — settled empirically |
| **P-04** | Accepted as a guarded risk: `data-center` keeps its `0.0.0.0:5432` publish; the settings guard and the smoke test are the tripwires. Both verified to fire |
| Fonts | Loaded from Google's CDN with real fallback stacks. Self-hosting the four families is the right follow-up for a system meant to run untouched for a decade |
