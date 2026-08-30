/**
 * Cash flow — Transactions, Category report, Recurring, Categories.
 *
 * Recording is manual and per-transaction; there is no import path, so entry speed
 * is the whole battle. The probable-duplicate advisory appears below the form
 * and adding anyway is always permitted — two identical amounts on one day are
 * ordinary.
 *
 * Two prohibitions hold here, in the structure rather than in copy:
 *
 *   * **There is no transfer affordance anywhere.** Moving money between one's
 *     own accounts is not a transaction; it shows only as two balance changes
 *     at the next close (BR-11). Nothing on this screen offers it.
 *   * **No figure here is ever added to a balance figure** (BR-12). The
 *     category report is per currency and never translated, because a month's
 *     groceries in MYR and a month's rent in AUD are two separate facts.
 */

import { Fragment, useEffect, useMemo, useState, type FormEvent } from 'react'
import {
  ResponsiveContainer,
  Sankey,
  Tooltip,
  type SankeyLinkProps,
  type SankeyNodeProps,
} from 'recharts'

import { AdvisoryList, ErrorBanner } from '@/components/Advisories'
import { ExclusionNotice } from '@/components/Provenance'
import { type Advisory } from '@/lib/api'
import {
  type CategoryFlow as CategoryFlowReport,
  type CategoryFlowRow,
  type CategoryTotal,
  type CurrencyBlock,
  type Direction,
  type Frequency,
  type Movement,
  type RecurringTemplate,
  type TransactionRow,
  useAddCategory,
  useCategories,
  useCategoryFlow,
  useCategoryReport,
  useConfirmProposal,
  useCreateTemplate,
  useDeleteCategory,
  useDeleteTransaction,
  useDismissProposal,
  useEndTemplate,
  useProposals,
  useRecordTransaction,
  useTemplates,
  useTransactions,
  useUpdateCategory,
  useUpdateTransaction,
} from '@/lib/cashflow'
import {
  BREACH,
  LINK_OPACITY,
  NEUTRAL,
  RISE,
  SANKEY_MARGIN,
  SANKEY_NODE_PADDING,
  SANKEY_NODE_WIDTH,
  SANKEY_ROW,
} from '@/lib/charts'
import {
  formatAmount,
  formatDate,
  formatDecimal,
  formatMonthLong,
  monthEnd,
} from '@/lib/format'
import { useDefaultCurrency } from '@/lib/fx'
import { CURRENCIES, type Money, type ReportingCurrencyCode } from '@/lib/money'
import { useViewState } from '@/lib/viewState'

type Tab = 'transactions' | 'report' | 'recurring' | 'categories'

const TABS: readonly { key: Tab; label: string }[] = [
  { key: 'transactions', label: 'Transactions' },
  { key: 'report', label: 'Category Report' },
  { key: 'recurring', label: 'Recurring' },
  { key: 'categories', label: 'Categories' },
]

/** A calendar date, as the server spells it. */
const DATE_KEY = /^[0-9]{4}-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])$/

const FREQUENCIES: readonly Frequency[] = ['Weekly', 'Fortnightly', 'Monthly']

/** Today, read in UTC as every other date key in this app is. */
function today(): string {
  return new Date().toISOString().slice(0, 10)
}

/** A child category flattened onto its parent, for the selects. */
interface CategoryOption {
  readonly id: number
  readonly name: string
  readonly is_active: boolean
  readonly parentId: number
  readonly parentName: string
}

/**
 * The same children, gathered under their parents — `optgroup` rather than a
 * `Parent → Child` label on every line. Two parents may each own a subcategory
 * called Other, and the grouping is what tells them apart now that the parent
 * is no longer repeated in the option text.
 *
 * Insertion order is the order the API sent, so parents keep their own sequence
 * and are not re-sorted here.
 */
function groupByParent(
  options: readonly CategoryOption[],
): readonly [string, readonly CategoryOption[]][] {
  const groups = new Map<string, CategoryOption[]>()
  for (const option of options) {
    const existing = groups.get(option.parentName)
    if (existing) existing.push(option)
    else groups.set(option.parentName, [option])
  }
  return [...groups]
}

/** What a form holds while choosing a category. Only `category_id` is ever sent. */
interface CategoryChoice {
  readonly parent_id: string
  readonly category_id: string
}

/**
 * The two selects that name a category — parent first, then the subcategory the
 * transaction or template is actually filed against.
 *
 * One component rather than one per form: entry and a recurring template ask
 * the identical question, and a second copy is a second place for the narrowing
 * to drift. Rendered as a fragment so both selects stay direct children of the
 * form's grid.
 */
function CategoryFields({
  idPrefix,
  value,
  onChange,
}: {
  readonly idPrefix: string
  readonly value: CategoryChoice
  readonly onChange: (next: CategoryChoice) => void
}) {
  const categories = useCategories()

  /**
   * Parents worth offering — active, with at least one active child. A parent
   * whose children are all deactivated would open an empty subcategory list and
   * there would be nothing to file against.
   */
  const parents = useMemo(
    () =>
      (categories.data ?? []).filter(
        (parent) => parent.is_active && parent.children.some((child) => child.is_active),
      ),
    [categories.data],
  )

  /** The chosen parent's active children, in the order the API sent them. */
  const subcategories = useMemo(
    () =>
      (categories.data ?? [])
        .filter((parent) => String(parent.id) === value.parent_id)
        .flatMap((parent) => parent.children.filter((child) => child.is_active)),
    [categories.data, value.parent_id],
  )

  return (
    <>
      <div className="field cashflow__category">
        <label className="field__label" htmlFor={`${idPrefix}-parent`}>
          Category
        </label>
        <select
          id={`${idPrefix}-parent`}
          className="input"
          value={value.parent_id}
          // Changing the parent abandons the subcategory with it. Keeping it
          // would leave a chosen child under a parent that does not own it, and
          // the field would then disagree with what gets saved.
          onChange={(event) => onChange({ parent_id: event.target.value, category_id: '' })}
          required
        >
          <option value="">Choose…</option>
          {parents.map((parent) => (
            <option key={parent.id} value={parent.id}>
              {parent.name}
            </option>
          ))}
        </select>
      </div>

      <div className="field cashflow__category">
        <label className="field__label" htmlFor={`${idPrefix}-category`}>
          Subcategory
        </label>
        <select
          id={`${idPrefix}-category`}
          className="input"
          value={value.category_id}
          onChange={(event) => onChange({ ...value, category_id: event.target.value })}
          // Nothing to choose from until a parent is chosen, and saying so with
          // a disabled select is plainer than an empty open list.
          disabled={value.parent_id === ''}
          required
        >
          <option value="">
            {value.parent_id === '' ? 'Category first…' : 'Choose…'}
          </option>
          {subcategories.map((child) => (
            <option key={child.id} value={child.id}>
              {child.name}
            </option>
          ))}
        </select>
      </div>
    </>
  )
}

interface Draft {
  date: string
  amount: string
  currency: string
  category_id: string
  note: string
}

function draftOf(row: TransactionRow): Draft {
  return {
    date: row.date,
    amount: row.amount,
    currency: row.currency,
    category_id: String(row.category_id),
    note: row.note,
  }
}

/**
 * Only what the user actually altered. Sending the untouched fields back would
 * put an unchanged category through the active-category check again, which
 * would leave a transaction on a since-deactivated category unable to have its
 * note corrected.
 */
function changedFields(row: TransactionRow, draft: Draft) {
  const changes: {
    date?: string
    amount?: string
    currency?: string
    category_id?: number
    note?: string
  } = {}

  if (draft.date !== row.date) changes.date = draft.date
  if (draft.amount.trim() !== row.amount) changes.amount = draft.amount.trim()
  if (draft.currency !== row.currency) changes.currency = draft.currency
  if (Number(draft.category_id) !== row.category_id)
    changes.category_id = Number(draft.category_id)
  if (draft.note !== row.note) changes.note = draft.note

  return changes
}

/** Advisories and refusals, against the row that produced them. */
function RowMessages({
  advisories,
  error,
}: {
  readonly advisories: readonly Advisory[]
  readonly error: unknown
}) {
  if (advisories.length === 0 && error == null) return null

  return (
    <tr className="table__message-row">
      <td colSpan={7}>
        <ErrorBanner error={error} />
        <AdvisoryList advisories={advisories} />
      </td>
    </tr>
  )
}

/**
 * The row's amount restated in the reporting currency.
 *
 * A column beside the entered figure and never in place of it: the transaction
 * happened in the currency it was recorded in, and nothing here rewrites that.
 * Each row is restated at the rate on **its own date** — a payment made on the
 * 3rd was worth what it was worth on the 3rd — and because the month's totals
 * are sums of these same figures, the column adds down to the net the dashboard
 * states.
 *
 * Where no rate exists on or before the row's date the cell **withholds a
 * number and says so in words** (FR-46). A zero here would be a claim that the
 * money was worth nothing, and the row keeps its own-currency figure and its
 * place in the list either way.
 *
 * A rate older than the staleness threshold takes the stale treatment, which is
 * a per-row fact here rather than a per-table one: two purchases a fortnight
 * apart lean on two different rates, and only one of them may be old.
 */
function RestatedCell({ row }: { readonly row: TransactionRow }) {
  const restated = row.restatement

  if (!restated || restated.amount === null) {
    return (
      <td className="numeric">
        <span className="excluded" title={restated?.exclusion_reason ?? undefined}>
          excluded — no rate
        </span>
      </td>
    )
  }

  return (
    <td className="numeric">
      <span
        className={`money ${row.direction === 'Income' ? 'money--rise' : ''} ${
          restated.rate?.stale ? 'rate--stale' : ''
        }`.trim()}
      >
        {row.direction === 'Income' ? '+' : '−'}
        {formatAmount(restated.amount)}
        <span className="money__code">{restated.amount.currency}</span>
      </span>
    </td>
  )
}

/**
 * One transaction, editable in place. Everything is editable at any time,
 * including history (BR-23, FR-53) — date, amount, currency, category and note
 * alike.
 *
 * The edit commits on Save rather than field by field, unlike account
 * reclassification: five fields typed a character at a time would otherwise be
 * a request per keystroke, and a half-typed amount would be saved on its way to
 * the real one.
 */
function TransactionRowView({
  row,
  options,
}: {
  readonly row: TransactionRow
  readonly options: readonly CategoryOption[]
}) {
  const update = useUpdateTransaction()
  const remove = useDeleteTransaction()
  const [draft, setDraft] = useState<Draft | null>(null)
  const [advisories, setAdvisories] = useState<readonly Advisory[]>([])

  const error = update.error ?? remove.error

  function save() {
    if (draft === null) return
    if (!draft.amount.trim() || !draft.category_id) return

    const changes = changedFields(row, draft)
    if (Object.keys(changes).length === 0) {
      setDraft(null)
      return
    }

    setAdvisories([])
    update.mutate(
      { id: row.id, ...changes },
      {
        onSuccess: (response) => {
          // Saved. The advisory sits under the row it concerns and blocks
          // nothing — an edit onto an identical twin is as ordinary as
          // entering one.
          setAdvisories(response.advisories)
          setDraft(null)
        },
      },
    )
  }

  function cancel() {
    setDraft(null)
    update.reset()
  }

  if (draft === null) {
    return (
      <>
        <tr>
          <td className="mono">{formatDate(row.date)}</td>
          <td className="secondary">{row.parent}</td>
          <td>{row.category}</td>
          <td className="secondary">{row.note}</td>
          <td className="numeric">
            <span className={row.direction === 'Income' ? 'money money--rise' : 'money'}>
              {row.direction === 'Income' ? '+' : '−'}
              {formatDecimal(row.amount)}
              <span className="money__code">{row.currency}</span>
            </span>
          </td>
          <RestatedCell row={row} />
          <td>
            <div className="cashflow__actions">
              <button
                type="button"
                className="link-button"
                onClick={() => {
                  setAdvisories([])
                  setDraft(draftOf(row))
                }}
              >
                Edit
              </button>
              <button
                type="button"
                className="link-button link-button--breach"
                onClick={() => remove.mutate(row.id)}
              >
                Delete
              </button>
            </div>
          </td>
        </tr>

        <RowMessages advisories={advisories} error={error} />
      </>
    )
  }

  // A category deactivated after the fact still names this transaction, so it
  // stays in this row's list. Dropping it would open the select on a blank and
  // saving would then recategorise a row the user only meant to renote.
  const selectable = options.filter(
    (option) => option.is_active || option.id === row.category_id,
  )

  /** Whose parent the Category cell shows while the select is open. */
  const chosen = selectable.find((option) => String(option.id) === draft.category_id)

  return (
    <>
      <tr
        // Enter commits and Escape abandons, so correcting one field never needs
        // the pointer.
        onKeyDown={(event) => {
          if (event.key === 'Enter') {
            event.preventDefault()
            save()
          }
          if (event.key === 'Escape') cancel()
        }}
      >
        <td>
          <input
            type="date"
            className="input input--grid mono"
            aria-label="Date"
            value={draft.date}
            onChange={(event) => setDraft({ ...draft, date: event.target.value })}
          />
        </td>
        {/* Not editable in its own right: a transaction is filed against a
            subcategory, and its parent is whatever that subcategory belongs to.
            Shown because the column exists and the cell must not read as blank,
            and it follows the select next to it. */}
        <td className="secondary">{chosen?.parentName ?? row.parent}</td>
        <td>
          <select
            className="input input--grid"
            aria-label="Subcategory"
            value={draft.category_id}
            onChange={(event) => setDraft({ ...draft, category_id: event.target.value })}
          >
            {groupByParent(selectable).map(([parent, children]) => (
              <optgroup key={parent} label={parent}>
                {children.map((option) => (
                  <option key={option.id} value={option.id}>
                    {option.name}
                    {option.is_active ? '' : ' (deactivated)'}
                  </option>
                ))}
              </optgroup>
            ))}
          </select>
        </td>
        <td>
          <input
            className="input input--grid"
            aria-label="Note"
            value={draft.note}
            onChange={(event) => setDraft({ ...draft, note: event.target.value })}
          />
        </td>
        <td>
          {/* The pair sits in a wrapper, not in the cell itself: a `td` given
              `display: flex` stops being a table cell, and the actions cell
              after it is then pushed onto its own line. */}
          <div className="cashflow__amount-cell">
            <input
              className="input input--grid mono numeric-input"
              aria-label="Amount"
              inputMode="decimal"
              value={draft.amount}
              onChange={(event) => setDraft({ ...draft, amount: event.target.value })}
            />
            <select
              className="input input--grid mono"
              aria-label="Currency"
              value={draft.currency}
              onChange={(event) => setDraft({ ...draft, currency: event.target.value })}
            >
              {CURRENCIES.map((code) => (
                <option key={code} value={code}>
                  {code}
                </option>
              ))}
            </select>
          </div>
        </td>
        {/* Derived from an amount currently being retyped, so there is nothing
            true to put here until the edit is saved. The old figure would be a
            restatement of a figure no longer on the row. */}
        <td className="numeric secondary">—</td>
        <td>
          <div className="cashflow__actions">
            <button
              type="button"
              className="link-button link-button--commit"
              onClick={save}
              disabled={update.isPending}
            >
              {update.isPending ? 'Saving…' : 'Save'}
            </button>
            <button type="button" className="link-button" onClick={cancel}>
              Cancel
            </button>
          </div>
        </td>
      </tr>

      <RowMessages advisories={advisories} error={error} />
    </>
  )
}

// ---------------------------------------------------------------------------

function Transactions({
  month,
  currency,
}: {
  readonly month: string
  /** What the column beside each amount is stated in. Never what it is stored in. */
  readonly currency: ReportingCurrencyCode
}) {
  const categories = useCategories()
  const transactions = useTransactions(month, currency)
  const proposals = useProposals(month)
  const record = useRecordTransaction()
  const confirm = useConfirmProposal()
  const dismiss = useDismissProposal()

  // Seeds the field on the first render and then leaves it alone — a
  // transaction keeps whichever currency was chosen for it.
  const defaultCurrency = useDefaultCurrency()

  const [advisories, setAdvisories] = useState<readonly Advisory[]>([])
  const [form, setForm] = useState({
    date: `${month}-01`,
    amount: '',
    currency: defaultCurrency as string,
    // The parent narrows the subcategory list and is not sent: a transaction is
    // filed against the subcategory, which already knows its parent.
    parent_id: '',
    category_id: '',
    note: '',
  })

  // A month the field can no longer reach must not stay in it. Left alone the
  // date would sit outside the bounds set below, where the browser blocks the
  // submit with a message of its own choosing and the form looks broken.
  useEffect(() => {
    setForm((current) => ({ ...current, date: `${month}-01` }))
  }, [month])

  // Every child, active or not. The entry form takes only the active ones; an
  // existing row also needs the deactivated category it already carries.
  const children = useMemo<readonly CategoryOption[]>(
    () =>
      (categories.data ?? []).flatMap((parent) =>
        parent.children.map((child) => ({
          ...child,
          parentId: parent.id,
          parentName: parent.name,
        })),
      ),
    [categories.data],
  )

  const rows = transactions.data?.rows ?? []

  function submit(event: FormEvent) {
    event.preventDefault()
    if (!form.category_id || !form.amount.trim()) return

    record.mutate(
      {
        date: form.date,
        amount: form.amount,
        currency: form.currency,
        category_id: Number(form.category_id),
        note: form.note,
      },
      {
        onSuccess: (response) => {
          setAdvisories(response.advisories)
          setForm({ ...form, amount: '', note: '' })
        },
      },
    )
  }

  return (
    <div className="cashflow__entry">
      <section className="panel">
        <h2 className="panel__heading">Add a Transaction</h2>
        <ErrorBanner error={record.error} />

        <form className="cashflow__form" onSubmit={submit}>
          <div className="field">
            <label className="field__label" htmlFor="txn-date">
              Date
            </label>
            <input
              id="txn-date"
              type="date"
              className="input mono"
              value={form.date}
              // The spine chose the month, and entry cannot leave it: a row
              // dated outside it would be saved and then vanish from the list
              // below, which reads as a lost transaction.
              min={`${month}-01`}
              max={monthEnd(month)}
              onChange={(event) => setForm({ ...form, date: event.target.value })}
            />
          </div>

          <CategoryFields
            idPrefix="txn"
            value={{ parent_id: form.parent_id, category_id: form.category_id }}
            onChange={(next) => setForm({ ...form, ...next })}
          />

          <div className="field cashflow__note">
            <label className="field__label" htmlFor="txn-note">
              Note
            </label>
            <input
              id="txn-note"
              className="input"
              value={form.note}
              onChange={(event) => setForm({ ...form, note: event.target.value })}
            />
          </div>
          <div className="field">
            <label className="field__label" htmlFor="txn-amount">
              Amount
            </label>
            <input
              id="txn-amount"
              className="input mono numeric-input"
              inputMode="decimal"
              placeholder="0.00"
              value={form.amount}
              onChange={(event) => setForm({ ...form, amount: event.target.value })}
            />
          </div>

          <div className="field">
            <label className="field__label" htmlFor="txn-currency">
              Currency
            </label>
            <select
              id="txn-currency"
              className="input mono"
              value={form.currency}
              onChange={(event) => setForm({ ...form, currency: event.target.value })}
            >
              {CURRENCIES.map((code) => (
                <option key={code} value={code}>
                  {code}
                </option>
              ))}
            </select>
          </div>


          <button type="submit" className="btn btn--primary" disabled={record.isPending}>
            Add
          </button>
        </form>

        {/* Adding anyway is always permitted. */}
        <AdvisoryList advisories={advisories} />
      </section>

      <section className="panel">
        <h2 className="panel__heading">Recurring Proposals</h2>
        {(proposals.data ?? []).length === 0 ? (
          <p className="fx__note">
            Nothing recurring falls in {formatMonthLong(month)}.
          </p>
        ) : (
          <div className="proposals">
            {(proposals.data ?? []).map((proposal) => {
              const decided = proposal.status !== 'Outstanding'
              return (
                <div
                  className={`proposal${decided ? ' proposal--decided' : ''}`}
                  key={`${proposal.template_id}-${proposal.occurrence}`}
                >
                  <div className="proposal__head">
                    <span>{proposal.name}</span>
                    <span className="mono">
                      {/* What was recorded, where anything was — the amount is
                          adjustable at confirmation, so the template's figure
                          would be reporting the proposal and not the
                          transaction. */}
                      {formatDecimal(proposal.recorded_amount ?? proposal.amount)}
                      <span className="money__code">{proposal.currency}</span>
                    </span>
                  </div>

                  <div className="proposal__meta">
                    {/* The occurrence is a date, because a weekly arrangement has
                        four or five of them in a month and each is its own
                        decision. */}
                    <span className="mono">{formatDate(proposal.occurrence)}</span>
                    <span>{proposal.category}</span>
                    {/* Only what was decided. An outstanding occurrence is
                        already saying so with the three buttons under it, and a
                        line repeating them is a word where a question is. */}
                    {decided && (
                      <span
                        className={`proposal__status proposal__status--${proposal.status.toLowerCase()}`}
                      >
                        {proposal.status}
                      </span>
                    )}
                    {/* Only where it differs from the occurrence: a date the
                        user moved is worth saying, and one they did not is
                        already printed beside it. */}
                    {proposal.recorded_date &&
                      proposal.recorded_date !== proposal.occurrence && (
                        <span className="mono">
                          recorded {formatDate(proposal.recorded_date)}
                        </span>
                      )}
                  </div>

                  {/* Only an undecided occurrence is still a question. A
                      confirmed one is edited as the transaction it became, in
                      the register below; a skipped one is not a transaction at
                      all. */}
                  {!decided && (
                    <div className="proposal__actions">
                      <button
                        type="button"
                        className="btn btn--primary"
                        onClick={() =>
                          confirm.mutate({
                            template_id: proposal.template_id,
                            occurrence: proposal.occurrence,
                          })
                        }
                      >
                        Confirm
                      </button>
                      <button
                        type="button"
                        className="btn"
                        onClick={() => {
                          const amount = window.prompt('Amount', proposal.amount)
                          if (amount)
                            confirm.mutate({
                              template_id: proposal.template_id,
                              occurrence: proposal.occurrence,
                              amount,
                            })
                        }}
                      >
                        Edit
                      </button>
                      <button
                        type="button"
                        className="btn"
                        onClick={() =>
                          dismiss.mutate({
                            template_id: proposal.template_id,
                            occurrence: proposal.occurrence,
                          })
                        }
                      >
                        Skip
                      </button>
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        )}
      </section>

      <section className="panel cashflow__list">
        <h2 className="panel__heading">Transactions for {formatMonthLong(month)}</h2>
        {rows.length === 0 ? (
          <p className="fx__note">Nothing recorded for this month.</p>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>Date</th>
                <th>Category</th>
                <th>Subcategory</th>
                <th>Note</th>
                <th className="numeric">Amount</th>
                {/* Named by the currency rather than labelled "Reporting": the
                    column states figures in one currency and saying which is
                    more use than saying which setting chose it. */}
                <th className="numeric">In {currency}</th>
                <th aria-label="Actions" />
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <TransactionRowView key={row.id} row={row} options={children} />
              ))}
            </tbody>
          </table>
        )}

        {/* Only when a contributing rate is stale, as on the dashboard and on
            the flow above. Silence is the signal. */}
        {transactions.data?.any_stale && transactions.data.as_at && (
          <details className="asat">
            <summary className="asat__summary">
              Rates as at {formatDate(transactions.data.as_at)}
            </summary>
            <table className="table asat__detail">
              <tbody>
                {transactions.data.rate_provenance.map((note) => (
                  <tr key={note.pair}>
                    <td className="mono">{note.pair}</td>
                    <td className="secondary">{formatDate(note.as_at)}</td>
                    <td className="secondary">{note.provenance}</td>
                    <td>{note.stale ? <span className="carry">stale</span> : ''}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </details>
        )}

        {/* The rows are all still above; it is the column that withholds a
            figure for them, and the reason is stated rather than implied. */}
        <ExclusionNotice exclusions={transactions.data?.exclusions ?? []} />
      </section>
    </div>
  )
}

// ---------------------------------------------------------------------------

type Tone = 'Income' | 'Expense' | 'hub'

interface FlowNodeDatum {
  readonly name: string
  readonly tone: Tone
  /** Leaves label outward; interior nodes label into the gap above themselves. */
  readonly side: 'left' | 'right' | 'above'
  /** The server's own string. Never the float the ribbon is drawn from. */
  readonly amount?: string
  /** The hub's three totals, which are not one figure and so are not one label. */
  readonly figures?: {
    readonly income: string
    readonly expense: string
    readonly net: string
  }
}

interface FlowLinkDatum {
  readonly source: number
  readonly target: number
  readonly value: number
  readonly tone: 'Income' | 'Expense'
  readonly amount: string
}

interface Flow {
  readonly nodes: readonly FlowNodeDatum[]
  readonly links: readonly FlowLinkDatum[]
  readonly height: number
}

/**
 * One month's categories as a flow: income children into their parents, through
 * the month, out through the expense parents into their children.
 *
 * Every figure arrives translated and rolled up. Nothing is summed here — a
 * browser that added money would be adding floats (ADR-02), and a parent total
 * computed on the ribbon would stop agreeing with the one the server sent.
 *
 * A zero category is dropped rather than drawn: a ribbon of no width is a label
 * attached to nothing, and the layout divides by each column's total.
 *
 * Everything is ordered largest first — the parents against each other, and each
 * parent's children within its own band. The eye goes to the top of a column for
 * the thing that mattered most, and a category keeps its place from one month to
 * the next unless the month itself changed the ranking.
 */
function buildFlow(report: CategoryFlowReport): Flow | null {
  const nodes: FlowNodeDatum[] = []
  const links: FlowLinkDatum[] = []
  const columns = new Map<string, number>()

  const push = (column: string, node: FlowNodeDatum): number => {
    columns.set(column, (columns.get(column) ?? 0) + 1)
    return nodes.push(node) - 1
  }

  const hub = push('hub', {
    name: formatMonthLong(report.month),
    tone: 'hub',
    side: 'above',
    figures: {
      income: report.income.amount,
      expense: report.expense.amount,
      net: report.net.amount,
    },
  })

  /**
   * Largest first, and a zero dropped rather than drawn — a ribbon of no width
   * is a label attached to nothing.
   *
   * The float here is the one the ribbon is already drawn from: a chart needs
   * pixels and pixels need a float (ADR-02's one exception). It orders rows and
   * sets a width, and it is never the figure the reader is shown — every label
   * prints the server's own string.
   */
  const bySize = <T extends { readonly total: Money }>(rows: readonly T[]) =>
    rows
      .map((row) => ({ row, value: Number(row.total.amount) }))
      .filter((entry) => entry.value > 0)
      .sort((a, b) => b.value - a.value)

  // Grouped before the parents are walked, so each parent can emit its own
  // children immediately after itself.
  const children = new Map<string, ReturnType<typeof bySize<CategoryFlowRow>>>()
  for (const entry of bySize(report.children)) {
    const key = `${entry.row.direction}:${entry.row.parent}`
    const group = children.get(key)
    if (group) group.push(entry)
    else children.set(key, [entry])
  }

  // The order the nodes are pushed in *is* the order the diagram draws them,
  // top to bottom, because the layout is told not to re-sort (`sort={false}`
  // below). So a parent's own children follow it here rather than being emitted
  // in a second pass: that is what keeps each family in one band, with the
  // largest at the top of it, and what stops one parent's ribbons crossing
  // another's.
  for (const { row: parent, value } of bySize(report.parents)) {
    const at = push(`parent:${parent.direction}`, {
      name: parent.parent,
      tone: parent.direction,
      side: 'above',
      amount: parent.total.amount,
    })
    links.push(
      parent.direction === 'Income'
        ? { source: at, target: hub, value, tone: 'Income', amount: parent.total.amount }
        : { source: hub, target: at, value, tone: 'Expense', amount: parent.total.amount },
    )

    const group = children.get(`${parent.direction}:${parent.parent}`) ?? []
    for (const { row: child, value: childValue } of group) {
      const leaf = push(`child:${child.direction}`, {
        name: child.category,
        tone: child.direction,
        side: child.direction === 'Income' ? 'left' : 'right',
        amount: child.total.amount,
      })
      links.push(
        child.direction === 'Income'
          ? {
              source: leaf,
              target: at,
              value: childValue,
              tone: 'Income',
              amount: child.total.amount,
            }
          : {
              source: at,
              target: leaf,
              value: childValue,
              tone: 'Expense',
              amount: child.total.amount,
            },
      )
    }
  }

  if (links.length === 0) return null

  // The tallest column sets the height: every node in it needs a row of its
  // own, or the labels stack on top of one another.
  const rows = Math.max(...columns.values())
  return {
    nodes,
    links,
    height: Math.min(760, Math.max(240, rows * SANKEY_ROW)),
  }
}

/** A node and its label. The label carries the figure; the rectangle is a hinge. */
function FlowNode({ x, y, width, height, payload }: SankeyNodeProps) {
  const datum = payload as unknown as FlowNodeDatum
  const fill = datum.tone === 'Income' ? RISE : datum.tone === 'Expense' ? BREACH : NEUTRAL

  const anchor = datum.side === 'left' ? 'end' : datum.side === 'right' ? 'start' : 'middle'
  const textX =
    datum.side === 'left' ? x - 8 : datum.side === 'right' ? x + width + 8 : x + width / 2

  return (
    <>
      <rect x={x} y={y} width={width} height={Math.max(height, 1)} rx={2} fill={fill} />
      <text
        x={textX}
        y={datum.side === 'above' ? y - 7 : y + height / 2}
        textAnchor={anchor}
        dominantBaseline={datum.side === 'above' ? 'auto' : 'central'}
        fontSize={11}
      >
        <tspan fill="rgba(233,233,237,.85)">{datum.name}</tspan>
        {datum.amount !== undefined && (
          <tspan dx={7} fill="rgba(233,233,237,.45)">
            {formatDecimal(datum.amount)}
          </tspan>
        )}
      </text>
    </>
  )
}

/** A ribbon, its width the amount and its colour the direction it is flowing. */
function FlowLink({
  sourceX,
  sourceY,
  sourceControlX,
  targetX,
  targetY,
  targetControlX,
  linkWidth,
  payload,
}: SankeyLinkProps) {
  const tone = (payload as unknown as FlowLinkDatum).tone
  return (
    <path
      className="recharts-sankey-link"
      d={`M${sourceX},${sourceY} C${sourceControlX},${sourceY} ${targetControlX},${targetY} ${targetX},${targetY}`}
      fill="none"
      stroke={tone === 'Income' ? RISE : BREACH}
      strokeWidth={Math.max(linkWidth, 1)}
      strokeOpacity={LINK_OPACITY}
    />
  )
}

/**
 * Figures in the tip are the server's strings, like every other figure on the
 * screen. The ribbon's own number is a width in pixels.
 */
function FlowTooltip({
  active,
  payload,
  currency,
}: {
  readonly active?: boolean
  readonly payload?: readonly { readonly payload?: unknown }[]
  readonly currency: string
}) {
  const hovered = active ? payload?.[0]?.payload : undefined
  if (hovered == null || typeof hovered !== 'object') return null

  // The layout resolves a link's source and target from indices to the nodes
  // themselves, which is how a ribbon's tip can name both of its ends.
  const datum = hovered as Partial<FlowNodeDatum & Omit<FlowLinkDatum, 'source' | 'target'>> & {
    readonly source?: { readonly name?: string }
    readonly target?: { readonly name?: string }
  }

  // The hub. Its inflow and its outflow are two different figures, so it is the
  // one node whose label cannot be a number — the tip states all three.
  if (datum.figures) {
    return (
      <div className="charttip">
        <div className="charttip__month mono">
          {datum.name} · {currency}
        </div>
        <dl className="charttip__list">
          <dt>Income</dt>
          <dd className="mono" style={{ color: RISE }}>
            {formatDecimal(datum.figures.income)}
          </dd>
          <dt>Expense</dt>
          <dd className="mono" style={{ color: BREACH }}>
            {formatDecimal(datum.figures.expense)}
          </dd>
          <dt>Net</dt>
          <dd
            className={`mono ${datum.figures.net.startsWith('-') ? 'money--breach' : 'money--rise'}`}
          >
            {formatDecimal(datum.figures.net)}
          </dd>
        </dl>
      </div>
    )
  }

  if (datum.amount === undefined) return null

  // A link knows both of its ends; a node knows only itself.
  const heading =
    typeof datum.source === 'object' && typeof datum.target === 'object'
      ? `${datum.source?.name} → ${datum.target?.name}`
      : datum.name

  return (
    <div className="charttip">
      <div className="charttip__month mono">{heading}</div>
      <dl className="charttip__list">
        <dt>{datum.tone}</dt>
        <dd className="mono">
          {formatDecimal(datum.amount)} {currency}
        </dd>
      </dl>
    </div>
  )
}

/**
 * The month as a flow, with every currency combined into the reporting one.
 *
 * This is the one translated figure in cash flow reporting, and the BRD
 * sanctions it — FX applies to balances and cash flow alike (A36); only
 * investment performance is barred (BR-18). It is what makes a single diagram
 * possible for a life lived in more than one currency: the tables below still
 * hold the exact per-currency record, and a reader who wants to know what a
 * thing cost in the money it was bought with reads them, not this.
 *
 * Because it is translated it carries what qualifies a translated total — the
 * currencies excluded for want of a rate, stated rather than quietly counted
 * as zero (FR-46), and where the rates it did use came from. Both are rendered
 * as they are on the dashboard, which is denominated by the same rule at the
 * same month-end rate.
 */
function CategoryFlow({
  report,
  flow,
}: {
  readonly report: CategoryFlowReport
  readonly flow: Flow | null
}) {
  return (
    <section className="panel">
      <h2 className="panel__heading">Category Flow</h2>

      {flow === null ? (
        // Silent about the month where the exclusions below already say why
        // there is nothing to draw. Two explanations of one absence is one
        // more than the reader needs.
        report.exclusions.length === 0 && (
          <p className="fx__note">Nothing recorded for {formatMonthLong(report.month)}.</p>
        )
      ) : (
        <figure className="cashflow__flow">
          <ResponsiveContainer width="100%" height={flow.height}>
            <Sankey
              data={{ nodes: [...flow.nodes], links: [...flow.links] }}
              margin={SANKEY_MARGIN}
              nodeWidth={SANKEY_NODE_WIDTH}
              nodePadding={SANKEY_NODE_PADDING}
              // Stack every column from the top rather than centring each one
              // against its own flows. Centred, a column of seven parents sits
              // lower than the column of fourteen children beside it — whose
              // padding alone fills the height — so the widest expense path left
              // the hub, sank to its parent and climbed back up to its largest
              // child. Aligned, the biggest band runs straight across the top,
              // which is the line the eye follows first.
              verticalAlign="top"
              // Keep the order `buildFlow` emitted. Left to re-sort each column
              // by weight, the layout lifts a large child above a different
              // parent's small ones — Rent above Gifts and Household — and those
              // two ribbons then cross Housing's.
              sort={false}
              node={(props) => <FlowNode {...props} />}
              link={(props) => <FlowLink {...props} />}
            >
              <Tooltip content={<FlowTooltip currency={report.currency} />} />
            </Sankey>
          </ResponsiveContainer>
        </figure>
      )}

      {/* Only when a contributing rate is stale, as on the dashboard. */}
      {report.any_stale && report.as_at && (
        <details className="asat">
          <summary className="asat__summary">Rates as at {formatDate(report.as_at)}</summary>
          <table className="table asat__detail">
            <tbody>
              {report.rate_provenance.map((row) => (
                <tr key={row.pair}>
                  <td className="mono">{row.pair}</td>
                  <td className="secondary">{formatDate(row.as_at)}</td>
                  <td className="secondary">{row.provenance}</td>
                  <td>{row.stale ? <span className="carry">stale</span> : ''}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      )}

      {/* A transaction with no rate on its own date is withheld from the
          diagram — never drawn as zero, and always said (FR-46). */}
      <ExclusionNotice exclusions={report.exclusions} />
    </section>
  )
}

// ---------------------------------------------------------------------------

/**
 * A row's movement on the month before it.
 *
 * Colour is judgement, not direction. Income up is a rise and income down is a
 * breach — but **expense up is a breach**, because spending more is not good
 * news, and painting it green because the number grew would be the colour
 * contradicting the figure. The same rule the dashboard's four figures follow.
 *
 * A new category reads as its whole total, because in cash flow a month with
 * nothing in a category genuinely spent nothing there.
 */
function MovementCell({
  movement,
  direction,
}: {
  readonly movement: Movement
  readonly direction: Direction
}) {
  if (movement.change === null) return <td className="numeric secondary">—</td>

  const falling = movement.change.startsWith('-')
  const good = falling !== (direction === 'Income')

  return (
    <td className="numeric">
      <span className={good ? 'money--rise' : 'money--breach'}>
        {falling ? '' : '+'}
        {formatDecimal(movement.change)}
      </span>
    </td>
  )
}

/**
 * One currency's categories, a parent to a row, opening onto its own children.
 *
 * The parent totals are the server's own rollup, not a sum taken here. Adding
 * money in the browser adds floats (ADR-02), and a total computed on the row
 * would stop agreeing with the one the diagram above it was drawn from.
 *
 * Closed to begin with. The question a month asks first is which parent the
 * money went to; the subcategory is the follow-up, and it is asked one parent at
 * a time rather than by reading forty rows.
 */
function CategoryRollup({ block }: { readonly block: CurrencyBlock }) {
  const [open, setOpen] = useState<readonly string[]>([])
  // A second list rather than a nesting of the first: a subcategory is opened
  // and closed independently of its parent, and closing a parent hides its
  // subcategories without deciding anything about them. Reopening it finds
  // them as they were left.
  const [openChildren, setOpenChildren] = useState<readonly string[]>([])

  const keyOf = (direction: Direction, parent: string) => `${direction}:${parent}`

  const toggle =
    (set: typeof setOpen) =>
    (key: string) =>
      set((current) =>
        current.includes(key)
          ? current.filter((entry) => entry !== key)
          : [...current, key],
      )

  /**
   * What came in, then what went out, each largest first.
   *
   * Income leads because it is the month's ceiling: the expenses underneath are
   * read against it. The server sends this alphabetically, which puts Expense
   * above Income and buries the biggest figure in the middle of the page.
   *
   * The float compares; it is never shown. Every figure in the table below is
   * printed from the server's own string (ADR-02).
   */
  const byTotal = (a: { readonly total: string }, b: { readonly total: string }) =>
    Number(b.total) - Number(a.total)
  const incomeFirst = (direction: Direction) => (direction === 'Income' ? 0 : 1)

  const parents = useMemo(
    () =>
      [...block.parents].sort(
        (a, b) =>
          incomeFirst(a.direction) - incomeFirst(b.direction) || byTotal(a, b),
      ),
    [block.parents],
  )

  const children = useMemo(() => {
    const grouped = new Map<string, CategoryTotal[]>()
    for (const row of block.children) {
      const key = keyOf(row.direction, row.parent)
      const group = grouped.get(key)
      if (group) group.push(row)
      else grouped.set(key, [row])
    }
    for (const group of grouped.values()) group.sort(byTotal)
    return grouped
  }, [block.children])

  return (
    <table className="table table--fixed">
      {/* One panel per currency, stacked down the page. They only read as one
          report if their columns line up, and separate tables under auto layout
          each size to their own content — a month with two MYR rows would put
          its Total column somewhere else entirely. Pinned here, as on Accounts
          and Investments. */}
      <colgroup>
        <col style={{ width: '36%' }} />
        <col style={{ width: '12%' }} />
        <col style={{ width: '14%' }} />
        <col style={{ width: '19%' }} />
        <col style={{ width: '19%' }} />
      </colgroup>
      <thead>
        <tr>
          <th>Category</th>
          <th>Type</th>
          <th className="numeric">Transactions</th>
          <th className="numeric">Total</th>
          <th className="numeric">Change</th>
        </tr>
      </thead>
      <tbody>
        {parents.map((parent) => {
          const key = keyOf(parent.direction, parent.parent)
          const expanded = open.includes(key)

          return (
            <Fragment key={key}>
              {/* The row is the target — the arrow says what will happen, but a
                  9px glyph is not what a pointer should have to hit, and neither
                  is a name when the figures beside it are part of the same
                  thought. */}
              <tr
                className={`disclosure-row${expanded ? ' disclosure-row--open' : ''}`}
                onClick={() => toggle(setOpen)(key)}
              >
                <td>
                  {/* Carries the state and takes the focus, but not a handler of
                      its own: a click here — including the one Enter and Space
                      raise on a focused button — reaches the row above. */}
                  <button type="button" className="disclosure" aria-expanded={expanded}>
                    <span className="disclosure__arrow" aria-hidden="true">
                      ▸
                    </span>
                    {parent.parent}
                  </button>
                </td>
                <td className="secondary">{parent.direction}</td>
                <td className="numeric secondary">{parent.count}</td>
                <td className="numeric">{formatDecimal(parent.total)}</td>
                <MovementCell movement={parent.change} direction={parent.direction} />
              </tr>

              {expanded &&
                (children.get(key) ?? []).map((row) => {
                  const childKey = `${key}:${row.category_id}`
                  const childOpen = openChildren.includes(childKey)

                  return (
                    <Fragment key={row.category_id}>
                      {/* The same row-is-the-target rule as the parent above:
                          the arrow says what will happen, the whole row is what
                          gets hit. */}
                      <tr
                        className="disclosure-row"
                        onClick={() => toggle(setOpenChildren)(childKey)}
                      >
                        <td className="disclosure__child">
                          <button
                            type="button"
                            className="disclosure"
                            aria-expanded={childOpen}
                          >
                            <span className="disclosure__arrow" aria-hidden="true">
                              ▸
                            </span>
                            {row.category}
                          </button>
                        </td>
                        {/* A child's direction is its parent's. Restating it on every
                            row would be four columns of the same word. */}
                        <td />
                        <td className="numeric secondary">{row.count}</td>
                        <td className="numeric">{formatDecimal(row.total)}</td>
                        <MovementCell movement={row.change} direction={row.direction} />
                      </tr>

                      {/* The third level: the transactions the figure above is
                          the sum of. Workings, not entries — unruled and tight,
                          the treatment a consumed lot gets under its sale, so
                          they cannot be misread as more subcategories.

                          Each amount sits in the Total column, directly under
                          the figure it contributes to. That column is the whole
                          reason to open the row, and nothing is added here to
                          reach it: the server sent the total, the server sent
                          these, and the browser prints both (ADR-02). */}
                      {childOpen &&
                        row.transactions.map((txn) => (
                          <tr className="disclosure-workings" key={txn.id}>
                            <td className="secondary disclosure__grandchild">
                              <span className="mono">{formatDate(txn.date)}</span>
                              {txn.note && (
                                <span className="disclosure__note">{txn.note}</span>
                              )}
                            </td>
                            <td />
                            <td />
                            <td className="numeric secondary">
                              {formatDecimal(txn.amount)}
                            </td>
                            {/* A transaction has no month before it to have
                                moved from. The column stays empty rather than
                                showing a dash, which would read as a change
                                that could not be computed. */}
                            <td />
                          </tr>
                        ))}
                    </Fragment>
                  )
                })}
            </Fragment>
          )
        })}
      </tbody>
    </table>
  )
}

// ---------------------------------------------------------------------------

function Report({
  month,
  currency,
}: {
  readonly month: string
  readonly currency: ReportingCurrencyCode
}) {
  const report = useCategoryReport(month)
  // A second request rather than a field on the first: the report is exact and
  // per currency, the flow is translated and combined, and one endpoint
  // returning both would leave a reader checking which kind of figure they had.
  const combined = useCategoryFlow(month, currency)

  const flow = useMemo(
    () => (combined.data ? buildFlow(combined.data) : null),
    [combined.data],
  )

  return (
    <div className="cashflow__report">
      {combined.data && <CategoryFlow report={combined.data} flow={flow} />}
      {(report.data?.currencies ?? []).length === 0 ? (
        <section className="panel">
          <p className="fx__note">Nothing recorded for {month}.</p>
        </section>
      ) : (
        (report.data?.currencies ?? []).map((block) => (
          <section className="panel" key={block.currency}>
            <h2 className="panel__heading">{block.currency}</h2>
            <div className="cashflow__totals mono">
              <span>
                <span className="label">Income</span> {formatDecimal(block.income)}
              </span>
              <span>
                <span className="label">Expense</span> {formatDecimal(block.expense)}
              </span>
              <span>
                <span className="label">Net</span>{' '}
                <span className={block.net.startsWith('-') ? 'money--breach' : 'money--rise'}>
                  {formatDecimal(block.net)}
                </span>
              </span>
            </div>

            <CategoryRollup block={block} />
          </section>
        ))
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------

function Categories() {
  const categories = useCategories()
  const update = useUpdateCategory()
  const add = useAddCategory()
  const remove = useDeleteCategory()

  if (!categories.data) return <div className="boot">Loading…</div>

  return (
    <div className="cashflow__categories">
      <p className="fx__note">
        Two levels. Transactions attach to children only; parents exist for rollup. A
        category that has been used is deactivated, never deleted — it leaves the entry
        form and its history stays intact.
      </p>
      <ErrorBanner error={remove.error} />

      {categories.data.map((parent) => (
        <section className="panel" key={parent.id}>
          <h2 className="panel__heading">
            {parent.direction} → {parent.name}
          </h2>
          <table className="table">
            <tbody>
              {parent.children.map((child) => (
                <tr key={child.id}>
                  <td className={child.is_active ? '' : 'ink-30'}>{child.name}</td>
                  <td className="secondary">
                    {child.used > 0
                      ? `${child.used} transaction${child.used === 1 ? '' : 's'}`
                      : 'unused'}
                  </td>
                  <td className="secondary">{child.is_active ? '' : 'deactivated'}</td>
                  <td className="numeric">
                    <button
                      type="button"
                      className="link-button"
                      onClick={() =>
                        update.mutate({ id: child.id, is_active: !child.is_active })
                      }
                    >
                      {child.is_active ? 'Deactivate' : 'Reactivate'}
                    </button>
                    {/* Only while unused. */}
                    {child.used === 0 && (
                      <button
                        type="button"
                        className="link-button link-button--breach"
                        onClick={() => remove.mutate(child.id)}
                      >
                        Delete
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <button
            type="button"
            className="link-button"
            onClick={() => {
              const name = window.prompt(`New category under ${parent.name}`)
              if (name) add.mutate({ name, parent_id: parent.id })
            }}
          >
            + Add category
          </button>
        </section>
      ))}
    </div>
  )
}

// ---------------------------------------------------------------------------

/**
 * Recurring templates — the things that do the proposing.
 *
 * Deciding a proposal happens on Transactions, beside the ledger it lands in.
 * This tab
 * is the other half: where the templates themselves are created and ended. A
 * template is proposed, never posted (BR-14), so nothing here writes a
 * transaction.
 *
 * Ending is the only edit offered. A template's fields are not amendable — an
 * amount that has genuinely changed is a different arrangement, and ending the
 * old one leaves its confirmed history intact while the new one starts from the
 * month it actually applies to. One-off variance needs none of that: the amount
 * is adjustable at confirmation.
 */
function Recurring({ month }: { readonly month: string }) {
  const templates = useTemplates()
  const create = useCreateTemplate()
  const end = useEndTemplate()

  const defaultCurrency = useDefaultCurrency()
  const todayKey = today()

  const [form, setForm] = useState({
    name: '',
    parent_id: '',
    category_id: '',
    amount: '',
    currency: defaultCurrency as string,
    frequency: 'Monthly' as Frequency,
    // The one date that fixes the rhythm: the weekday a weekly arrangement falls
    // on, or the day of the month a monthly one does. Seeded to the first of the
    // month being worked on, which is the likeliest place to start.
    anchor_date: `${month}-01`,
  })

  function submit(event: FormEvent) {
    event.preventDefault()
    if (!form.name.trim() || !form.category_id || !form.amount.trim()) return

    create.mutate(
      {
        name: form.name,
        amount: form.amount,
        currency: form.currency,
        category_id: Number(form.category_id),
        frequency: form.frequency,
        anchor_date: form.anchor_date,
      },
      // Category, currency and frequency are kept: arrangements are often added
      // in a batch that differs only in name and amount.
      { onSuccess: () => setForm({ ...form, name: '', amount: '' }) },
    )
  }

  /**
   * Ending takes a final date, and blank means today. A date still to come is
   * allowed and is the useful case — an arrangement known to be ending keeps
   * proposing until then rather than going quiet the moment it is recorded.
   *
   * Checked here because the round trip that only teaches the user how a date is
   * spelled is a round trip wasted; the server checks it too.
   */
  function endTemplate(row: RecurringTemplate) {
    const answer = window.prompt(
      `Last date ${row.name} falls on, as YYYY-MM-DD. Blank ends it today.`,
      todayKey,
    )
    if (answer === null) return

    const trimmed = answer.trim()
    if (trimmed !== '' && !DATE_KEY.test(trimmed)) {
      window.alert('A date is written as YYYY-MM-DD — 2026-08-20.')
      return
    }

    end.mutate({ id: row.id, ...(trimmed === '' ? {} : { end_date: trimmed }) })
  }

  const rows = templates.data ?? []

  return (
    <div className="cashflow__entry">
      <section className="panel">
        <h2 className="panel__heading">Add a Recurring Item</h2>
        <ErrorBanner error={create.error} />

        <form className="recurring__form" onSubmit={submit}>
          <div className="field">
            <label className="field__label" htmlFor="tpl-name">
              Name
            </label>
            <input
              id="tpl-name"
              className="input"
              placeholder="Rent"
              value={form.name}
              onChange={(event) => setForm({ ...form, name: event.target.value })}
              required
            />
          </div>

          <CategoryFields
            idPrefix="tpl"
            value={{ parent_id: form.parent_id, category_id: form.category_id }}
            onChange={(next) => setForm({ ...form, ...next })}
          />

          <div className="field">
            <label className="field__label" htmlFor="tpl-frequency">
              Frequency
            </label>
            <select
              id="tpl-frequency"
              className="input"
              value={form.frequency}
              onChange={(event) =>
                setForm({ ...form, frequency: event.target.value as Frequency })
              }
            >
              {FREQUENCIES.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </select>
          </div>

          <div className="field">
            <label className="field__label" htmlFor="tpl-anchor">
              Anchor Date
            </label>
            <input
              id="tpl-anchor"
              type="date"
              className="input mono"
              value={form.anchor_date}
              // Ignore a cleared field, as the entry form does: an empty box is a
              // transient state of the control, not an answer.
              onChange={(event) =>
                event.target.value && setForm({ ...form, anchor_date: event.target.value })
              }
              required
            />
          </div>

          <div className="field">
            <label className="field__label" htmlFor="tpl-amount">
              Amount
            </label>
            <input
              id="tpl-amount"
              className="input mono numeric-input"
              inputMode="decimal"
              placeholder="0.00"
              value={form.amount}
              onChange={(event) => setForm({ ...form, amount: event.target.value })}
              required
            />
          </div>

          <div className="field">
            <label className="field__label" htmlFor="tpl-currency">
              Currency
            </label>
            <select
              id="tpl-currency"
              className="input mono"
              value={form.currency}
              onChange={(event) => setForm({ ...form, currency: event.target.value })}
            >
              {CURRENCIES.map((code) => (
                <option key={code} value={code}>
                  {code}
                </option>
              ))}
            </select>
          </div>

          <button type="submit" className="btn btn--primary" disabled={create.isPending}>
            Add
          </button>
        </form>
      </section>

      <section className="panel cashflow__list">
        <h2 className="panel__heading">Recurring Items</h2>
        <ErrorBanner error={end.error} />

        {rows.length === 0 ? (
          <p className="fx__note">Nothing recurring yet.</p>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Category</th>
                <th>Subcategory</th>
                <th>Frequency</th>
                <th>Anchor</th>
                <th>Ends</th>
                <th className="numeric">Amount</th>
                <th aria-label="Actions" />
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id}>
                  <td>{row.name}</td>
                  <td className="secondary">{row.parent}</td>
                  <td>{row.category}</td>
                  <td className="secondary">{row.frequency}</td>
                  <td className="mono">{formatDate(row.anchor_date)}</td>
                  {/* An ended template says so here rather than in a status
                      column of its own: the date it stopped is the useful fact,
                      and there is nothing to state while it is still running. */}
                  <td className="mono secondary">
                    {row.end_date ? formatDate(row.end_date) : '—'}
                  </td>
                  <td className="numeric">
                    <span
                      className={row.direction === 'Income' ? 'money money--rise' : 'money'}
                    >
                      {row.direction === 'Income' ? '+' : '−'}
                      {formatDecimal(row.amount)}
                      <span className="money__code">{row.currency}</span>
                    </span>
                  </td>
                  <td>
                    {/* Hard against the right edge, like the register's own
                        actions column: the last thing on the row is the thing
                        that acts on it. */}
                    <div className="cashflow__actions">
                      {row.is_active ? (
                        <button
                          type="button"
                          className="link-button link-button--breach"
                          onClick={() => endTemplate(row)}
                          disabled={end.isPending}
                        >
                          End
                        </button>
                      ) : (
                        <span className="secondary">ended</span>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  )
}

// ---------------------------------------------------------------------------

export function CashFlow() {
  // The month lives in the URL and is chosen on the spine, the currency in the
  // URL and chosen in the header — this screen reads both and sets neither.
  const { month, currency } = useViewState()
  const [tab, setTab] = useState<Tab>('transactions')

  return (
    <div className="cashflow">
      <div className="seg cashflow__tabs" role="group" aria-label="Cash flow tabs">
        {TABS.map((option) => (
          <button
            key={option.key}
            type="button"
            className={`seg__option${tab === option.key ? ' seg__option--on' : ''}`}
            aria-pressed={tab === option.key}
            onClick={() => setTab(option.key)}
          >
            {option.label}
          </button>
        ))}
      </div>

      {tab === 'transactions' && <Transactions month={month} currency={currency} />}
      {tab === 'report' && <Report month={month} currency={currency} />}
      {tab === 'recurring' && <Recurring month={month} />}
      {tab === 'categories' && <Categories />}
    </div>
  )
}
