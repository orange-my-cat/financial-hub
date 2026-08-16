/**
 * Cash flow — Entry, Category report, Categories.
 *
 * Entry is manual and per-transaction; there is no import path, so entry speed
 * is the whole battle. The probable-duplicate advisory appears below the form
 * and adding anyway is always permitted — two identical amounts on one day are
 * ordinary.
 *
 * Two prohibitions are stated in copy on this screen rather than merely
 * implemented:
 *
 *   * **There is no transfer affordance anywhere.** Moving money between your
 *     own accounts is not a transaction and shows only as two balance changes
 *     at the next close (BR-11).
 *   * **No figure here is ever added to a balance figure** (BR-12). The
 *     category report is per currency and never translated, because a month's
 *     groceries in MYR and a month's rent in AUD are two separate facts.
 */

import { useMemo, useState, type FormEvent } from 'react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import { AdvisoryList, ErrorBanner } from '@/components/Advisories'
import { type Advisory } from '@/lib/api'
import {
  useAddCategory,
  useCategories,
  useCategoryReport,
  useCategoryTrend,
  useConfirmProposal,
  useDeleteCategory,
  useDeleteTransaction,
  useDismissProposal,
  useProposals,
  useRecordTransaction,
  useTransactions,
  useUpdateCategory,
} from '@/lib/cashflow'
import { formatDate, formatDecimal } from '@/lib/format'
import { useDefaultCurrency } from '@/lib/fx'
import { CURRENCIES } from '@/lib/money'
import { useViewState } from '@/lib/viewState'

type Tab = 'entry' | 'report' | 'categories'

const TABS: readonly { key: Tab; label: string }[] = [
  { key: 'entry', label: 'Entry' },
  { key: 'report', label: 'Category Report' },
  { key: 'categories', label: 'Categories' },
]

/** The standing note. It exists because the absence needs explaining. */
function TransferNote() {
  return (
    <p className="fx__note transfer-note">
      Moving money between your own accounts is not a transaction and has no record here.
      It shows only as two balance changes at the next close.
    </p>
  )
}

// ---------------------------------------------------------------------------

function Entry({ month }: { readonly month: string }) {
  const categories = useCategories()
  const transactions = useTransactions(month)
  const proposals = useProposals()
  const record = useRecordTransaction()
  const remove = useDeleteTransaction()
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
    category_id: '',
    note: '',
  })

  const children = useMemo(
    () =>
      (categories.data ?? []).flatMap((parent) =>
        parent.children
          .filter((child) => child.is_active)
          .map((child) => ({ ...child, parentName: parent.name })),
      ),
    [categories.data],
  )

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
              onChange={(event) => setForm({ ...form, date: event.target.value })}
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

          <div className="field cashflow__category">
            <label className="field__label" htmlFor="txn-category">
              Category
            </label>
            <select
              id="txn-category"
              className="input"
              value={form.category_id}
              onChange={(event) => setForm({ ...form, category_id: event.target.value })}
              required
            >
              <option value="">Choose…</option>
              {children.map((child) => (
                <option key={child.id} value={child.id}>
                  {child.parentName} → {child.name}
                </option>
              ))}
            </select>
          </div>

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

          <button type="submit" className="btn btn--primary" disabled={record.isPending}>
            Add
          </button>
        </form>

        {/* Adding anyway is always permitted. */}
        <AdvisoryList advisories={advisories} />
        <TransferNote />
      </section>

      <section className="panel">
        <h2 className="panel__heading">Recurring Proposals</h2>
        <p className="fx__note">
          Proposed each period, never posted automatically. The amount is adjustable at
          confirmation, and a confirmed transaction is thereafter independent of its
          template.
        </p>

        {(proposals.data ?? []).length === 0 ? (
          <p className="fx__note">Nothing awaiting confirmation.</p>
        ) : (
          <div className="proposals">
            {(proposals.data ?? []).map((proposal) => (
              <div className="proposal" key={`${proposal.template_id}-${proposal.period}`}>
                <div className="proposal__head">
                  <span>{proposal.name}</span>
                  <span className="mono secondary">{proposal.period}</span>
                </div>
                <div className="proposal__amount mono">
                  {formatDecimal(proposal.amount)}
                  <span className="money__code">{proposal.currency}</span>
                </div>
                <div className="secondary">{proposal.category}</div>
                <div className="proposal__actions">
                  <button
                    type="button"
                    className="btn btn--primary"
                    onClick={() =>
                      confirm.mutate({
                        template_id: proposal.template_id,
                        period: proposal.period,
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
                          period: proposal.period,
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
                        period: proposal.period,
                      })
                    }
                  >
                    Skip
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="panel cashflow__list">
        <h2 className="panel__heading">Transactions in {month}</h2>
        {(transactions.data ?? []).length === 0 ? (
          <p className="fx__note">Nothing recorded for this month.</p>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>Date</th>
                <th>Category</th>
                <th>Note</th>
                <th className="numeric">Amount</th>
                <th aria-label="Actions" />
              </tr>
            </thead>
            <tbody>
              {(transactions.data ?? []).map((row) => (
                <tr key={row.id}>
                  <td className="mono">{formatDate(row.date)}</td>
                  <td>
                    <span className="secondary">{row.parent} → </span>
                    {row.category}
                  </td>
                  <td className="secondary">{row.note}</td>
                  <td className="numeric">
                    <span className={row.direction === 'Income' ? 'money money--rise' : 'money'}>
                      {row.direction === 'Income' ? '+' : '−'}
                      {formatDecimal(row.amount)}
                      <span className="money__code">{row.currency}</span>
                    </span>
                  </td>
                  <td className="numeric">
                    <button
                      type="button"
                      className="link-button link-button--breach"
                      onClick={() => remove.mutate(row.id)}
                    >
                      Delete
                    </button>
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

function Report({ month, from, to }: { readonly month: string; readonly from: string; readonly to: string }) {
  const report = useCategoryReport(month)
  const trend = useCategoryTrend(from, to)

  const chart = useMemo(() => {
    if (!trend.data) return []
    return trend.data.months.map((m, index) => {
      const row: Record<string, string | number> = { month: m }
      for (const series of trend.data!.series) {
        row[`${series.currency} ${series.direction}`] = Number(series.points[index] ?? '0')
      }
      return row
    })
  }, [trend.data])

  const seriesKeys = useMemo(
    () => (trend.data?.series ?? []).map((s) => `${s.currency} ${s.direction}`),
    [trend.data],
  )

  return (
    <div className="cashflow__report">
      <p className="fx__note">
        Amounts stay in the currency they were entered in and are never translated. No
        figure on this screen is ever added to an account balance.
      </p>

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

            <table className="table">
              <thead>
                <tr>
                  <th>Parent</th>
                  <th>Category</th>
                  <th>Direction</th>
                  <th className="numeric">Total</th>
                  <th className="numeric">Count</th>
                </tr>
              </thead>
              <tbody>
                {block.children.map((row) => (
                  <tr key={row.category_id}>
                    <td className="secondary">{row.parent}</td>
                    <td>{row.category}</td>
                    <td className="secondary">{row.direction}</td>
                    <td className="numeric">{formatDecimal(row.total)}</td>
                    <td className="numeric secondary">{row.count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        ))
      )}

      {chart.length > 0 && (
        <section className="panel">
          <h2 className="panel__heading">Trend</h2>
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={chart} margin={{ top: 8, right: 8, bottom: 8, left: 8 }}>
              <CartesianGrid stroke="rgba(233,233,237,.06)" vertical={false} />
              <XAxis
                dataKey="month"
                tick={{ fill: 'rgba(233,233,237,.45)', fontSize: 11 }}
                tickLine={false}
              />
              <YAxis
                tick={{ fill: 'rgba(233,233,237,.45)', fontSize: 11 }}
                tickLine={false}
                axisLine={false}
                width={72}
              />
              <Tooltip
                contentStyle={{
                  background: '#232532',
                  border: '1px solid rgba(233,233,237,.16)',
                  borderRadius: 8,
                  fontSize: 12,
                }}
              />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              {seriesKeys.map((key, index) => (
                <Bar
                  key={key}
                  dataKey={key}
                  fill={index % 2 === 0 ? '#6fae90' : '#d1756a'}
                  isAnimationActive={false}
                />
              ))}
            </BarChart>
          </ResponsiveContainer>
        </section>
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

export function CashFlow() {
  // The month lives in the URL, not here, so this field and the spine are two
  // faces of one value rather than two copies that drift apart.
  const { from, to, month, setMonth } = useViewState()
  const [tab, setTab] = useState<Tab>('entry')

  return (
    <div className="cashflow">
      <p className="screen__subhead">
        Obeys the date range. The reporting currency does not apply — cash flow stays in
        the currency each transaction was entered in.
      </p>

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

        {tab !== 'categories' && (
          <label className="cashflow__month">
            <span className="label">Month</span>
            <input
              type="month"
              className="input mono"
              value={month}
              // Ignore a cleared field. It is a transient state of the input,
              // and writing it through would put an empty month in the URL.
              onChange={(event) => event.target.value && setMonth(event.target.value)}
            />
          </label>
        )}
      </div>

      {tab === 'entry' && <Entry month={month} />}
      {tab === 'report' && <Report month={month} from={from} to={to} />}
      {tab === 'categories' && <Categories />}
    </div>
  )
}
