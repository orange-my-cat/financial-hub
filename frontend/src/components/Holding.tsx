/**
 * The two pieces of a holding's own page: its open lots, and entry.
 *
 * Kept out of the screen file because neither is about the page's layout — one
 * is the shape the FIFO queue is always drawn in, the other is the only place in
 * the application where an investment transaction is written.
 *
 * `LotQueue` is the open FIFO queue — the thing that makes cost basis legible,
 * a list of purchase dates with what remains of each and what that remainder
 * cost. Without it "cost basis" is a number the user has to take on trust.
 *
 * `RecordTransaction` is entry, and it lives on **one** screen: the holding's
 * own page. There is no holding picker, because there is nothing to pick — the
 * page is already about one holding, and the transaction is recorded against
 * the holding whose workings are on screen above the form.
 *
 * It sat on the register too, with a picker, which is what the design handoff
 * asks for. The Product Owner moved it here. The cost is real and worth naming:
 * a close that touches four holdings is now four page visits rather than four
 * uses of one form, and entry speed during the close is the primary failure
 * mode this application is designed around. What it buys is that a transaction
 * cannot be recorded against the wrong holding, because no holding is ever
 * chosen from a list.
 */

import { useState, type FormEvent } from 'react'

import { ErrorBanner } from '@/components/Advisories'
import { formatDate, formatDecimal } from '@/lib/format'
import {
  useRecordInvestment,
  type InvestmentAction,
  type Position,
} from '@/lib/investments'

/**
 * Four actions, and Reinvestment is the combined one: the cash a distribution
 * paid and the units it bought, entered once. A distribution taken as cash has
 * no action here at all — the cash reaches an account and shows up in that
 * account's balance at the next close, which is where every other movement of
 * money into an account shows up (BR-01).
 */
const ACTIONS: readonly InvestmentAction[] = ['Buy', 'Sell', 'Split', 'Reinvestment']

function today(): string {
  return new Date().toISOString().slice(0, 10)
}

// ---------------------------------------------------------------------------

export function LotQueue({ position }: { readonly position: Position }) {
  if (position.lots.length === 0) {
    return <p className="fx__note">No open lots.</p>
  }

  return (
    <table className="table">
      <thead>
        <tr>
          <th>Acquired</th>
          <th className="numeric">Remaining</th>
          <th className="numeric">Unit Cost</th>
          <th className="numeric">Cost Basis</th>
        </tr>
      </thead>
      <tbody>
        {/* A lot from a reinvestment is named by the colour of the whole row,
            which is the colour Reinvestment wears in the register on the same
            page — the `r` superscript that used to say it is gone at the Product
            Owner's instruction. The title survives it: colour alone would leave
            the fact unreadable without hue, and this is the one mark on the page
            with no word beside it. */}
        {position.lots.map((lot) => (
          <tr
            key={lot.transaction_id}
            className={lot.from_reinvestment ? 'lot--reinvested' : undefined}
            title={lot.from_reinvestment ? 'From a reinvestment' : undefined}
          >
            <td className="mono">{formatDate(lot.acquired)}</td>
            <td className="numeric">{formatDecimal(lot.remaining_quantity, 4)}</td>
            <td className="numeric">{formatDecimal(lot.unit_cost, 4)}</td>
            <td className="numeric">{formatDecimal(lot.remaining_cost)}</td>
          </tr>
        ))}
        {/* No total row. Both of its figures are stated elsewhere on the page —
            units held and cost basis in the figure column beside the plot, and
            the running unit total in the transaction register below — so a third
            copy here was a figure to reconcile rather than to read. Removed at
            the Product Owner's instruction. */}
      </tbody>
    </table>
  )
}

// ---------------------------------------------------------------------------

export function RecordTransaction({ holding }: { readonly holding: Position }) {
  const record = useRecordInvestment()
  const [form, setForm] = useState({
    action: 'Buy' as InvestmentAction,
    date: today(),
    amount: '',
    quantity: '',
    unit_price: '',
    fees: '',
    split_ratio: '',
    cash_amount: '',
  })

  /*
   * Acquiring is entered by dollar value; disposing is entered by units.
   *
   * That asymmetry is the paperwork's, not this form's. A confirmation says what
   * was paid and at what price, and a DRP statement says what the distribution
   * was worth — the fractional unit count is the result of the trade and nobody
   * types `0.4588502067`. A sale is the other way round: units are what is
   * chosen and the proceeds follow.
   *
   * The server derives the units from the money and the price, once (ADR-12 —
   * the browser has no arithmetic on money, and a division done here would be
   * a second definition of what a purchase bought).
   */
  const needsAmount = form.action === 'Buy'
  const needsQuantity = form.action === 'Sell'
  const needsPrice = ['Buy', 'Sell', 'Reinvestment'].includes(form.action)
  const needsRatio = form.action === 'Split'
  // The one figure a reinvestment is entered by: the income the holding paid,
  // which is also what bought the units.
  const needsCash = form.action === 'Reinvestment'

  function submit(event: FormEvent) {
    event.preventDefault()

    record.mutate(
      {
        holdingId: holding.id,
        action: form.action,
        date: form.date,
        amount: form.amount || '0',
        quantity: form.quantity || '0',
        unit_price: form.unit_price || '0',
        fees: form.fees || '0',
        split_ratio: form.split_ratio || '0',
        cash_amount: form.cash_amount || '0',
      },
      {
        onSuccess: () =>
          setForm({ ...form, amount: '', quantity: '', unit_price: '', fees: '', cash_amount: '' }),
      },
    )
  }

  return (
    <section className="panel">
      {/* No holding named in the heading: the page is titled with it. */}
      <h2 className="panel__heading">Record a Transaction</h2>
      {/* The scope note that stood here — corporate actions are limited to fees,
          splits and reinvestment, and a merger, spin-off, rights issue or return
          of capital hand-represented as a sale and a purchase will not reflect
          the true event — was removed at the Product Owner's instruction. The
          limit is unchanged: the action list below is the whole of it, and the
          API accepts nothing else. */}

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
        <div className="field field--date">
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

        {needsAmount && (
          <div className="field">
            {/* Not "Amount paid": fees sit in their own field beside this one
                and are added to cost basis on top of it (BR-16), so the total
                paid is this plus those. */}
            <label className="field__label" htmlFor="inv-amount">
              Amount
            </label>
            <input
              id="inv-amount"
              className="input mono numeric-input"
              inputMode="decimal"
              value={form.amount}
              onChange={(event) => setForm({ ...form, amount: event.target.value })}
            />
          </div>
        )}

        {needsCash && (
          <div className="field">
            <label className="field__label" htmlFor="inv-cash">
              Cash distributed
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

        {needsQuantity && (
          <div className="field">
            <label className="field__label" htmlFor="inv-quantity">
              Units sold
            </label>
            <input
              id="inv-quantity"
              className="input mono numeric-input"
              inputMode="decimal"
              value={form.quantity}
              onChange={(event) => setForm({ ...form, quantity: event.target.value })}
            />
          </div>
        )}

        {needsPrice && (
          <>
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
          </div>
        )}

        <button type="submit" className="btn btn--primary" disabled={record.isPending}>
          Record
        </button>
      </form>
    </section>
  )
}
