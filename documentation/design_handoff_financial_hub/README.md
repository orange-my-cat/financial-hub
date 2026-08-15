# Handoff: Financial Hub — single-user net worth tracker

## Overview

Financial Hub is a locally hosted, single-user web application that replaces a spreadsheet. One person uses it: an individual living between Australia and Malaysia, holding money in multiple currencies and reporting in USD. There is no second user, no sharing, no delegation, no organisation.

The system's spine is **net worth tracking**. It exists to answer one question with confidence: *is the balance of this account increasing, and what is its trend?* — for any single account, in under thirty seconds.

The defining constraint: **account balances are manually entered monthly snapshots, never derived from transactions.** The system can show *that* a balance moved; it generally cannot explain *why*. Nothing in the UI may imply transaction-derived balances.

The dominant interaction is a **monthly close** sitting at a desktop: enter month-end balances for every account, enter required exchange rates, enter the month's transactions, record investment activity — completable in one sitting. Between closes, use is read-only. Friction during the close is the primary failure mode.

## About the design files

The files in this bundle are **design references created in HTML** — prototypes showing intended look and behaviour, not production code to copy directly. The task is to **recreate these designs in the target codebase's existing environment** (React, Vue, Svelte, etc.) using its established patterns, component library and state management. If no environment exists yet, choose an appropriate framework and implement the designs there.

`Financial Hub.dc.html` is a design board: a canvas holding all screens side by side as cards, each card a full 1440px screen with the app chrome drawn in. It is not the application shell. In the real application there is one chrome (icon rail + header) and screens swap inside it.

## Fidelity

**High fidelity.** Colours, typography, spacing, table anatomy and state treatments are final and exact. Recreate them precisely, substituting the codebase's own primitives where they exist. The Month Close inputs in the prototype are functionally wired (type → blur → saved indicator → completeness counter updates); every other screen is static.

---

## Design tokens

### Colour — six values, every one a role

| Token | Hex | Role |
|---|---|---|
| Ground | `#161826` | Page and rail base. Rail is `#12141f`, spine gutter `#131523`, raised surfaces `#232532`. |
| Ink | `#e9e9ed` | Figures and labels. Stepped as `rgba(233,233,237,.85 / .55 / .45 / .30)` for hierarchy. |
| Accent | `#9184d9` | Interactive only — focus, current month, links, triangulated rate. Light step `#b5abfc` for text on dark. Never used for data. |
| Carry | `#c9a15e` | Stale, carried, incomplete, advisory. Always paired with a glyph or word. |
| Breach | `#d1756a` | Missing, excluded, error, decrease. Never decorative. |
| Rise | `#6fae90` | Saved, and increase in a change column. Nothing else. |

Rules: colour is semantic only — nothing is coloured for decoration. Every coloured state also carries a shape or a word, so meaning survives without hue. Divider hairlines are `rgba(233,233,237,.10)`; table row rules are `rgba(233,233,237,.08)` and fade to transparent over the first and last 48px of the row.

### Typography — three faces, strictly divided

| Role | Face | Sizes |
|---|---|---|
| Wordmark | Instrument Serif | 22px expanded rail, 21px collapsed ("FH"), colour `#9184d9` |
| Display | Domine | 27px screen titles, 22–32px panel headings, `line-height: 1.05` |
| Interface | Inter 400 / 500 | 13px body, 12.5px table cells, 11.5px secondary, 10px uppercase labels with `letter-spacing: .14em` |
| Data | IBM Plex Mono 400/500 | 12.5px table figures, 13px emphasis, 27–31px hero totals, `font-variant-numeric: tabular-nums` |

Google Fonts: `Instrument+Serif:ital@0;1`, `Domine:wght@400;500;600`, `IBM+Plex+Mono:wght@400;500;600`, `Inter:wght@400;500;600;700`.

### Number formatting

- Always two decimal places, thousands separated with commas, tabular figures, right-aligned in tables.
- **Money never appears as a bare number.** The currency code is inseparable from the amount, set one size down (10.5–11.5px) at 50% ink, immediately after the figure.
- Negatives take a **minus sign** — `−12,450.00 USD` — never parentheses.
- **Liabilities are entered as positive figures**; the system applies the sign. Entry shows a positive number, reporting shows the reduction.

### Spacing and density

- Screen gutters 28px (20px at tablet), 18–20px between panels, 14–16px inside panels.
- Table rows ~30px, cell padding 5.6px vertical / 5.6px horizontal, header labels 11px uppercase.
- Radii: 5–6px small chips and rail items, 8–10px panels and inputs, 9px advisory boxes.
- Inputs: `min-height: 36px` standard, 28px in the Month Close grid; padding `3px 8px` in grid, `6px 10px` elsewhere.

### Table anatomy

Header row: 11px uppercase Inter at 60% ink, `letter-spacing: .08em`, bottom rule fading at both ends. Body rows: 12.5px mono figures right-aligned, 13px Inter for names, 11.5px at 55–65% ink for secondary attributes (type, tier, currency). Row hover: `rgba(233,233,237,.04)` overlay, rule keeps painting. Totals row: same rules, label in Inter 500, figure one step larger.

### Form anatomy

Label 12px at 70% ink above the field. Input: `#232532` fill, 1px `rgba(233,233,237,.16)` border, 8px radius. Hover raises the border to 45% ink; focus takes a 1px accent border; keyboard focus elsewhere is `outline: 2px solid #9184d9; outline-offset: 2px`. Buttons are **outlined, never filled** — primary is a 1px accent border on transparent with accent text; secondary is a divider-coloured border.

---

## State treatments — the substance of the system

These are non-negotiable and each has a visible consequence.

### 1. Entered vs stale

A **stale** balance is one carried forward from an earlier month because none was entered. It must never be mistaken for a figure the user typed.

- Entered: full ink, no mark.
- Stale: ink dropped to 45%, `border-bottom: 1px dotted #c9a15e`, and a superscript `c` in Carry. A footnote or Source column names the month it was carried from.

### 2. Rate as-at date — silent when it doesn't matter

When every contributing rate is fresh, **show nothing** — no as-at date, no disclosure control. When any contributing rate is stale, show the **oldest** contributing as-at date in a Carry-tinted strip below the figure, expandable to per-currency detail (pair, rate, as-at date, provenance, one row per currency). Both states are designed: see cards `S3` (silent) and `S2` (expanded).

### 3. Rate provenance

Three values, visible on every rate: **exact** (unmarked — the common case earns no ink), **carried** (superscript `c`, Carry), **triangulated** through USD (superscript `t`, `#b5abfc`).

### 4. No rate at all → exclusion

Where no rate exists on any date, the affected account is **excluded from the translated total**, the exclusion is stated explicitly on the figure ("Excludes 1 account — no USD/SGD rate exists"), and the balance is **never shown as zero**. In tables the excluded row keeps its own-currency figure and its place; only the translated column withholds a number, replaced by the words "excluded — no rate" in Breach.

### 5. Month completeness — four states, not two

A 11px square glyph carries the state, so it reads without colour:

| State | Glyph | Meaning |
|---|---|---|
| Complete | solid ink square | every account and rate present |
| Incomplete | half-filled Carry square (`linear-gradient(90deg,#c9a15e 50%,transparent 50%)`) | some entered, some absent |
| Missing | hollow Breach square | the month exists, nothing entered |
| Outside Range | dashed neutral square | before the first account opened — not a fault |

### 6. Warning vs error

**Warnings are advisory, sit beside the thing they concern, keep both actions live, and never block.** Treatment: 1px dashed Carry border, 9px radius, an uppercase "ADVISORY · <kind>" label in Carry, a sentence of plain explanation, and two or three buttons that all leave the data saved. Three warnings exist: probable-duplicate transaction, exchange-rate variance, historic restatement on reclassification.

**Errors block and are structurally different.** Two forms:
- *Non-field*: a banner with a solid 3px Breach left bar on a `rgba(209,117,106,.10)` fill, uppercase "ERROR" label, and a statement that nothing was saved.
- *Field-level*: the input border turns Breach and a message appears directly beneath it in Breach, prefixed with a ▲ glyph.

---

## The signature element: the ledger spine

A persistent **month rail down the right edge of every screen**, 100px wide, `#131523` ground, latest month at the top. Each row is a month label in 11px mono plus its completeness glyph. The current month is keyed with a 2px accent right border and a `rgba(145,132,217,.14)` fill. The spine is the same on every screen — it ties every view to one timeline and makes the shape of the user's history legible at a glance.

At tablet width the spine becomes a **horizontal strip below the header**, running **ascending left to right** (oldest → newest), with the current month keyed at the right end.

---

## Navigation

An icon rail on the left, 56px collapsed, expanding on hover to a 208px drawer showing names and a task-count badge per destination.

Tabs, in order: **Dashboard · Net worth · Accounts · Month Close · Cash flow · Investments · FX rates**. **Settings** is pinned to the bottom of the rail, separated from the tab group.

Nested, not tabs:
- **Account detail** opens from an account name in the Accounts table. Breadcrumb: `Accounts / <account name>`. The rail keys Accounts.
- **Categories** is the third tab on Cash flow, beside Entry and Category report. The rail keys Cash flow.

Badges show outstanding work: Month Close 14, Cash flow 2, FX rates 2 in the reference data.

**Reporting currency and date range are persistent view state, not filters.** Both live in the chrome, both are reflected in the URL, and every view is bookmarkable. Each screen states in words which of the two it obeys. Where a control does not apply (Month Close, Account detail, Investments) it renders at 40% opacity and the subhead says so.

---

## Screens

### 1 — Dashboard

Fixed layout. No configurable widgets, no drag-and-drop. Panel order, top to bottom:

1. **Net worth summary and trend.** Left column 330px: the total in 31px mono with its currency code, month-on-month change in amount and percentage, then the as-at strip (only when a rate is stale) and the exclusion notice (only when an account is excluded). Right column: a 24-month SVG polyline, 2px accent stroke, no fill, no axes, with a fading rule beneath and Sep 2024 / 24 months / Aug 2026 labels above.
2. **Outstanding tasks.** A bordered panel, 1px `rgba(201,161,94,.35)`, 10px radius — the only panel on the screen with a border, because this panel is the product's conscience. Rows: a count in 15px mono tinted Carry or Breach, the task in 13px Inter, and a right-aligned link to the screen that resolves it. Tasks: accounts without a balance, currencies with missing or stale rates, unconfirmed recurring proposals.
3. **Cash flow summary.** A table by currency: income, expense, net. Subhead states that these figures do not affect any account balance.
4. **Investments summary.** A table by currency: holdings count, cost basis, realised gains for the year. Never combined across currencies.
5. **Backup status.** A single 8px-tall strip: state dot, last-written date, destination path in mono, link to Settings.

Obeys the reporting currency. Fixed to the current month — the date range does not apply.

### 2 — Month Close (the most important screen)

Twenty rows, one per active account. Optimised for a person typing twenty numbers without lifting their hands.

- Header, then a **persistent completeness readout** pinned below it: the state glyph, the state word, `n of 20 balances · n of 4 rates` in mono, what remains, and the line "Autosaves on blur. There is no save button."
- **Section 1 — Exchange rates required for this month.** A table of pairs with rate, provenance, as-at date, and an entry field per pair. The rate-variance advisory appears directly beneath. Rates come first so the whole pass runs in one tab order.
- **Section 2 — Balances as at 31 <Month> <Year>.** Columns: row number, account, type, currency, **prior month's balance**, the input, saved indicator. The prior balance sits immediately left of the input — that adjacency is the point of the screen.
- Inputs: right-aligned mono, 28px tall. On blur the value saves, the field takes a `rgba(111,174,144,.07)` fill with a 40% Rise border, and the indicator reads "saved" in Rise. Unsaved rows show an em dash at 30% ink.
- **Autosave on blur; there is deliberately no batch save button** — an interruption mid-close must not cost the entry, and a partly closed month is a legitimate state, not an error.
- Tab advances to the next account.
- Neither view control applies; both render inert.

### 3 — Net worth

The landing report. Total, month-on-month change in amount and percentage, a 24-month trend line, and **slice toggles** as a segmented control: by account type, by liquidity tier, by currency, by account. Toggling is the whole interaction model — there is **no drill-down**.

Below the chart, two tables side by side: the active slice (nine account types, each labelled asset or liability, liabilities in Breach with a minus sign, totalling to net worth) and the month-on-month table (month, net worth, change, percentage, latest first).

Date range and reporting currency both apply; both are in the URL.

### 4 — Account detail

Serves the driving question. Opened from a name in Accounts.

Header: breadcrumb, account name in Domine 27px, then tags for type, liquidity tier, status and currency plus the opened date. Left column: the balance in 31px mono in **the account's own currency**, then a one-line direction statement ("Increasing. Up in ten of the last twelve months."), then month-on-month change, twelve-month change, and a count of stale months in range. Right: a 12-month trend line and the month table — month, balance, change, percentage, source — with stale months marked by the superscript `c` and a Source column.

The reporting-currency control does not apply. A note states that balances are entered snapshots and the system cannot say why one moved.

### 5 — Accounts

Create, edit, close, set dormant. Columns: account, type, liquidity tier, status, currency, opened, closed, actions.

- Currency is **locked once balances exist** — marked with a superscript `ᴸ` beside the code.
- **Delete is offered only for accounts with no balance history**, rendered in Breach; every other row offers **Close**. Deletes are soft.
- Reclassifying an account **restates history** — the restatement advisory appears above the table, names how many months change, and both actions save.
- Account names are links to Account detail.

### 6 — Cash flow

Three tabs: **Entry**, **Category report**, **Categories**.

*Entry* — a single-row quick-entry form: date, amount, currency, child category, optional note, Add. The probable-duplicate advisory appears immediately below when a match is detected; adding anyway is always permitted. To the right, **recurring proposals awaiting confirmation** as cards with Confirm / Edit / Skip — proposals are never posted automatically. Below the form, the month's transactions. Entry is manual and per-transaction; there is no import path, so entry speed is the whole battle.

A standing note states: moving money between your own accounts is not a transaction, has no record here, and shows only as two balance changes at the next close. **There is no transfer affordance anywhere in the application.**

*Category report* — parent and child categories with income, expense and net per currency, a category trend chart over the selected range, and totals by currency. Amounts stay in the currency they were entered in and are not translated.

*Categories* — a two-level taxonomy: parent categories containing child categories; transactions attach to children only. Seeded on first run, editable thereafter. A child with no transactions can be deleted; **a category that has been used is deactivated, never deleted** — it disappears from entry, its history stays intact.

### 7 — Investments

Every figure stays in its holding's own currency. This is the one screen the reporting-currency toggle does not apply to, and it says so in the subhead.

- **Holdings**: symbol, name, total quantity, total cost basis, currency, lot count.
- **Open-lot FIFO queue** per holding, given a full column: purchase date, remaining quantity, unit cost, remaining cost basis, and a total. This is the screen that makes cost basis legible.
- **Buy / sell entry**: a Buy/Sell segmented control, date, holding, quantity, unit cost, fees. Corporate actions limited to fees, splits and reinvestment.
- **Realised gains**, full width beneath, **grouped by currency and never summed across currencies**: sale date, holding, proceeds, fees, cost basis, gross gain, estimated tax percentage, net gain, with a per-currency total only.
- A holding whose history has been retroactively invalidated by an edit is **flagged, never blocked** — the advisory names the offending edit; figures still display and entry still works.

Two absolute prohibitions, both stated in copy on the screen: **unrealised gain does not exist in this system** (no market prices, no portfolio return percentage, no paper gain anywhere), and **estimated tax is a user-typed percentage, not a calculation** — the net figure is labelled indicative and clearly the user's own estimate, reflecting no jurisdiction's rules.

### 8 — FX rates

- **Bulk entry for a single date**: one as-at field, then one field per pair, one Save all button.
- The **rate-variance advisory** on entry, stating the prior rate and the percentage difference. It saves either way.
- **Daily rate table** with provenance per rate and an Edit action per row.
- **Missing and stale summary**: one row per pair with the completeness glyph — no rate on record (Breach), n days old against the threshold (Carry), current (neutral).
- **Rate trend chart** per currency pair with start and end values labelled.

### 9 — Categories

See Cash flow, third tab.

### 10 — Settings

Default reporting currency (segmented control, stated as a display choice only — stored balances are always USD and never rewritten); timezone (one, fixed, applied to all date interpretation — all dates are plain calendar dates with no time component); rate staleness threshold in days, default 7; password change; backup status and destination (status readout only — backups are taken outside the application, there is nothing to run or restore from here); and a global CSV export.

**CSV export is available from every table and report.** It is the only route data has out of the application, so it is a persistent secondary button in every screen header, never a tucked-away tertiary action.

---

## States to design and build

| Card | State | What it shows |
|---|---|---|
| `S1` | First run | The system is empty. No accounts, no balances, no history. Two numbered steps — create accounts, then close a month, the second disabled until the first is done. An invitation, not a marketing screen. No onboarding wizard. The spine shows every month as Outside Range. |
| `S2` | Stale rates | The as-at strip expanded to per-currency detail; tasks raised on the dashboard. |
| `S3` | Complete month | Nothing stale, no as-at date, no exclusion notice, no tasks. Silence is the signal. |
| `S4` | Excluded account | The total states its exclusion; the excluded row keeps its own-currency figure. |
| `S5` | Mid-close | Some balances entered, some rates missing, completeness partial — plus the readout rendered in all four completeness states for reference. |

---

## Interactions and behaviour

- **Month Close**: `onChange` updates the value, `onBlur` commits and sets the saved flag; the completeness counter recomputes on every commit. Tab moves to the next account's input. No batch save exists. A partly closed month persists as-is.
- **Slice toggles** (Net worth) swap the grouping of the lower-left table only; the chart and headline are unchanged. No navigation, no drill-down.
- **Rail hover** expands the 56px icon rail to a 208px drawer with names and badges.
- **As-at disclosure** expands and collapses the per-currency rate detail; it is not rendered at all when no contributing rate is stale.
- **Advisories** never block. Their actions all leave data saved.
- **Errors** block the save and state that nothing was saved.
- **Everything is editable at any time, including history.** Deletes are soft. An account can be hard-deleted only if it has no balances; otherwise it is Closed.
- **Responsive**: reporting screens (Dashboard, Net worth, Account detail, Category report) reflow down to tablet — the spine becomes a horizontal ascending month strip below the header, two-column bodies stack, no table columns are dropped. Data entry screens (Month Close, Accounts, Cash flow entry, Investments, FX rates, Settings) are **desktop-only by design** and do not reflow.

## State management

- `reportingCurrency`: `'USD' | 'AUD' | 'MYR'` — display only, in the URL, never mutates stored data. Stored and base currency is always USD.
- `dateRange`: start and end reporting months, in the URL.
- `currentMonth`: the reporting month being closed. A reporting month is a calendar month with its boundary at the last calendar day; all balances are as at that date.
- Per-account balance entries keyed by `(accountId, month)`, each with an entered/carried origin flag.
- Per-pair rates keyed by `(pair, date)`, each with provenance `exact | carried | triangulated`.
- Derived per month: completeness state, the set of missing balances, the set of missing or stale rates, the oldest contributing as-at date, and the set of excluded accounts.
- Recurring proposals: pending until explicitly confirmed, edited or skipped. Never posted automatically.

## Fixed vocabulary — use these exact terms

- **Account types (nine, no grouping above them)**: Current/Checking, Savings/Deposit, Investment/Brokerage, Pension/Retirement, Property, Physical Asset (assets); Credit Card, Loan/Mortgage, Other Liability (liabilities).
- **Liquidity tiers (four)**: Instant, Short, Long, Locked.
- **Account status (three)**: Open, Dormant, Closed.
- **Month completeness (four)**: Complete, Incomplete, Missing, Outside Range.
- **Rate provenance (three)**: exact, carried, triangulated.

## Explicitly out of scope

Do not build any of these; inventing them makes the implementation wrong rather than generous:

market prices · unrealised gain · portfolio return percentage · transfers between accounts · budgets · forecasting · tax computation · bank or broker connections · file or statement import · CSV *import* · multi-user, avatars, sharing, permissions · notifications or email · drill-down navigation · configurable dashboard widgets · audit trail or change history · in-app backup and restore controls beyond a status readout · onboarding wizards · marketing or landing pages · reconciliation against external statements · mobile-optimised data entry

## Assets

No image assets. All iconography is inline SVG on `currentColor`, 24px viewBox, 1.5px stroke, round caps and joins — Phosphor-style geometric glyphs, one per rail destination. Charts are inline SVG polylines with `vector-effect: non-scaling-stroke`, no libraries. Sparklines, where used, are flex rows of 4px-wide divs.

## Files

- `Financial Hub.dc.html` — the design board. Open it in a browser. Cards are addressable by anchor: `#1ds` design system, `#2a`–`#2j` the ten screens, `#2m`–`#2q` the five states, `#2r`/`#2s` the tablet layouts. Turn 1 at the bottom of the board holds the three signature-element explorations, kept for reference; the ledger spine (`#1a`) was the one chosen.
- `nocturne-styles.css` — the Nocturne design system stylesheet the board builds on. Its `:root` block carries the base tokens (ground, surface, accent, neutral and accent ramps, spacing scale, radii, shadows) and its component layer carries `.btn`, `.input`, `.seg`, `.tag`, `.table`, `.card`, `.dialog`. The six semantic colours, the three type faces and every state treatment above are additions on top of it, documented here and defined in the board's own `:root`.
