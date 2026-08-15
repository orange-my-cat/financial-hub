# Business Requirements Document
## Personal Finance Tracker — Version 1.0

---

## 1. Document Control

| Field | Value |
|---|---|
| Document title | Business Requirements Document — Personal Finance Tracker |
| Version | 1.0 |
| Date | 13 August 2026 |
| Author | Senior Business Analyst (elicited via structured interview) |
| Owner / Sponsor | The Product Owner (sole stakeholder and sole user) |
| Status | Draft for review |
| Basis | Fifteen-turn requirements interview covering eleven agenda areas |
| Next review trigger | Completion of the first live month close |

### Version history

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1–0.9 | 13 Aug 2026 | BA | Interview in progress; no document produced |
| 1.0 | 13 Aug 2026 | BA | First complete draft following close of interview |

---

## 2. Executive Summary

The Product Owner requires a personal finance tracker for private, single-user use, replacing a spreadsheet that has accumulated approximately seven months of incomplete data. The spreadsheet is not being migrated; the system starts empty.

The system's spine is **net worth tracking**. Its purpose is to answer one driving question with confidence: *is the balance of a given account increasing, and what is its historical trend?* Spending analysis and investment performance are supporting capabilities, not the primary purpose.

The defining design decision is that **account balances are manually entered monthly snapshots**. They are never derived from transactions. This single choice cascades through the entire specification: it removes the need for snapshot-versus-derived precedence rules, it decouples all four modules from one another, and it keeps the recurring monthly effort to a single sitting. It also accepts a known limitation — the system can show *that* a balance moved but generally cannot explain *why* it moved.

Four modules are in scope, delivered as a single release:

1. **Net Worth** — monthly balance snapshots across all accounts, reported by account type, liquidity tier, currency and individual account.
2. **Cash Flow** — a parallel ledger of income and expense transactions against a two-level category taxonomy. It does not affect balances.
3. **Investments** — lot-level records of buys and sells with FIFO cost basis and realised gain computation, reported in each holding's own currency.
4. **FX Rates** — a manually maintained daily exchange rate table that supplies translation rates for net worth, plus a rate trend chart. **This module was deliberately reduced in scope during the interview: it does not track currency conversions.**

The system is a locally hosted web application, single user, protected by a single password, not internet-facing. Success is defined less by feature completeness than by sustained use: the system succeeds if the Product Owner closes a month every month without reverting to the spreadsheet.

Four decisions are flagged as high-risk and likely to change after real use: the hard month-completeness block, per-transaction manual cash flow entry with no import path, pure carry-forward on the FX rate table, and the full multi-panel dashboard.

---

## 3. Business Objectives and Success Criteria

### 3.1 Business objectives

| ID | Objective |
|---|---|
| OBJ-01 | Provide a single, trustworthy record of net worth over time, broken down in a way that shows where wealth sits and how liquid it is. |
| OBJ-02 | Answer the driving question — is a given account's balance increasing, and what is its trend — without recourse to any other tool. |
| OBJ-03 | Provide visibility of spending patterns by category, sufficient to support spending control as a secondary goal. |
| OBJ-04 | Maintain an accurate record of investment cost basis and realised gains, including an indicative net-of-tax position. |
| OBJ-05 | Retire the existing spreadsheet as the system of record for all new financial data. |

### 3.2 Success criteria

| ID | Criterion | Measure |
|---|---|---|
| SC-01 | Sustained low-friction use | Twelve consecutive monthly closes completed without abandonment. This is the primary criterion; all others are subordinate. |
| SC-02 | Driving question answered | The Product Owner can, in under thirty seconds, retrieve the balance history and trend of any single account. |
| SC-03 | Spreadsheet retired | No new financial data is recorded in the spreadsheet after the first live month close. |
| SC-04 | Monthly effort contained | A complete month close — all balances, all rates, all transactions — is achievable in a single sitting. |

### 3.3 Explicitly not a success criterion

Formal reconciliation of system figures against real bank and broker statements was assessed and confirmed as a **nice-to-have, not a v1 pillar** (Assumption A1, confirmed). The system makes no accuracy guarantee against external statements.

---

## 4. Scope

### 4.1 In scope — Version 1

| Area | Included |
|---|---|
| Net Worth | Account administration; monthly balance snapshots; guided Month Close; net worth trend and point-in-time reporting; slicing by account type, liquidity tier, currency and individual account; per-account balance history |
| Cash Flow | Manual per-transaction entry; two-level editable category taxonomy; recurring transactions; monthly category reporting |
| Investments | Lot-level buy and sell records; FIFO cost basis; realised gain computation; transaction fees; stock splits; dividend reinvestment; manual estimated tax percentage per holding |
| FX | Manual daily exchange rate table; carry-forward of unentered days; rate trend chart; translation of balances into base and alternate reporting currencies |
| Cross-cutting | Multi-panel dashboard; CSV export; single-password authentication; settings including reporting currency toggle |

### 4.2 Out of scope — Version 1

| Excluded | Rationale |
|---|---|
| Budgeting and budget-versus-actual | Confirmed out of scope, Area 1 |
| Forecasting, projections, retirement modelling | Confirmed out of scope, Area 1 |
| Tax computation, tax-year reporting, jurisdiction rules | Confirmed out of scope; the estimated tax percentage is a manual input, not a calculation of tax liability |
| Bank, broker or aggregator API connections | Confirmed out of scope, Area 1 |
| Automatic market price feeds | Confirmed out of scope; no security prices are held at all in v1 |
| Multi-user and household sharing | Confirmed out of scope, Area 1 |
| Native mobile application | Confirmed out of scope; responsive read-only web access only |
| CSV or file import of any kind | Confirmed out of scope; deferred to Phase 2 |
| Currency conversion transactions and FX gain/loss | Deliberate reduction of Module 4 from the original brief |
| Split transactions | Assessed as high effort, low benefit for v1 |
| Transfers between own accounts | Not recorded anywhere in the system |
| Derived balances from transactions | Excluded by the snapshot-only decision |
| Effective-dated account classification | Reclassification restates history |
| Unrealised gain, on investments or on currency | Not computable from the chosen data model |
| Reconciliation workflow against statements | Nice-to-have, deferred |
| In-application backup and restore | Handled externally at the database layer |
| Month locking, immutability, audit trail | All history remains fully editable |
| Encryption at rest | No threat model justifies it for a local single-user system |
| Drill-down from chart segments | Deferred to Phase 2 |
| Institution and free-text tag slices in net worth | Deferred to Phase 2 |

### 4.3 Future phases

**Phase 2 (identified, not scheduled):**
- CSV import for cash flow transactions with reusable column mapping — the primary mitigation for the entry-friction risk
- External exchange rate API with manual override
- Drill-down from chart segments to constituent accounts
- Net worth slices by institution and by free-text tag
- Informational comparison of net worth movement against recorded cash flow

**Phase 3 (speculative):**
- Manual per-holding price entry, enabling unrealised gain and a snapshot-versus-holdings comparison
- Budgeting
- Reconciliation workflow
- Second-user support

---

## 5. Stakeholders and User Profile

| Stakeholder | Role | Interest |
|---|---|---|
| The Product Owner | Sponsor, sole user, sole data entry operator, sole consumer of all reporting | Complete |

### 5.1 User profile

- **Single individual.** No delegated access, no shared accounts, no household members.
- **Not a finance professional.** Business rules must be expressed in plain terms; the interface must not assume familiarity with accounting conventions.
- **Geographically split between Australia and Malaysia**, holding assets and liabilities in more than one currency and reporting in United States Dollars.
- **Technically capable.** The system runs locally under the user's own control.
- **Low transaction volume**, mostly recurring in nature (Assumption A6).

### 5.2 Usage pattern

The dominant interaction is a **monthly close sitting** at a desktop: enter month-end balances for every active account, enter or confirm required exchange rates, enter the month's cash flow transactions, and record any investment activity. Between closes, usage is read-only and may occur on a tablet or phone.

### 5.3 Multi-user posture

Version 1 is single-user. The business model should not *preclude* a second user in future, but no multi-user capability is specified, built or tested in v1.

---

## 6. Glossary and Business Definitions

| Term | Definition |
|---|---|
| **Account** | A single holding of value or obligation at a single institution, denominated in exactly one currency. A provider offering multiple currencies is represented as multiple accounts. |
| **Account type** | One of nine fixed classifications: Current/Checking, Savings/Deposit, Investment/Brokerage, Pension/Retirement, Property, Physical Asset, Credit Card, Loan/Mortgage, Other Liability. There is no higher-level grouping. |
| **Asset account** | An account whose balance increases net worth: Current/Checking, Savings/Deposit, Investment/Brokerage, Pension/Retirement, Property, Physical Asset. |
| **Liability account** | An account whose balance decreases net worth: Credit Card, Loan/Mortgage, Other Liability. |
| **Balance** | The value of an account as at a month-end, entered manually. Balances are never calculated from transactions. |
| **Snapshot** | A single balance figure recorded against one account for one reporting month. |
| **Reporting month** | A calendar month. Its boundary is the last calendar day of that month. All balances are stated as at that date. |
| **Month close** | The act of recording all required balances and rates for a reporting month. A month is either Complete or Incomplete. |
| **Complete month** | A reporting month in which every account that is Open on the month-end date has a balance recorded. |
| **Active account** | An account that is Open on a given month-end date and was opened on or before that date. Only active accounts are required for month completeness. |
| **Account status** | One of three values: **Open** (in use, balance required each month), **Dormant** (in use but not chased; last balance carried forward and shown as stale), **Closed** (excluded from all months after its closure date; history preserved). |
| **Dormant** | A status set manually by the user. The system never assigns dormancy automatically. |
| **Stale balance** | A balance displayed for a month in which it was not entered, carried forward from an earlier month. Always visually distinguished from an entered balance. |
| **Net worth** | The sum of all asset account balances minus the sum of all liability account balances, translated to the reporting currency at the month-end rate, for all accounts Open or Dormant as at that month-end. |
| **Liquidity tier** | One of four fixed tiers assigned manually per account: **Instant** (immediately available), **Short** (available in days to weeks), **Long** (available in months, or requiring disposal), **Locked** (access legally or contractually restricted until a date or event, such as a pension before preservation age). |
| **Base currency** | United States Dollars. The single stored currency of record for net worth. |
| **Reporting currency** | The currency in which figures are displayed. Selectable at any time between USD, AUD and MYR. A display-layer choice only; it never changes stored data. |
| **Account currency** | The single currency in which an account is denominated. Balances are entered in this currency. |
| **Month-end rate** | The exchange rate in effect on the last calendar day of a reporting month, used to translate all balances for that month. |
| **Carry-forward rate** | A rate applied to a date for which no rate was entered, taken from the most recent earlier date that has one. |
| **Rate as-at date** | The date of the rate actually used in a translation, which may be earlier than the date being reported. Always displayed alongside translated figures. |
| **Transaction (cash flow)** | A single recorded item of income or expense, assigned to exactly one category. |
| **Transfer** | Movement of money between two accounts both belonging to the Product Owner. **Transfers are not recorded in this system.** Their effect is visible only as changes in account balances. |
| **Category** | A two-level classification of cash flow. A parent category contains child categories; transactions are assigned to a child. |
| **Recurring transaction** | A cash flow item defined once with an expected amount, category and frequency, presented for confirmation each period rather than typed afresh. |
| **Holding** | An investment instrument owned within an investment account: an individual equity, an ETF, or a mutual fund / unit trust. |
| **Lot** | A single purchase of a holding, with its own date, quantity, price per unit and fees. A holding's position is the sum of its unconsumed lots. |
| **FIFO** | First In, First Out. On a sale, the oldest lots are consumed first. |
| **Cost basis** | The original purchase cost of the units being sold, including purchase fees, drawn from lots in FIFO order. |
| **Realised gain** | Sale proceeds net of sale fees, minus the cost basis of the units sold. Computed only when a sale occurs. Always expressed in the holding's own currency. |
| **Unrealised gain** | The paper gain on units still held. **Not computed in v1**, as no market prices are held. |
| **Estimated tax percentage** | A manually entered percentage held against each holding, applied to realised gains to display an indicative net-of-tax figure. It is a user estimate, not a tax calculation, and reflects no jurisdiction's rules. |
| **Net realised gain** | Realised gain less the estimated tax percentage applied to it. Indicative only. |
| **Dividend reinvestment (DRIP)** | A distribution used to acquire further units of the same holding, recorded as a distribution and a corresponding new lot. |
| **Stock split** | A change in unit quantity without a change in total cost basis, applied proportionally across all open lots. |
| **Interest** | Income earned on cash and savings accounts, including high-interest savings accounts. Recorded in Cash Flow, not in Investments. |

---

## 7. Business Rules

Each rule states the rule, its rationale, and its edge cases.

---

### BR-01 — Balances are entered, never derived

**Rule.** An account balance for a reporting month is a value entered manually by the user. No transaction of any kind — cash flow, investment or otherwise — alters an account balance.

**Rationale.** Derived balances require complete transaction capture in every account or the balance silently drifts wrong. Complete capture was assessed as the principal cause of abandonment for tools of this kind. The entered snapshot is always correct by definition because it is copied from the real account.

**Edge cases.**
- Where a recorded cash flow transaction and a balance movement appear to contradict each other, **the balance is authoritative** and no discrepancy is raised.
- There is no concept of an opening balance, a running balance, or an unexplained difference.
- Because balances are entered rather than derived, no snapshot-versus-derived precedence rule is required. *This rule exists to make that absence explicit and deliberate.*

---

### BR-02 — The reporting period is the calendar month

**Rule.** All balances are stated as at the last calendar day of a calendar month. All reporting periods are calendar months.

**Rationale.** Aligns with the statement cycles of most institutions and is universally understood.

**Edge cases.**
- A balance obtained on a date other than month-end is recorded against that month regardless; the system does not adjust it.
- No part-month or arbitrary-date reporting is supported.

---

### BR-03 — A month is complete only when every active account has a balance

**Rule.** A reporting month is Complete when every account that is Open, and was opened on or before that month-end, has a balance recorded for that month. Otherwise the month is Incomplete, and this status is displayed prominently.

**Rationale.** The user explicitly required completeness enforcement so that no month can be quietly reported on partial data.

**Edge cases.**
- **Dormant** accounts are excluded from the requirement. Their last known balance is carried forward and displayed as stale, and is included in net worth.
- **Closed** accounts are excluded from all months after their closure date.
- Accounts are excluded from months preceding their opening date.
- **Back-dated months are exempt from this rule entirely** (see BR-05).
- An Incomplete month is still viewable and reportable; the block is a visible status, not a prohibition on reading data.

> ⚠ **FLAGGED HIGH RISK.** This rule stands in tension with SC-01 (sustained low-friction use), the primary success criterion. A hard completeness requirement is a recognised cause of abandonment when a month is busy. This is the requirement most likely to be softened to a warning after live use.

---

### BR-04 — Net worth is assets minus liabilities at month-end rates

**Rule.** Net worth for a reporting month equals the sum of all asset account balances minus the sum of all liability account balances, each translated to the reporting currency using the month-end rate for that account's currency, for all accounts Open or Dormant as at that month-end.

**Rationale.** The standard definition, made explicit so every report derives from one statement.

**Edge cases.**
- Dormant accounts are included at their carried-forward balance.
- Closed accounts are excluded from months after closure but remain in historic months.
- Where a month is Incomplete, net worth is computed from the balances present; the figure is displayed with the Incomplete status attached.

---

### BR-05 — History may be back-dated but is never seeded

**Rule.** The system starts with no data. Months earlier than the first live close may be entered later at the user's discretion. Back-dated months are exempt from BR-03.

**Rationale.** The existing spreadsheet holds roughly seven months of lossy data judged not worth migrating, but the option to enter a past month should not be foreclosed.

**Edge cases.**
- A back-dated month with partial data is permanently Incomplete and is labelled as such in all reporting.
- Back-dated months appear in trend charts with the same treatment as any other month.

---

### BR-06 — Liabilities are entered as positive figures; the system applies the sign

**Rule.** Balances for liability accounts are entered as positive numbers. The system subtracts them when computing net worth, based on the account's type.

**Rationale.** Entering a mortgage as `247,500` rather than `-247,500` is materially less error-prone.

**Edge cases.**
- A credit card in credit (the institution owes the user) is entered as a negative figure on a liability account, which correspondingly increases net worth.
- Changing an account's type between asset and liability reverses the sign of its entire history — see BR-07.

---

### BR-07 — Reclassification restates history

**Rule.** An account's type and liquidity tier are properties of the account, not of a point in time. Changing either immediately restates all historic reporting as though the new classification had always applied.

**Rationale.** Effective-dated classification is technically more correct but complicates every report, and genuine reclassification is rare in personal finance.

**Edge cases.**
- Changing type across the asset/liability boundary reverses the sign of that account's contribution in every historic month, changing historic net worth. The system must warn before this is applied.
- No record is kept of the previous classification.

---

### BR-08 — One account holds exactly one currency

**Rule.** Each account is denominated in exactly one currency, fixed at creation. A provider offering multiple currency sub-balances is represented as multiple accounts, distinguished by currency.

**Rationale.** Guarantees that every balance is unambiguous and translatable without apportionment.

**Edge cases.**
- An account's currency cannot be changed after balances exist. Correcting a mistake requires a new account.
- Two accounts at the same institution in different currencies are unrelated records in v1, as institution is not a reporting slice.

---

### BR-09 — Currency translation uses the month-end rate, carried forward if absent

**Rule.** Every balance is translated from its account currency to the reporting currency using the rate in effect on the month-end date. Where no rate was entered for that date, the most recent earlier rate is used, and the **as-at date of the rate actually used is displayed alongside the translated figure**.

**Rationale.** A manually maintained rate table will have gaps. Carrying forward keeps reports functional; displaying the as-at date prevents a stale rate from silently misstating net worth.

**Edge cases.**
- If no rate exists on or before the month-end date for a required currency, the balance cannot be translated. The affected account is excluded from the translated total and the omission is displayed explicitly. The figure is never treated as zero.
- Rates for the base currency against itself are always 1 and are not entered.
- Changing a historic rate restates the historic reports that used it.

> ⚠ **FLAGGED HIGH RISK.** Pure carry-forward means a month-end may be valued at a rate entered weeks earlier, moving reported net worth on stale data. The as-at date display is the mitigation, not a fix.

---

### BR-10 — Base currency is fixed; reporting currency is a display choice

**Rule.** United States Dollars is the base currency and the stored currency of record. Australian Dollars and Malaysian Ringgit are selectable as alternate reporting currencies. Selecting a reporting currency changes display only; it never alters stored data and is reversible at any time.

**Rationale.** One unambiguous source of truth, three views. A switchable true base would make the question "what did net worth do in the month I changed base currency" unanswerable.

**Edge cases.**
- Alternate reporting currencies are computed from the same underlying rate table, at the same month-end dates, with the same carry-forward and as-at display behaviour.
- The reporting currency selection is a user setting and persists between sessions.

---

### BR-11 — Transfers between own accounts are not recorded

**Rule.** Movement of money between two accounts belonging to the Product Owner is not recorded as a transaction of any kind. Its effect is visible solely as a change in the two accounts' balances.

**Rationale.** Because balances are snapshots and cash flow is a parallel ledger, a transfer changes nothing that the system computes. Recording it would create a category of entry with no consumer.

**Edge cases.**
- **Transfers must not be entered as income or expense.** A transfer entered as an expense would overstate spending. The system provides no transfer type to prevent this; the discipline rests with the user.
- A statement line representing a transfer is skipped during cash flow entry. The system therefore has no capability to prove that a statement has been fully accounted for.
- A repayment from a current account to a credit card or loan is a transfer and is not recorded. Its effect appears as both balances moving.

> ⚠ **FLAGGED HIGH RISK.** This rule interacts poorly with per-transaction manual entry (BR-13). At the point of entry, a transfer looks identical to an expense. The absence of a transfer transaction type places the entire burden of correct treatment on the user, every time.

---

### BR-12 — Cash flow is a parallel ledger

**Rule.** Cash flow transactions record income and expense for spending analysis only. They do not affect account balances, net worth, or any investment figure. No report sums cash flow figures together with balance figures.

**Rationale.** Follows directly from BR-01. Keeping the modules decoupled means an incomplete cash flow ledger never corrupts net worth.

**Edge cases.**
- Interest recorded as cash flow income (BR-15) also appears as balance growth in the account snapshot. Because no report combines the two, this is not a double count; it is the same event observed from two independent angles.
- The system cannot explain net worth movement in terms of saving, spending, market movement or currency movement. This is an accepted limitation of the chosen model.

---

### BR-13 — Cash flow is captured per transaction, manually

**Rule.** Each item of income or expense is entered individually, with a date, an amount, a currency and exactly one child category. No merchant or payee field is required. No import path exists in v1.

**Rationale.** The user assessed personal transaction volume as low and largely recurring, making per-transaction capture sustainable.

**Edge cases.**
- **Split transactions are not supported.** A transaction covering several categories is assigned to the dominant category in full.
- Recurring transactions (BR-14) reduce the typing burden for the majority of volume.
- A soft duplicate warning is raised when a new transaction matches an existing one on date, amount and category. The warning never blocks saving.

> ⚠ **FLAGGED HIGH RISK.** This is the highest-friction decision in the specification and directly threatens SC-01. The identified mitigation — CSV import — was placed out of scope for v1, leaving the risk unmitigated within the release.

---

### BR-14 — Recurring transactions are proposed, never posted automatically

**Rule.** A recurring transaction is a template defining an expected amount, category and frequency. Each period, the system presents it for confirmation. It becomes a real transaction only on confirmation, and the amount may be adjusted at that point.

**Rationale.** Preserves the accuracy of a manual ledger while removing most of the typing. Automatic posting would create transactions for payments that did not occur.

**Edge cases.**
- An unconfirmed recurring item creates no transaction and leaves no trace in reporting.
- Changing a template never alters transactions already confirmed from it.
- Ending a recurring item stops future proposals and leaves history intact.

---

### BR-15 — Returns follow the account, not the instrument type

**Rule.** Interest earned on cash and savings accounts, including high-interest savings accounts, is recorded in **Cash Flow** under `Income → Gains → Interest`. Dividends, distributions and realised gains arising on investment holdings are recorded in the **Investments module only** and never appear in cash flow.

**Rationale.** The split is unambiguous at the point of entry: if the return attaches to a holding it belongs to Investments; if it attaches to a cash account it belongs to Cash Flow. A savings account has no holding to attach interest to.

**Edge cases.**
- A cash dividend paid into a brokerage account's cash balance is a return on a holding and is recorded in Investments. It is not cash flow income.
- Interest on a cash balance held inside a brokerage account is a boundary case. **Open issue OI-04.**
- Interest recorded here appears both as cash flow income and as balance growth in the snapshot; see BR-12 edge cases.

---

### BR-16 — Investment holdings are tracked at lot level with FIFO cost basis

**Rule.** Every purchase creates a distinct lot recording date, quantity, price per unit and fees. On a sale, lots are consumed oldest first. Cost basis is drawn from the consumed lots including their purchase fees.

**Rationale.** Lot-level records are the only basis on which a partial sale can be costed meaningfully, and FIFO is deterministic, requires no decision at the point of sale, and matches most brokers' default reporting.

**Edge cases.**
- A sale consuming part of a lot leaves the remainder of that lot open at its original unit cost.
- A sale exceeding the total units held must be rejected.
- Sale fees are deducted from proceeds rather than added to cost basis.

> ⚠ **FLAGGED LIKELY TO CHANGE.** The Product Owner is tax-resident across Australia and Malaysia. Australia permits specific lot identification, and its capital gains discount for assets held over twelve months means the choice of parcel can materially affect tax. Should tax reporting ever come into scope, FIFO would likely be replaced. Lot-level tracking preserves that option.

---

### BR-17 — Realised gain is computed; unrealised gain is not

**Rule.** Realised gain equals sale proceeds net of sale fees, minus the FIFO cost basis of the units sold. It is computed only at the moment of sale. No unrealised gain is computed anywhere in the system.

**Rationale.** No market prices are held in v1, so unrealised gain is not computable. The account's balance snapshot already conveys current value.

**Edge cases.**
- Realised gain may be negative (a realised loss) and is displayed as such.
- The system holds no notion of total return, time-weighted return or money-weighted return.

---

### BR-18 — Investment figures are stated in the holding's own currency

**Rule.** All investment performance figures — cost basis, proceeds, fees, realised gain, net realised gain — are expressed in the currency of the holding and are never translated to the base or reporting currency.

**Rationale.** Translating performance would conflate market movement with currency movement, producing a figure that answers neither question.

**Edge cases.**
- No aggregate realised gain across holdings of different currencies is produced, as it would require translation. Totals are presented per currency.
- The investment *account's balance* is translated for net worth like any other account (BR-04). Performance figures and balance figures are therefore stated on different bases; this is intentional.

---

### BR-19 — Holdings and investment account balances are independent

**Rule.** An investment account's balance snapshot and the holdings recorded within it are independent records. The system enforces no relationship between them, performs no comparison, and raises no discrepancy.

**Rationale.** The snapshot is authoritative for net worth; the holdings are authoritative for cost basis and realised gains. With no market prices, no meaningful comparison is possible.

**Edge cases.**
- A holding may exist with no corresponding balance movement, and vice versa. Neither is an error.
- Recording a buy or a sell does not alter any balance.

---

### BR-20 — Corporate actions are limited to fees, splits and reinvestment

**Rule.** The Investments module supports transaction fees on buys and sells, stock splits and consolidations, and dividend reinvestment. All other corporate actions — mergers, spin-offs, rights issues, returns of capital — are out of scope.

**Rationale.** Fees are unavoidable and form part of cost basis. Splits silently corrupt quantities if unsupported. Reinvestment is common. The remainder are rare, individually complex, and each behaves differently.

**Edge cases.**
- A stock split adjusts the quantity of every open lot proportionally and leaves each lot's total cost basis unchanged; unit cost changes accordingly.
- A dividend reinvestment is recorded as a distribution against the holding plus a new lot at the reinvestment price, dated to the reinvestment.
- An unsupported corporate action must be represented manually by the user as a sale and a purchase. The system offers no guidance on this and the resulting figures will not reflect the true event.

---

### BR-21 — Estimated tax is a user-supplied percentage, not a calculation

**Rule.** Each holding carries a manually entered estimated tax percentage. Applied to a realised gain, it produces an indicative net realised gain. The system applies no jurisdiction rules, holding-period rules, allowances or thresholds.

**Rationale.** The Product Owner requires a net-of-gains view without bringing tax computation into scope. A user-supplied percentage keeps every tax judgement with the user.

**Edge cases.**
- Where no percentage is set, net realised gain equals gross realised gain and is displayed as having no estimate applied.
- Changing a holding's percentage restates the net figure on all its historic sales, including sales already reported.
- The percentage is not applied to realised losses. **Open issue OI-05.**
- All net-of-tax figures must be labelled as indicative estimates on every screen and export where they appear.

---

### BR-22 — Categories are seeded, editable, and never deleted once used

**Rule.** The system is seeded with the agreed two-level taxonomy in Title Case. The user may add, rename and deactivate categories. A category that has been used by any transaction may be deactivated but never deleted.

**Rationale.** Immediate usability without designing a taxonomy on day one, with no risk of orphaning historic transactions.

**Edge cases.**
- A deactivated category remains visible in historic reporting and is unavailable for new transactions.
- Renaming a category restates its label across all history; no record of the former name is kept.
- Every transaction is assigned to a child category. Parent categories exist for rollup only and are not directly selectable.

**Seeded taxonomy:**

| Parent | Children |
|---|---|
| Income → Employment | Salary, Bonus |
| Income → Gains | Interest, Dividends, Realised Investment Gains |
| Income → Other | Gifts, Refunds, Miscellaneous |
| Expenses → Housing | Rent, Mortgage Payment, Council Tax, Maintenance |
| Expenses → Utilities | Energy, Water, Internet, Mobile |
| Expenses → Subscriptions | Media, Software, Memberships |
| Expenses → Food | Groceries, Eating Out |
| Expenses → Shopping | Clothing, Household, Electronics |
| Expenses → Travel | Transport, Holidays |
| Expenses → Entertainment | Events, Hobbies |
| Expenses → Health | Medical, Fitness, Insurance |
| Expenses → Other | Miscellaneous |

> **Note on `Income → Gains`.** This parent is retained to accommodate interest on cash and savings accounts (BR-15). Its `Dividends` and `Realised Investment Gains` children are seeded but **must not be used for returns on investment holdings**, which belong exclusively to the Investments module. **Open issue OI-06** proposes removing them.

---

### BR-23 — All history is editable

**Rule.** Any balance, transaction, rate, lot or classification may be edited or deleted at any time, in any period. No month is locked, no reopening step exists, and no audit record of changes is kept.

**Rationale.** Single user, no external audit obligation, greenfield start. Corrections will be frequent in the first year and friction here would be actively harmful.

**Edge cases.**
- Editing a historic balance or rate silently restates every report that used it, including figures already viewed.
- Deleting the last balance for an account in a month reverts that month to Incomplete.
- There is no undo and no recovery of a deleted record from within the application. Recovery depends entirely on the external database backup (DEP-02).

---

### BR-24 — Dates are calendar dates in a single fixed timezone

**Rule.** All dates in the system — month-ends, transaction dates, rate dates, opening and closure dates — are plain calendar dates with no time component, interpreted in a single timezone set once in settings.

**Rationale.** The Product Owner operates across two timezones roughly three hours apart. Device-local timestamps would place an entry made late at night in Kuala Lumpur on a different calendar day from one made in Sydney.

**Edge cases.**
- The system never displays or stores a time of day for any financial record.
- Changing the configured timezone does not restate any stored date.

---

## 8. Functional Requirements

MoSCoW priorities follow the agreed posture: **Must** = required to close a month and see the net worth trend; **Should** = cash flow and investments core; **Could** = dashboard polish, rate trend chart, export.

---

### 8.1 Module 1 — Net Worth

---

**FR-01 — Create an account**
*Priority: Must*

The user can create an account, specifying name, account type, currency, liquidity tier, and opening date.

> **Given** the user is on the accounts administration screen
> **When** they create an account with a name, type, currency, liquidity tier and opening date
> **Then** the account is saved with status Open and appears in the Month Close list for all months from its opening date onward

---

**FR-02 — Classify an account by type**
*Priority: Must*

The user can assign exactly one of the nine account types to each account.

> **Given** the user is creating or editing an account
> **When** they select an account type
> **Then** the account is treated as an asset or a liability according to that type, and its sign in net worth follows BR-06

---

**FR-03 — Assign a liquidity tier**
*Priority: Must*

The user can assign exactly one of the four liquidity tiers — Instant, Short, Long, Locked — to each account.

> **Given** an account exists
> **When** the user assigns it a liquidity tier
> **Then** its balance is included in that tier in all liquidity reporting, for all periods including historic ones

---

**FR-04 — Change an account's classification with warning**
*Priority: Must*

The user can change an account's type or liquidity tier, and is warned when the change restates historic net worth.

> **Given** an account of an asset type has recorded balances
> **When** the user changes its type to a liability type
> **Then** the system warns that historic net worth will be restated, and applies the change only on confirmation

---

**FR-05 — Set an account to Dormant**
*Priority: Must*

The user can manually set an account's status to Dormant.

> **Given** an Open account with a recorded balance
> **When** the user sets it to Dormant
> **Then** it is no longer required for month completeness, its last balance is carried forward into subsequent months marked as stale, and it remains included in net worth

---

**FR-06 — Close an account**
*Priority: Must*

The user can close an account by setting a closure date.

> **Given** an account with recorded history
> **When** the user closes it with a closure date
> **Then** it is excluded from all months after that date, its historic balances remain unchanged, and it no longer appears in the Month Close list

---

**FR-07 — Record a monthly balance snapshot**
*Priority: Must*

The user can record one balance figure per account per reporting month, in the account's own currency.

> **Given** an active account for a reporting month
> **When** the user enters a balance figure
> **Then** the figure is stored against that account and month, and net worth for that month is recomputed

---

**FR-08 — Complete a month close from a single screen**
*Priority: Must*

The system provides one guided Month Close screen listing every active account for the selected month, each showing the previous month's balance alongside an input for the current month, together with the exchange rates required for that month.

> **Given** the user opens Month Close for a reporting month
> **When** the screen loads
> **Then** every active account is listed with its prior balance visible, an input for the current balance, and any missing rate for a currency in use is indicated

---

**FR-09 — Display month completeness status**
*Priority: Must*

The system shows whether a reporting month is Complete or Incomplete, and identifies which accounts are outstanding.

> **Given** a reporting month in which one or more active accounts lack a balance
> **When** the user views Month Close or the dashboard
> **Then** the month is shown as Incomplete and the specific outstanding accounts are listed

---

**FR-10 — Carry forward dormant balances as stale**
*Priority: Must*

The system carries a Dormant account's last recorded balance into subsequent months, visually distinguishing it from an entered balance.

> **Given** a Dormant account whose last balance was recorded three months ago
> **When** the user views the current month's net worth
> **Then** the account is included at that balance and is visually marked as stale

---

**FR-11 — Enter a back-dated month**
*Priority: Should*

The user can record balances for a reporting month earlier than the first live close.

> **Given** the user selects a month preceding the first live close
> **When** they enter balances for some or all accounts
> **Then** the balances are saved, the month appears in trend reporting, and it is exempt from the completeness rule while being labelled as partial

---

**FR-12 — View the net worth trend**
*Priority: Must*

The system displays total net worth over time as a time series, defaulting to a rolling twelve months.

> **Given** at least two months of recorded balances
> **When** the user opens the net worth trend
> **Then** total net worth is plotted by month for the last twelve months in the selected reporting currency

---

**FR-13 — Display month-on-month change**
*Priority: Must*

The net worth trend shows the change from the previous month in both currency amount and percentage.

> **Given** two consecutive months with recorded balances
> **When** the user views the trend
> **Then** the change between them is displayed as both an absolute amount and a percentage

---

**FR-14 — Select a date range**
*Priority: Should*

The user can change the period shown in any time-series report.

> **Given** the user is viewing a time-series report
> **When** they select a different date range
> **Then** the report redraws for that range without altering any stored data

---

**FR-15 — Slice net worth by account type**
*Priority: Must*

The system breaks net worth down across the nine account types.

> **Given** accounts of several types with recorded balances
> **When** the user selects the account type slice
> **Then** net worth is broken down by type for the selected period

---

**FR-16 — Slice net worth by liquidity tier**
*Priority: Must*

The system breaks net worth down across the four liquidity tiers.

> **Given** accounts assigned to several liquidity tiers
> **When** the user selects the liquidity slice
> **Then** net worth is broken down across Instant, Short, Long and Locked

---

**FR-17 — Slice net worth by currency**
*Priority: Must*

The system breaks net worth down by account currency, translated into the reporting currency.

> **Given** accounts denominated in more than one currency
> **When** the user selects the currency slice
> **Then** net worth is broken down by account currency, with each figure translated to the reporting currency

---

**FR-18 — Slice net worth by individual account**
*Priority: Must*

The system shows the contribution of each individual account to net worth.

> **Given** a reporting month with recorded balances
> **When** the user selects the account slice
> **Then** each account's contribution is listed for that month

---

**FR-19 — View a single account's balance history**
*Priority: Must*

The system displays the balance history and trend of a single selected account. *This requirement directly serves the driving question (OBJ-02).*

> **Given** an account with balances recorded across several months
> **When** the user opens that account's detail screen
> **Then** its balance history is displayed as a time series in the account's own currency, with month-on-month change

---

**FR-20 — View a point-in-time net worth position**
*Priority: Must*

The system displays the full net worth position for a single selected month.

> **Given** a reporting month with recorded balances
> **When** the user selects that month
> **Then** total net worth and its breakdown by the available slices are displayed for that month alone

---

**FR-21 — Toggle the slice dimension on a chart**
*Priority: Should*

The user can switch the dimension by which a net worth chart is broken down, and show or hide individual series.

> **Given** the user is viewing a net worth breakdown chart
> **When** they select a different slice dimension
> **Then** the chart redraws using that dimension without page reload or data change

---

### 8.2 Module 2 — Cash Flow

---

**FR-22 — Record a cash flow transaction**
*Priority: Should*

The user can record a single income or expense transaction with a date, amount, currency and one child category.

> **Given** the user is on the cash flow entry screen
> **When** they enter a date, amount, currency and child category and save
> **Then** the transaction is stored and appears in that month's cash flow reporting, and no account balance changes

---

**FR-23 — Warn on a probable duplicate**
*Priority: Should*

The system raises a non-blocking warning when a new transaction matches an existing one on date, amount and category.

> **Given** a transaction already exists for a given date, amount and category
> **When** the user enters a second transaction matching all three
> **Then** a warning is displayed and the user may save anyway

---

**FR-24 — Maintain the category taxonomy**
*Priority: Should*

The user can add, rename and deactivate categories at both levels.

> **Given** the user is on the categories administration screen
> **When** they add a child category under an existing parent
> **Then** it becomes available for selection on new transactions

---

**FR-25 — Prevent deletion of a used category**
*Priority: Should*

The system permits deactivation but prevents deletion of any category referenced by a transaction.

> **Given** a category used by at least one transaction
> **When** the user attempts to delete it
> **Then** deletion is refused and deactivation is offered instead

---

**FR-26 — Define a recurring transaction**
*Priority: Should*

The user can define a recurring transaction template with an expected amount, category and frequency.

> **Given** the user defines a monthly recurring transaction
> **When** the template is saved
> **Then** it is proposed for confirmation in each subsequent period and creates no transaction until confirmed

---

**FR-27 — Confirm a recurring transaction**
*Priority: Should*

The user can confirm a proposed recurring transaction, adjusting the amount before it is created.

> **Given** a recurring transaction is proposed for the current period
> **When** the user adjusts the amount and confirms
> **Then** a transaction is created at the adjusted amount and the template is unchanged

---

**FR-28 — Report cash flow by category for a month**
*Priority: Should*

The system reports total income and total expense by category, at both parent and child level, for a selected month.

> **Given** transactions recorded across several categories in a month
> **When** the user views the monthly cash flow report
> **Then** totals are shown by child category and rolled up by parent, with income and expense separated

---

**FR-29 — Report cash flow trend over time**
*Priority: Could*

The system reports category totals across multiple months.

> **Given** transactions recorded across several months
> **When** the user views the cash flow trend
> **Then** category totals are plotted by month for the selected date range

---

### 8.3 Module 3 — Investments

---

**FR-30 — Create a holding**
*Priority: Should*

The user can create a holding within an investment account, specifying name, instrument type and currency.

> **Given** an investment account exists
> **When** the user creates a holding with a name, instrument type and currency
> **Then** the holding is available for buy and sell transactions, and all its figures are expressed in that currency

---

**FR-31 — Record a purchase as a lot**
*Priority: Should*

The user can record a purchase, creating a lot with date, quantity, price per unit and fees.

> **Given** a holding exists
> **When** the user records a purchase with quantity, unit price, date and fees
> **Then** a new lot is created and the holding's total position increases by that quantity

---

**FR-32 — Record a sale consuming lots by FIFO**
*Priority: Should*

The user can record a sale, which consumes open lots oldest first.

> **Given** a holding with three open lots purchased on different dates
> **When** the user sells a quantity spanning the first two lots
> **Then** the first lot is fully consumed, the second is partially consumed, the third is untouched, and cost basis is drawn from the consumed portions

---

**FR-33 — Reject a sale exceeding units held**
*Priority: Should*

The system prevents a sale of more units than are currently held.

> **Given** a holding with 100 units across open lots
> **When** the user attempts to sell 150 units
> **Then** the sale is rejected with an explanatory message and no records are altered

---

**FR-34 — Compute realised gain on a sale**
*Priority: Should*

The system computes realised gain as proceeds net of sale fees minus the FIFO cost basis of the units sold.

> **Given** a sale has been recorded against lots with a known cost basis
> **When** the user views the sale
> **Then** realised gain is displayed in the holding's own currency and may be positive or negative

---

**FR-35 — Record transaction fees**
*Priority: Should*

The user can record fees on both purchases and sales.

> **Given** the user is recording a purchase or sale
> **When** they enter a fee amount
> **Then** purchase fees are included in cost basis and sale fees are deducted from proceeds

---

**FR-36 — Apply a stock split**
*Priority: Should*

The user can record a stock split or consolidation, adjusting all open lots proportionally.

> **Given** a holding with several open lots
> **When** the user records a two-for-one split
> **Then** the quantity of every open lot doubles, each lot's total cost basis is unchanged, and unit cost halves

---

**FR-37 — Record a dividend reinvestment**
*Priority: Should*

The user can record a distribution that is reinvested into further units of the same holding.

> **Given** a holding pays a distribution that is reinvested
> **When** the user records the reinvestment with a date, amount and unit price
> **Then** the distribution is recorded against the holding and a new lot is created at that price and date

---

**FR-38 — Record a cash distribution**
*Priority: Should*

The user can record a distribution taken as cash rather than reinvested.

> **Given** a holding pays a cash distribution
> **When** the user records it
> **Then** it is recorded against the holding in the Investments module and does not appear in cash flow

---

**FR-39 — Set an estimated tax percentage per holding**
*Priority: Should*

The user can record an estimated tax percentage against each holding.

> **Given** a holding exists
> **When** the user enters an estimated tax percentage
> **Then** it is stored against the holding and applied to that holding's realised gains

---

**FR-40 — Display net realised gain**
*Priority: Should*

The system displays realised gain net of the holding's estimated tax percentage, clearly labelled as indicative.

> **Given** a realised gain and an estimated tax percentage on the same holding
> **When** the user views the realised gains report
> **Then** gross gain, the percentage applied, and net gain are all displayed, with net gain labelled as an indicative estimate

---

**FR-41 — Report realised gains by currency**
*Priority: Should*

The system reports realised gains grouped by holding currency, without translating between currencies.

> **Given** realised gains on holdings denominated in more than one currency
> **When** the user views the realised gains report
> **Then** totals are presented separately per currency and no combined total is shown

---

**FR-42 — View current holdings and open lots**
*Priority: Should*

The system lists current holdings with their quantity and cost basis, and the open lots comprising each.

> **Given** holdings with open lots
> **When** the user views the holdings screen
> **Then** each holding shows its total quantity and total cost basis in its own currency, expandable to its constituent open lots

---

### 8.4 Module 4 — FX Rates

---

**FR-43 — Record a daily exchange rate**
*Priority: Must*

The user can record an exchange rate for a currency pair on a specific date.

> **Given** the user is on the rate table screen
> **When** they enter a rate for a currency pair on a date
> **Then** the rate is stored and used for translations on that date

---

**FR-44 — Carry forward the most recent rate**
*Priority: Must*

Where no rate exists for a required date, the system uses the most recent earlier rate.

> **Given** a rate was entered on the 20th and none since
> **When** a translation is required for the 31st
> **Then** the rate from the 20th is applied

---

**FR-45 — Display the rate as-at date**
*Priority: Must*

Wherever a translated figure is displayed, the system shows the date of the rate actually used.

> **Given** a net worth figure translated using a carried-forward rate
> **When** the user views that figure
> **Then** the as-at date of the rate is displayed alongside it

---

**FR-46 — Handle an entirely missing rate**
*Priority: Must*

Where no rate exists on or before the required date for a currency in use, the system excludes the affected accounts and states the omission.

> **Given** an account in a currency with no rate recorded at any date
> **When** the user views net worth for that month
> **Then** that account is excluded from the translated total and the exclusion is stated explicitly, and its balance is not treated as zero

---

**FR-47 — Select the reporting currency**
*Priority: Must*

The user can switch the reporting currency between USD, AUD and MYR at any time.

> **Given** the user is viewing any report
> **When** they change the reporting currency
> **Then** all displayed figures are re-translated and no stored data changes

---

**FR-48 — View the exchange rate trend**
*Priority: Could*

The system plots recorded exchange rates over time for a selected currency pair.

> **Given** rates recorded across several dates for a currency pair
> **When** the user views the rate trend chart
> **Then** the rates are plotted over the selected date range

---

### 8.5 Cross-cutting

---

**FR-49 — Authenticate the user**
*Priority: Must*

The system requires a single password before any financial data is accessible.

> **Given** an unauthenticated visitor reaches the application
> **When** they attempt to view any screen other than login
> **Then** they are directed to log in and no financial data is displayed

---

**FR-50 — Display the dashboard**
*Priority: Could*

The system provides a landing dashboard with fixed panels covering net worth, cash flow, investments and outstanding tasks.

> **Given** the user logs in
> **When** the dashboard loads
> **Then** net worth panels are displayed first, followed by cash flow and investment panels, followed by the outstanding-tasks panel, in a fixed layout

---

**FR-51 — Display outstanding tasks**
*Priority: Should*

The dashboard shows what is blocking completion of the current month.

> **Given** the current month has three accounts without balances and one currency with a stale rate
> **When** the user views the dashboard
> **Then** both conditions are listed in the outstanding-tasks panel with a link to the relevant screen

---

**FR-52 — Export a report to CSV**
*Priority: Could*

The user can export any displayed table or report to CSV.

> **Given** the user is viewing any table or report
> **When** they select export
> **Then** a CSV file of the displayed data is produced, reflecting the current reporting currency and date range

---

**FR-53 — Edit or delete any record**
*Priority: Must*

The user can edit or delete any balance, transaction, rate, lot or account at any time.

> **Given** any stored record in any period
> **When** the user edits or deletes it
> **Then** the change is applied immediately and all dependent reporting is recomputed

---

**FR-54 — Read reports on a tablet or phone**
*Priority: Could*

Reporting screens remain legible and usable on tablet and phone viewports.

> **Given** the user opens the application on a phone
> **When** they view the net worth trend
> **Then** the layout adapts and remains legible, though data entry remains optimised for desktop

---

**FR-55 — Set the application timezone**
*Priority: Must*

The user can set a single timezone in settings, applied to all date interpretation.

> **Given** the user is in settings
> **When** they select a timezone
> **Then** all date interpretation uses that timezone and no stored date is altered

---

## 9. Data Requirements

### 9.1 Key business entities

**Account.** A single holding of value or obligation. Attributes: name; account type (one of nine); currency (one, fixed at creation); liquidity tier (one of four); status (Open, Dormant, Closed); opening date; closure date where applicable. An account has many Balances. An account may contain many Holdings, but only if it is of type Investment/Brokerage.

**Balance.** A single value for one account as at one month-end. Attributes: account; reporting month; amount in the account's currency. Exactly one balance may exist per account per month. Balances are entered, never computed.

**Reporting Month.** A calendar month with a completeness status derived from whether every active account has a balance. Attributes: year and month; completeness status; whether it is a back-dated month.

**Category.** A node in the two-level cash flow taxonomy. Attributes: name (Title Case); level (parent or child); parent where applicable; active flag. Transactions attach only to child categories.

**Transaction.** A single item of income or expense. Attributes: date; amount; currency; child category; optional free-text note. Transactions attach to no account and affect no balance.

**Recurring Transaction Template.** A definition from which transactions are proposed. Attributes: expected amount; currency; child category; frequency; start date; end date where applicable; active flag. A template has many confirmed Transactions, but a Transaction, once created, is independent of its template.

**Holding.** An investment instrument within an investment account. Attributes: name; instrument type (equity, ETF, or mutual fund / unit trust); currency; estimated tax percentage. A holding has many Lots and many Investment Transactions.

**Lot.** A single purchase of a holding, with a remaining quantity that decreases as sales consume it. Attributes: holding; purchase date; original quantity; remaining quantity; price per unit; purchase fees.

**Investment Transaction.** A buy, sell, distribution, reinvestment or split against a holding. Attributes: holding; type; date; quantity where applicable; price per unit where applicable; fees where applicable; amount where applicable. A sale additionally carries its computed cost basis and realised gain, both in the holding's currency.

**Exchange Rate.** A rate for one currency pair on one date. Attributes: from currency; to currency; date; rate. At most one rate per pair per date.

**Setting.** Application-level configuration. Attributes: base currency (fixed at USD); selected reporting currency; timezone.

### 9.2 Key relationships in business language

- An account holds many monthly balances; each balance belongs to exactly one account and one month.
- An investment account contains many holdings; a holding belongs to exactly one investment account.
- A holding is composed of many lots; a sale consumes lots in purchase-date order.
- A transaction belongs to exactly one child category; a child category belongs to exactly one parent.
- **No relationship exists between transactions and accounts.** This is deliberate and follows from the parallel-ledger rule (BR-12). See **Open issue OI-03**.
- **No relationship exists between holdings and balances.** Also deliberate (BR-19).
- Exchange rates are referenced by every translated figure but are owned by no other entity.

### 9.3 Data lifecycle

| Stage | Behaviour |
|---|---|
| Creation | All data is created manually by the sole user. No import, no feed, no seeding of financial data. Categories alone are seeded at first run. |
| Amendment | All records are editable indefinitely. Amendments restate dependent reporting immediately and silently. |
| Deletion | All records are deletable. Categories referenced by transactions may only be deactivated. There is no undo and no in-application recovery. |
| Archiving | None. No data is archived, summarised or moved. |
| Retention | Indefinite. No record is ever purged. |
| Recovery | Entirely external, via the database backup regime (DEP-02). |

### 9.4 Volume expectations

Based on sizing Assumption A6: approximately 20 accounts and approximately 100 cash flow transactions per month. Over ten years this yields roughly 2,400 balances, 12,000 transactions, a few thousand exchange rates and a few hundred lots — in the order of 15,000 to 20,000 records in total. This is a small dataset by any measure and no volume-driven design constraint arises.

---

## 10. Reporting Requirements

| ID | Report / view | Purpose | Dimensions | Measures |
|---|---|---|---|---|
| REP-01 | **Net worth trend** *(landing report)* | Answer whether total wealth is growing | Reporting month | Total net worth; month-on-month change in amount and percentage |
| REP-02 | **Net worth by account type** | Show where wealth sits | Reporting month; account type (nine values) | Net worth contribution per type |
| REP-03 | **Net worth by liquidity tier** | Show how accessible wealth is | Reporting month; liquidity tier (Instant, Short, Long, Locked) | Net worth contribution per tier |
| REP-04 | **Net worth by currency** | Show currency exposure | Reporting month; account currency | Net worth contribution per currency, translated to reporting currency |
| REP-05 | **Net worth by account** | Show each account's contribution | Reporting month; account | Balance translated to reporting currency |
| REP-06 | **Account balance history** *(serves OBJ-02)* | Answer the driving question for one account | Reporting month; single account | Balance in account currency; month-on-month change in amount and percentage |
| REP-07 | **Point-in-time position** | Show the full picture for one month | Single reporting month; all slices | Total net worth; breakdown by each slice |
| REP-08 | **Month close status** | Show what blocks completion | Reporting month; account; currency | Count and identity of accounts without balances; currencies with stale or missing rates |
| REP-09 | **Cash flow by category — monthly** | Show where money went in a month | Single reporting month; parent and child category | Total income; total expense; net |
| REP-10 | **Cash flow trend** | Show spending patterns over time | Reporting month; category | Category totals per month |
| REP-11 | **Current holdings** | Show what is owned and what it cost | Holding; instrument type; currency | Total quantity; total cost basis in holding currency |
| REP-12 | **Open lots by holding** | Show the FIFO queue | Holding; lot purchase date | Remaining quantity; unit cost; total remaining cost basis |
| REP-13 | **Realised gains** | Show investment outcomes after tax estimate | Sale date; holding; holding currency | Proceeds; fees; cost basis; gross realised gain; estimated tax percentage; net realised gain — grouped per currency, never combined |
| REP-14 | **Exchange rate trend** | Show how rates have moved | Date; currency pair | Rate |
| REP-15 | **Dashboard** | Single entry point across all modules | Fixed panels | Net worth summary and trend; cash flow summary; investments summary; outstanding tasks (positioned below net worth panels) |

**Applying to all reports:** the selected reporting currency governs every translated figure; the rate as-at date is displayed wherever translation has occurred; date-range selection is available on every time-series report; and any report may be exported to CSV (FR-52, priority Could). Investment reports (REP-11 to REP-13) are stated in each holding's own currency and are never translated.

---

## 11. Non-Functional Requirements

**NFR-01 — Authentication.** The system requires a single password to access any financial data, with session-based access thereafter. *Priority: Must.*

**NFR-02 — Network exposure.** The system is not internet-facing and operates on the local machine or local network only. *Priority: Must.*

**NFR-03 — Performance.** Any report renders within two seconds at the volume described in section 9.4, on the target hardware. *Priority: Should.*

**NFR-04 — Retention.** All data is retained indefinitely. No archiving, summarisation or purging occurs. *Priority: Must.*

**NFR-05 — Encryption at rest.** Not required. The system stores financial data unencrypted on a local machine under the user's physical control. *Priority: Won't (v1).*

**NFR-06 — Audit trail.** Not required. The system keeps no record of what was changed, when, or from what previous value. *Priority: Won't (v1).*

**NFR-07 — Backup and restore.** Not an application responsibility. Backup is handled externally at the database layer. The system provides no backup, restore or full-data-export capability beyond per-report CSV export. *Priority: Won't (v1).* **See RISK-02.**

**NFR-08 — Browser support.** The system functions on current versions of Chrome, Edge, Firefox and Safari. *Priority: Must.*

**NFR-09 — Device support.** Data entry is optimised for desktop. All reporting screens remain legible and usable on tablet and phone viewports. Entry on small viewports is not required to be optimised. *Priority: Could.*

**NFR-10 — Timezone.** A single timezone is configured once in settings. All dates are calendar dates without a time component. *Priority: Must.*

**NFR-11 — Usability under the friction constraint.** A complete month close — all balances, all required rates, and the month's transactions — is achievable in a single sitting. Any change that materially increases recurring monthly effort must be justified against SC-01. *Priority: Must.*

**NFR-12 — Data portability.** The user can extract any report or table as CSV, ensuring data is not trapped within the application. *Priority: Could.* **Note:** given NFR-07, this is the only application-level route to data extraction.

**NFR-13 — Single-user operation.** The system supports exactly one user with no concurrency requirement. The business model should not preclude a second user in future, but no multi-user capability is built or tested. *Priority: Must.*

**NFR-14 — Transparency of derived figures.** Wherever a displayed figure depends on a carried-forward balance or a carried-forward rate, that dependency is visible to the user. *Priority: Must.*

---

## 12. Assumptions, Constraints and Dependencies

### 12.1 Assumptions

| ID | Assumption | Status |
|---|---|---|
| A1 | Formal reconciliation against real statements is a nice-to-have, not a v1 requirement. | Confirmed |
| A2 | One account holds exactly one currency; multi-currency providers are modelled as separate accounts. | Confirmed |
| A3 | Net worth = assets minus liabilities at month-end rates, for accounts Open or Dormant, including dormant accounts at their last known balance. | Confirmed |
| A4 | The seeded two-level category taxonomy as set out in BR-22, Title Case, with Housing split into Rent and Mortgage Payment. | Confirmed |
| A5 | Interest on cash and savings accounts is recorded in cash flow; investment returns are not. `Income → Gains` is retained. | Confirmed (initial proposal rejected and revised) |
| A6 | Volume of approximately 20 accounts and approximately 100 transactions per month is an order-of-magnitude sizing estimate, not a counted figure. | **Unconfirmed** |
| A7 | The sequence net worth → cash flow → investments → dashboard survives as internal build order only, not as delivery milestones. | **Unconfirmed** |
| A8 | With no deadline, MoSCoW priorities are the sole scope-control mechanism; Could items may be dropped without renegotiating scope. | **Unconfirmed** |
| A9 | The currencies in use are USD, AUD and MYR. No other currency has been identified as held. | **Unconfirmed — see OI-01** |
| A10 | The Product Owner has continuous access to the underlying account balances from institutions' own applications, and needs no assistance obtaining them. | **Unconfirmed** |
| A11 | Investment account balance snapshots obtained from a broker already reflect market value, making the absence of price data acceptable. | **Unconfirmed** |

### 12.2 Constraints

| ID | Constraint |
|---|---|
| CON-01 | React front end, Django back end, running as Docker containers on the Product Owner's local PC. |
| CON-02 | Recharts is the Product Owner's preferred charting library. **Recorded as an unconfirmed preference, not a requirement.** |
| CON-03 | Single developer, who is also the sole user and sole stakeholder. |
| CON-04 | No internet-facing deployment. |
| CON-05 | No external data feeds of any kind: no price feeds, no rate feeds, no institution connections. |
| CON-06 | All data originates from manual entry. |
| CON-07 | The system starts empty. No migration of the existing spreadsheet is undertaken. |

### 12.3 Dependencies

| ID | Dependency | Impact if unmet |
|---|---|---|
| DEP-01 | The Product Owner obtains accurate month-end balances from each institution each month. | Month cannot be closed; BR-03 blocks completeness. |
| DEP-02 | An external, automated database backup regime exists and is verified. | Total loss of hand-entered data with no in-application recovery. **See RISK-02.** |
| DEP-03 | The Product Owner sources exchange rates from an external site or application to enter manually. | Balances in foreign currencies cannot be translated; FR-46 exclusion applies. |
| DEP-04 | The Product Owner sources holding prices and corporate action details from broker statements. | Lots and splits cannot be recorded accurately. |

---

## 13. Risks and Open Issues

### 13.1 Risks

| ID | Risk | Impact | Likelihood | Owner | Mitigation |
|---|---|---|---|---|---|
| RISK-01 | **Per-transaction manual cash flow entry proves too onerous and the module is abandoned**, taking OBJ-03 with it and undermining SC-01. | High | High | Product Owner | Recurring transactions (FR-26, FR-27) absorb most volume. Bring CSV import forward from Phase 2 at the first sign of slippage. Accept a partial cash flow ledger — because of BR-12, it corrupts nothing else. |
| RISK-02 | **No in-application backup, restore or full export.** Years of hand-typed data depend entirely on an external regime outside the system's control and visibility. | Severe | Medium | Product Owner | Verify DEP-02 by performing an actual restore before the first live close. Consider promoting a full-data export from Could to Must. |
| RISK-03 | **The hard completeness block (BR-03) causes abandonment** during a busy month, in direct tension with SC-01. | High | Medium | Product Owner | Design the block as a visible status rather than a functional prohibition. Reassess after three live closes; softening to a warning is anticipated. |
| RISK-04 | **Transfers entered as expenses (BR-11).** With no transfer type and no guard, a single mis-entry overstates spending, and nothing in the system detects it. | Medium | High | Product Owner | Reconsider introducing a Transfer transaction type excluded from all totals. This was offered during the interview and declined. |
| RISK-05 | **A stale carried-forward rate silently moves net worth (BR-09).** A month-end may be valued at a rate weeks old. | Medium | Medium | Product Owner | The as-at date display (FR-45) makes staleness visible but does not prevent it. Consider a warning when a rate exceeds a configurable age. |
| RISK-06 | **The full multi-panel dashboard (FR-50) is built before usage reveals what is actually looked at**, making it the most expensive screen and the most likely to be rebuilt. | Medium | High | Product Owner | Fixed layout, no configurability. Priority is Could, so it may be dropped from the release under A8. |
| RISK-07 | **FIFO proves wrong if tax reporting ever comes into scope**, particularly given Australian CGT rules and dual residence. | Medium | Medium | Product Owner | Lot-level tracking (BR-16) preserves the option to add specific identification without restructuring. |
| RISK-08 | **Single-release delivery of four modules with no deadline drifts indefinitely**, with no intermediate milestone to force completion. | Medium | Medium | Product Owner | MoSCoW priorities are the only control (A8). Consider an internal checkpoint when net worth alone is usable. |
| RISK-09 | **The system cannot explain net worth movement**, only report it. Should the underlying question shift from "is it growing" to "why is it growing", the data model does not support an answer. | Medium | Medium | Product Owner | Accepted for v1. The Phase 2 informational comparison of net worth movement against recorded cash flow is the first step toward addressing it. |
| RISK-10 | **The estimated tax percentage is trusted as a real figure.** An indicative number displayed alongside precise ones tends to acquire unearned authority. | Low | Medium | Product Owner | Label as indicative on every screen and export (BR-21, FR-40). Never aggregate into anything resembling a tax return. |

### 13.2 Open issues

| ID | Issue | Owner | Proposed resolution |
|---|---|---|---|
| OI-01 | **Which currencies are actually held?** USD, AUD and MYR are known reporting currencies, but the full set of account currencies was never enumerated. | Product Owner | Enumerate before building the rate table; each additional currency adds a rate to maintain per BR-09. |
| OI-02 | **Confirm assumptions A6, A7, A8, A9, A10 and A11.** | Product Owner | Confirm or correct at first review of this document. |
| OI-03 | **Do cash flow transactions record which account they relate to?** Not required by any rule, since balances are snapshots and transfers are unrecorded — but its absence permanently prevents any future per-account cash flow analysis. | Product Owner | Recommend capturing an optional account reference now. It costs nothing and cannot be added retrospectively to historic data. |
| OI-04 | **Where does interest on a cash balance inside a brokerage account belong?** BR-15 splits by account, but this case sits on the boundary. | Product Owner | Recommend treating it as cash flow interest, consistent with it being a cash return with no holding attached. |
| OI-05 | **Is the estimated tax percentage applied to realised losses?** Applying it would imply a tax benefit the system cannot substantiate. | Product Owner | Recommend applying it only to gains; display losses gross. |
| OI-06 | **Should `Dividends` and `Realised Investment Gains` be removed from the seeded taxonomy?** They are seeded under `Income → Gains` but must never be used, since BR-15 assigns those returns to Investments. Retaining unusable categories invites the double-entry the rule exists to prevent. | Product Owner | Recommend removing both, retaining `Interest` alone under `Income → Gains`. |
| OI-07 | **What is the acceptance event for the release?** Done is defined as acceptance criteria passed plus one full month closed in live use — but under single-release delivery this applies to all four modules simultaneously, making the first live close the acceptance event for the entire system. | Product Owner | Confirm this reading, or nominate per-module acceptance despite single-release delivery. |
| OI-08 | **What is the configured timezone value?** BR-24 requires one; it was never nominated. | Product Owner | Nominate at first configuration. |
| OI-09 | **How are recurring transactions proposed for a period the user skips?** Behaviour when a period passes unconfirmed was never defined. | Product Owner | Recommend proposals remain outstanding until confirmed or explicitly dismissed. |
| OI-10 | **Is there a minimum viable subset if Could items are dropped?** Under A8, dropping the dashboard, rate trend chart and CSV export is permitted — but CSV export is also the sole data-extraction route under NFR-07. | Product Owner | Recommend promoting CSV export to Must, given RISK-02. |

---

## 14. Appendix — Decisions Log

The complete record of decisions taken during the requirements interview, in the order settled.

### Purpose and scope

1. Primary purpose is **wealth tracking**; spending control and investment performance are secondary.
2. The driving question is **per-account balance trend** — is a given account growing, and what is its history.
3. Success means sustained low-friction monthly entry, answering the driving question, and fully replacing the spreadsheet for new data.
4. Formal reconciliation against statements is a nice-to-have, not a v1 pillar.
5. **No migration.** Greenfield start; the existing seven months of lossy spreadsheet data will not be seeded.
6. Out of scope for v1: budgeting, forecasting, tax computation, bank and broker API connections, automatic price feeds, multi-user, native mobile application.
7. Single user in v1; the model should not preclude a second user later.

### Data model

8. **Balances are snapshot-only** — manually entered per account per month. No derived balances, and consequently no snapshot-versus-derived precedence rule.
9. Reporting period boundary is **calendar month-end**.
10. **Hard completeness block** — a month is Incomplete until every active account has a balance. *Flagged high-risk against the low-friction criterion.*
11. Cash flow, investments and FX do **not** drive balances. All four modules are decoupled.
12. Investments are a **performance record only**; investment account balances remain typed snapshots.
13. FX supplies month-end rates and, as originally scoped, logged conversions — later reduced, see item 33.

### Accounts and classification

14. **Nine granular account types.** No reporting-group rollup; slicing is by granular type directly.
15. **Four liquidity tiers** — Instant, Short, Long, Locked — manually assigned. Locked means access restricted until a date or event.
16. Liabilities in scope, entered as positive figures on liability-type accounts; the system applies the sign.
17. No effective-dated classification; reclassification restates history.
18. Lifecycle is **Open / Dormant / Closed**, with dormancy set **manually only**. Closed and pre-opening months are excluded from completeness; dormant accounts carry forward a stale-marked balance.

### Net worth reporting

19. Slices: granular account type, liquidity tier, currency, individual account. Institution and free-text tags deferred to Phase 2.
20. Start empty; back-dating permitted; back-dated months exempt from the completeness block.
21. Primary view is the **trend over time**, with point-in-time and per-account history one click away.
22. Default period is rolling twelve months, absolute plus month-on-month change in amount and percentage, with a date-range selector.

### Cash flow

23. **Two-level taxonomy**, Title Case, seeded then editable, categories deactivated rather than deleted. Housing split into Rent and Mortgage Payment.
24. **Transfers are not recorded at all.** Movement between own accounts is visible only via balances.
25. **Per-transaction manual entry.** Merchant field not required. Recurring transactions in scope; splits out. *Flagged high-risk: highest-friction decision made.*
26. Soft duplicate warning on matching date, amount and category.

### Investments

27. Instruments: individual equities, ETFs, mutual funds and unit trusts. Bonds, crypto and private holdings excluded.
28. **Lot-level tracking with FIFO cost basis.** *Flagged likely to change if CGT reporting is ever wanted.*
29. In scope: transaction fees, stock splits, dividend reinvestment. Excluded: mergers, spin-offs, rights issues, returns of capital.
30. **No prices in v1**, therefore no unrealised gain. Snapshot balances and holdings are independent records with no enforced relationship.
31. **Estimated tax is a manual percentage per holding**, applied to realised gains to display net-of-tax gains. The system performs no tax rules or jurisdiction logic.
32. Interest on cash and savings accounts, including HISA, goes to Cash Flow under `Income → Gains → Interest`. Dividends, distributions and realised gains on holdings go to the Investments module only. `Income → Gains` is retained.

### Foreign exchange

33. **Module 4 redefined** as a currency rate trend viewer and rate source — *not* a conversion tracker. No conversion transactions, and no realised or unrealised FX gain anywhere in the system. Recorded as a deliberate reduction from the original brief.
34. **USD is the stored base currency**; AUD and MYR are display toggles computed on the fly. No true base-currency switching.
35. **Manual daily rate table**; unentered days carry forward the last rate. Rates display their as-at date wherever a translated figure appears. Rate API deferred to Phase 2.
36. FX applies to balances and cash flow only. Investment performance is stated in each holding's own currency and never translated.

### Data entry

37. **No import in v1.** Manual entry only; CSV import deferred to Phase 2. *This removes the identified mitigation for the entry-friction risk from the release.*
38. **Month Close** is a single guided screen listing all active accounts with prior balance alongside an input, plus required rates.
39. All history fully editable. No month locking, no reopen step, no audit requirement.

### Reporting and interface

40. **Full multi-panel dashboard** across all four modules, **fixed layout**, no configurable widgets. Outstanding-tasks panel present, positioned below the net worth panels. *Flagged likely to change.*
41. All ten screens are must-have: dashboard; Month Close; net worth trend with slice toggles; account detail; accounts admin; cash flow entry and category report; investments; FX rate table and trend chart; categories admin; settings.
42. Interactions: filter and toggle with date-range selection. Drill-down deferred to Phase 2.
43. CSV export from any table or report — now the only application-level data escape hatch.
44. Desktop-optimised entry; tablet and mobile readable but not entry-optimised.

### Non-functional

45. Single local password, session-based.
46. **Backup handled externally** at the database layer; no in-application backup or restore requirement.
47. Indefinite retention, no archiving. Sizing: approximately 20 accounts, 100 transactions per month, ten years. Performance target of under two seconds per report.
48. No encryption at rest, no audit trail.
49. Single fixed timezone set in settings; all records are plain calendar dates with no time component. Current versions of Chrome, Edge, Firefox and Safari.

### Delivery

50. **Single release** covering all four modules. The phased R1–R4 sequence survives as internal build order only.
51. **No deadline.** The soft "before next month ends" target was dropped when single-release delivery was chosen.
52. Done means acceptance criteria passed **plus** one full month closed in live use with no blocking defects — now applying to all four modules simultaneously.
53. MoSCoW posture: Must = close a month and see the net worth trend. Should = cash flow and investments core. Could = dashboard polish, rate trend chart, drill-down, export. Won't (v1) = import, price feeds, budgets, forecasting, tax computation, multi-user, aggregators.
54. Recharts recorded as an **unconfirmed technology preference**, not a requirement.

---

*End of document.*
