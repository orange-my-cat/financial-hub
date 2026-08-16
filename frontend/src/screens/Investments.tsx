/**
 * Investments — holdings, the open-lot FIFO queue, entry, and realised gains.
 *
 * Every figure stays in its holding's own currency. This is the one screen the
 * reporting-currency toggle does not apply to, and it says so in the subhead.
 *
 * **The open-lot queue gets a full column**, because it is the thing that makes
 * cost basis legible — a list of purchase dates with what remains of each and
 * what that remainder cost. Without it, "cost basis" is a number the user has
 * to take on trust.
 *
 * Two prohibitions are stated in copy here, not merely implemented:
 *
 *   * **Unrealised gain does not exist in this system.** No market prices are
 *     held, so there is no paper gain, no portfolio return percentage and no
 *     total return anywhere.
 *   * **Estimated tax is a percentage you typed, not a calculation.** No
 *     jurisdiction's rules are applied, and every net figure is indicative.
 *
 * A holding invalidated by a historic edit is **flagged, never blocked** — the
 * advisory names the offending sale, the figures still display, and entry still
 * works.
 */

import { useState, type FormEvent } from 'react'

import { ErrorBanner } from '@/components/Advisories'
import { useAccounts } from '@/lib/accounts'
import { formatDate, formatDecimal } from '@/lib/format'
import { useDefaultCurrency } from '@/lib/fx'
import {
  INSTRUMENT_TYPES,
  useCreateHolding,
  useHoldings,
  useRealisedGains,
  useRecordInvestment,
  useUpdateHolding,
  type InvestmentAction,
  type Position,
} from '@/lib/investments'
import { CURRENCIES } from '@/lib/money'

const ACTIONS: readonly InvestmentAction[] = [
  'Buy',
  'Sell',
  'Split',
  'Distribution',
  'Reinvestment',
]

function today(): string {
  return new Date().toISOString().slice(0, 10)
}

// ---------------------------------------------------------------------------

function LotQueue({ position }: { readonly position: Position }) {
  if (position.lots.length === 0) {
    return <p className="fx__note">No open lots.</p>
  }

  return (
    <table className="table">
      <thead>
        <tr>
          <th>Acquired</th>
          <th className="numeric">Remaining</th>
          <th className="numeric">Unit cost</th>
          <th className="numeric">Cost basis</th>
        </tr>
      </thead>
      <tbody>
        {position.lots.map((lot) => (
          <tr key={lot.transaction_id}>
            <td className="mono">
              {formatDate(lot.acquired)}
              {lot.from_reinvestment && (
                <sup className="mark mark--carried" title="From a reinvestment">
                  r
                </sup>
              )}
            </td>
            <td className="numeric">{formatDecimal(lot.remaining_quantity, 4)}</td>
            <td className="numeric">{formatDecimal(lot.unit_cost, 4)}</td>
            <td className="numeric">{formatDecimal(lot.remaining_cost)}</td>
          </tr>
        ))}
        <tr className="table__total">
          <td>Total</td>
          <td className="numeric">{formatDecimal(position.total_quantity, 4)}</td>
          <td />
          <td className="numeric">
            {formatDecimal(position.total_cost_basis)}
            <span className="money__code">{position.currency}</span>
          </td>
        </tr>
      </tbody>
    </table>
  )
}

// ---------------------------------------------------------------------------

function TransactionForm({ holdings }: { readonly holdings: readonly Position[] }) {
  const record = useRecordInvestment()
  const [form, setForm] = useState({
    holdingId: '',
    action: 'Buy' as InvestmentAction,
    date: today(),
    quantity: '',
    unit_price: '',
    fees: '',
    split_ratio: '',
    cash_amount: '',
  })

  const needsQuantity = ['Buy', 'Sell', 'Reinvestment'].includes(form.action)
  const needsRatio = form.action === 'Split'
  const needsCash = form.action === 'Distribution'

  function submit(event: FormEvent) {
    event.preventDefault()
    if (!form.holdingId) return

    record.mutate(
      {
        holdingId: Number(form.holdingId),
        action: form.action,
        date: form.date,
        quantity: form.quantity || '0',
        unit_price: form.unit_price || '0',
        fees: form.fees || '0',
        split_ratio: form.split_ratio || '0',
        cash_amount: form.cash_amount || '0',
      },
      { onSuccess: () => setForm({ ...form, quantity: '', unit_price: '', fees: '' }) },
    )
  }

  return (
    <section className="panel">
      <h2 className="panel__heading">Record a Transaction</h2>
      <p className="fx__note">
        Corporate actions are limited to fees, splits and reinvestment. Mergers,
        spin-offs, rights issues and returns of capital are out of scope — representing
        one by hand as a sale and a purchase will not reflect the true event.
      </p>

      <ErrorBanner error={record.error} />

      <div className="seg invest__actions" role="group" aria-label="Action">
        {ACTIONS.map((action) => (
          <button
            key={action}
            type="button"
            className={`seg__option${form.action === action ? ' seg__option--on' : ''}`}
            aria-pressed={form.action === action}
            onClick={() => setForm({ ...form, action })}
          >
            {action}
          </button>
        ))}
      </div>

      <form className="invest__form" onSubmit={submit}>
        <div className="field">
          <label className="field__label" htmlFor="inv-holding">
            Holding
          </label>
          <select
            id="inv-holding"
            className="input"
            value={form.holdingId}
            onChange={(event) => setForm({ ...form, holdingId: event.target.value })}
            required
          >
            <option value="">Choose…</option>
            {holdings.map((holding) => (
              <option key={holding.id} value={holding.id}>
                {holding.name} ({holding.currency})
              </option>
            ))}
          </select>
        </div>

        <div className="field">
          <label className="field__label" htmlFor="inv-date">
            Date
          </label>
          <input
            id="inv-date"
            type="date"
            className="input mono"
            value={form.date}
            onChange={(event) => setForm({ ...form, date: event.target.value })}
          />
        </div>

        {needsQuantity && (
          <>
            <div className="field">
              <label className="field__label" htmlFor="inv-quantity">
                Quantity
              </label>
              <input
                id="inv-quantity"
                className="input mono numeric-input"
                inputMode="decimal"
                value={form.quantity}
                onChange={(event) => setForm({ ...form, quantity: event.target.value })}
              />
            </div>
            <div className="field">
              <label className="field__label" htmlFor="inv-price">
                Unit price
              </label>
              <input
                id="inv-price"
                className="input mono numeric-input"
                inputMode="decimal"
                value={form.unit_price}
                onChange={(event) => setForm({ ...form, unit_price: event.target.value })}
              />
            </div>
            <div className="field">
              <label className="field__label" htmlFor="inv-fees">
                Fees
              </label>
              <input
                id="inv-fees"
                className="input mono numeric-input"
                inputMode="decimal"
                value={form.fees}
                onChange={(event) => setForm({ ...form, fees: event.target.value })}
              />
              <span className="fx__note">
                {form.action === 'Sell'
                  ? 'Deducted from proceeds.'
                  : 'Added to cost basis.'}
              </span>
            </div>
          </>
        )}

        {needsRatio && (
          <div className="field">
            <label className="field__label" htmlFor="inv-ratio">
              Ratio
            </label>
            <input
              id="inv-ratio"
              className="input mono numeric-input"
              inputMode="decimal"
              placeholder="2"
              value={form.split_ratio}
              onChange={(event) => setForm({ ...form, split_ratio: event.target.value })}
            />
            <span className="fx__note">2 for a 2:1 split, 0.1 for a 1:10 consolidation.</span>
          </div>
        )}

        {needsCash && (
          <div className="field">
            <label className="field__label" htmlFor="inv-cash">
              Cash received
            </label>
            <input
              id="inv-cash"
              className="input mono numeric-input"
              inputMode="decimal"
              value={form.cash_amount}
              onChange={(event) => setForm({ ...form, cash_amount: event.target.value })}
            />
          </div>
        )}

        <button type="submit" className="btn btn--primary" disabled={record.isPending}>
          Record
        </button>
      </form>
    </section>
  )
}

// ---------------------------------------------------------------------------

function NewHolding() {
  const accounts = useAccounts()
  const create = useCreateHolding()
  // Seeds the field only. A holding's currency is a fact about the instrument,
  // and once chosen it is not the default's to revise.
  const defaultCurrency = useDefaultCurrency()
  const [form, setForm] = useState({
    name: '',
    symbol: '',
    instrument_type: 'Equity',
    currency: defaultCurrency as string,
    account_id: '',
    estimated_tax_percent: '',
  })

  const investmentAccounts = (accounts.data ?? []).filter(
    (account) => account.status !== 'Closed',
  )

  function submit(event: FormEvent) {
    event.preventDefault()
    if (!form.account_id) return
    create.mutate(
      {
        name: form.name,
        symbol: form.symbol,
        instrument_type: form.instrument_type,
        currency: form.currency,
        account_id: Number(form.account_id),
        estimated_tax_percent: form.estimated_tax_percent || null,
      },
      { onSuccess: () => setForm({ ...form, name: '', symbol: '' }) },
    )
  }

  return (
    <section className="panel">
      <h2 className="panel__heading">Add a Holding</h2>
      <p className="fx__note">
        A holding belongs to one account and cannot be moved. The same instrument at two
        brokers is two holdings with independent FIFO queues.
      </p>
      <ErrorBanner error={create.error} />

      <form className="invest__form" onSubmit={submit}>
        <div className="field">
          <label className="field__label" htmlFor="hold-name">
            Name
          </label>
          <input
            id="hold-name"
            className="input"
            value={form.name}
            onChange={(event) => setForm({ ...form, name: event.target.value })}
            required
          />
        </div>
        <div className="field">
          <label className="field__label" htmlFor="hold-symbol">
            Symbol
          </label>
          <input
            id="hold-symbol"
            className="input mono"
            value={form.symbol}
            onChange={(event) => setForm({ ...form, symbol: event.target.value })}
          />
        </div>
        <div className="field">
          <label className="field__label" htmlFor="hold-type">
            Type
          </label>
          <select
            id="hold-type"
            className="input"
            value={form.instrument_type}
            onChange={(event) => setForm({ ...form, instrument_type: event.target.value })}
          >
            {INSTRUMENT_TYPES.map((type) => (
              <option key={type} value={type}>
                {type}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label className="field__label" htmlFor="hold-currency">
            Currency
          </label>
          <select
            id="hold-currency"
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
        <div className="field">
          <label className="field__label" htmlFor="hold-account">
            Account
          </label>
          <select
            id="hold-account"
            className="input"
            value={form.account_id}
            onChange={(event) => setForm({ ...form, account_id: event.target.value })}
            required
          >
            <option value="">Choose…</option>
            {investmentAccounts.map((account) => (
              <option key={account.id} value={account.id}>
                {account.name}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label className="field__label" htmlFor="hold-tax">
            Estimated tax %
          </label>
          <input
            id="hold-tax"
            className="input mono numeric-input"
            inputMode="decimal"
            value={form.estimated_tax_percent}
            onChange={(event) =>
              setForm({ ...form, estimated_tax_percent: event.target.value })
            }
          />
        </div>
        <button type="submit" className="btn btn--primary" disabled={create.isPending}>
          Add
        </button>
      </form>
    </section>
  )
}

// ---------------------------------------------------------------------------

export function Investments() {
  const holdings = useHoldings()
  const gains = useRealisedGains()
  const update = useUpdateHolding()

  if (holdings.isPending) return <div className="boot">Loading…</div>
  if (!holdings.data) return <ErrorBanner error={holdings.error} />

  const { holdings: positions, prohibitions } = holdings.data

  return (
    <div className="invest">
      <p className="screen__subhead">
        Every figure is in its holding’s own currency and is never translated. The
        reporting currency does not apply to this screen.
      </p>

      {/* Stated in copy, not merely implemented. */}
      <div className="prohibitions">
        <p>{prohibitions.unrealised_gain}</p>
        <p>{prohibitions.estimated_tax}</p>
      </div>

      {positions.length === 0 ? (
        <section className="panel">
          <p className="fx__note">No holdings yet.</p>
        </section>
      ) : (
        positions.map((position) => (
          <section className="panel invest__holding" key={position.id}>
            <div className="invest__head">
              <div>
                <h2 className="panel__heading">
                  {position.name}{' '}
                  {position.symbol && <span className="secondary mono">{position.symbol}</span>}
                </h2>
                <div className="secondary">
                  {position.instrument_type} · {position.account} ·{' '}
                  <span className="mono">{position.currency}</span> · {position.lot_count} lot
                  {position.lot_count === 1 ? '' : 's'}
                </div>
              </div>

              <label className="invest__tax">
                <span className="label">Est. tax %</span>
                <input
                  className="input mono"
                  inputMode="decimal"
                  defaultValue={position.estimated_tax_percent ?? ''}
                  onBlur={(event) =>
                    update.mutate({
                      id: position.id,
                      estimated_tax_percent: event.target.value || null,
                    })
                  }
                />
              </label>
            </div>

            {/* Flagged, never blocked. Figures still display below. */}
            {!position.consistent &&
              position.inconsistencies.map((problem) => (
                <div className="advisory" key={problem.transaction_id} role="status">
                  <span className="advisory__label">Advisory · Retroactively invalid</span>
                  <span className="advisory__body">{problem.message}</span>
                </div>
              ))}

            <LotQueue position={position} />
          </section>
        ))
      )}

      <TransactionForm holdings={positions} />
      <NewHolding />

      <section className="panel">
        <h2 className="panel__heading">Realised Gains</h2>
        <p className="fx__note">
          Grouped by currency and never summed across them. Net figures are indicative
          estimates using the percentage you typed.
        </p>

        {(gains.data?.currencies ?? []).length === 0 ? (
          <p className="fx__note">No sales recorded.</p>
        ) : (
          (gains.data?.currencies ?? []).map((block) => (
            <div key={block.currency} className="invest__gains">
              <h3 className="invest__gains-heading mono">{block.currency}</h3>
              <table className="table">
                <thead>
                  <tr>
                    <th>Sale date</th>
                    <th>Holding</th>
                    <th className="numeric">Proceeds</th>
                    <th className="numeric">Fees</th>
                    <th className="numeric">Cost basis</th>
                    <th className="numeric">Gross gain</th>
                    <th className="numeric">Est. tax</th>
                    <th className="numeric">Net gain</th>
                  </tr>
                </thead>
                <tbody>
                  {block.sales.map((sale) => (
                    <tr key={sale.transaction_id}>
                      <td className="mono">{formatDate(sale.date)}</td>
                      <td>{sale.holding}</td>
                      <td className="numeric">{formatDecimal(sale.proceeds)}</td>
                      <td className="numeric secondary">{formatDecimal(sale.fees)}</td>
                      <td className="numeric">{formatDecimal(sale.cost_basis)}</td>
                      <td className="numeric">
                        <span className={sale.is_loss ? 'money money--breach' : 'money money--rise'}>
                          {formatDecimal(sale.realised_gain)}
                        </span>
                      </td>
                      <td className="numeric secondary">
                        {/* Losses are shown gross; no percentage is applied. */}
                        {sale.tax_applied ? `${sale.estimated_tax_percent}%` : '—'}
                      </td>
                      <td className="numeric">
                        {formatDecimal(sale.net_realised_gain)}
                        {sale.tax_applied && <span className="indicative"> indicative</span>}
                      </td>
                    </tr>
                  ))}
                  <tr className="table__total">
                    <td>Total, {block.currency} only</td>
                    <td colSpan={4} />
                    <td className="numeric">{formatDecimal(block.gross)}</td>
                    <td />
                    <td className="numeric">
                      {formatDecimal(block.net)}
                      {block.tax_applied && <span className="indicative"> indicative</span>}
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          ))
        )}
      </section>
    </div>
  )
}
