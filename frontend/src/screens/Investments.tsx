/**
 * Investments — the register of holdings, entry, and realised gains.
 *
 * Built as Accounts is: a register whose first column is a link, and one
 * subpage per row where that row's history is read *and written*. A holding's
 * name opens its transaction breakdown — every buy, sale, split, distribution
 * and reinvestment, with what the replay engine made of each — and the form that
 * records the next one.
 *
 * So this screen creates holdings and lists them, and records nothing. The
 * design handoff puts buy/sell entry here with a holding picker; the Product
 * Owner moved it to the holding's page, where there is no holding to pick.
 *
 * **A departure from the design handoff, and a deliberate one.** The handoff
 * gives the open-lot FIFO queue a full column on this screen, one block per
 * holding. That does not survive a portfolio of any size: eight holdings became
 * eight stacked tables and the screen stopped answering "what do I hold" in
 * favour of answering "what is in every lot of everything". The queue moved to
 * the holding's own page, where it sits beside the register it explains, and
 * this screen states cost basis and lot count per row so the figure is still
 * one click from its workings.
 *
 * Every figure stays in its holding's own currency; the reporting-currency
 * toggle does not apply. The subhead that said so, and the two prohibition
 * paragraphs the BRD requires in copy, were removed at the Product Owner's
 * instruction — see the comment where they stood. Both prohibitions are still
 * stated on a holding's own page, beside the figures they govern.
 *
 * **Edit opens the row's editable facts**: name, symbol, instrument type and the
 * estimated tax percentage. Not the account and not the currency — a holding is
 * scoped to one account as a one-way door, and its currency is the one every
 * figure beside it is stated in. The API declines both, so this is a rule rather
 * than a screen that happens not to offer them.
 *
 * A holding invalidated by a historic edit is **flagged, never blocked** — the
 * advisory appears under its row, the figures still display, and entry still
 * works.
 */

import { useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'

import { ErrorBanner } from '@/components/Advisories'
import { useAccounts } from '@/lib/accounts'
import { formatDecimal } from '@/lib/format'
import { useDefaultCurrency } from '@/lib/fx'
import {
  INSTRUMENT_TYPES,
  useCreateHolding,
  useDeleteHolding,
  useHoldings,
  useUpdateHolding,
  type Position,
} from '@/lib/investments'
import { CURRENCIES } from '@/lib/money'
import { icons } from '@/shell/icons'

// ---------------------------------------------------------------------------

function HoldingRow({ position }: { readonly position: Position }) {
  const update = useUpdateHolding()
  const remove = useDeleteHolding()
  const [editing, setEditing] = useState(false)

  /**
   * Saved on blur, and only where something changed.
   *
   * Every figure in this system is computed on read, so a request per keystroke
   * would refetch the register — and each holding's whole replayed position
   * with it — once per character. An idle blur is not an edit and sends
   * nothing.
   */
  function edit(field: 'name' | 'symbol' | 'estimated_tax_percent', value: string) {
    const trimmed = value.trim()

    // The percentage clears to null, which is a meaning: no estimate has been
    // given and the net figure equals the gross. A name clears to nothing at
    // all, so an empty one is a mis-swipe rather than an instruction.
    if (field === 'estimated_tax_percent') {
      if (trimmed === (position.estimated_tax_percent ?? '')) return
      update.mutate({ id: position.id, estimated_tax_percent: trimmed || null })
      return
    }

    if (field === 'name' && trimmed === '') return
    if (trimmed === position[field]) return
    update.mutate({ id: position.id, [field]: trimmed })
  }

  return (
    <>
      <tr>
        <td>
          {editing ? (
            <div className="invest__edit">
              {/* Sized by the flex row, not by `input--cell`: these two share
                  a cell, so neither of them is the width of it. */}
              <input
                className="input input--grid invest__edit-name"
                defaultValue={position.name}
                aria-label="Holding name"
                onBlur={(event) => edit('name', event.target.value)}
              />
              <input
                className="input input--grid mono invest__edit-symbol"
                defaultValue={position.symbol}
                aria-label="Symbol"
                onBlur={(event) => edit('symbol', event.target.value)}
              />
            </div>
          ) : (
            <>
              <Link to={`/investments/${position.id}`}>{position.name}</Link>
              {/* The symbol as a chip, because that is what it is: a short fixed
                  label that confirms which instrument the name means, not a
                  second phrase to read on from the name into. */}
              {position.symbol && (
                <span className="tag tag--symbol mono">{position.symbol}</span>
              )}
            </>
          )}
        </td>
        <td className="secondary">
          {editing ? (
            <select
              className="input input--grid input--cell"
              value={position.instrument_type}
              aria-label="Instrument type"
              onChange={(event) =>
                update.mutate({ id: position.id, instrument_type: event.target.value })
              }
            >
              {INSTRUMENT_TYPES.map((type) => (
                <option key={type} value={type}>
                  {type}
                </option>
              ))}
            </select>
          ) : (
            position.instrument_type
          )}
        </td>
        {/* Neither of these is ever editable. A holding is scoped to one account
            as a one-way door (§13.4), and its currency is the currency every
            figure beside it is stated in and never translated from (BR-18). The
            API's update serialiser declines both. */}
        <td className="secondary">{position.account}</td>
        <td className="numeric">{formatDecimal(position.total_quantity, 4)}</td>
        <td className="numeric">{formatDecimal(position.total_cost_basis)}</td>
        <td className="mono">{position.currency}</td>
        {/* Closed gains only. There is no unrealised gain in this system, so
            nothing here is waiting on a price: what has been sold is all that
            is counted, and the percentage is that gain over what those units
            cost — never over a value of units still held. */}
        <td className="numeric">
          {position.realised_gain === null ? (
            <span className="secondary">—</span>
          ) : (
            <span
              className={
                position.realised_gain.startsWith('-')
                  ? 'money money--breach'
                  : 'money money--rise'
              }
            >
              {formatDecimal(position.realised_gain)}
            </span>
          )}
        </td>
        <td className="numeric secondary">
          {position.realised_gain_percent === null
            ? '—'
            : `${position.realised_gain_percent}%`}
        </td>
        {/* Changing this restates the net figure on every historic sale,
            including sales already reported — free, because nothing was
            stored (BR-21). Editable here and on the holding's own page, with one
            mutation behind both. */}
        <td className="numeric secondary">
          {editing ? (
            <input
              className="input input--grid mono numeric-input"
              inputMode="decimal"
              defaultValue={position.estimated_tax_percent ?? ''}
              aria-label="Estimated tax percent"
              onBlur={(event) => edit('estimated_tax_percent', event.target.value)}
            />
          ) : position.estimated_tax_percent ? (
            `${position.estimated_tax_percent}%`
          ) : (
            '—'
          )}
        </td>
        <td className="accounts__actions">
          <div className="accounts__actions-set">
            <button
              type="button"
              className="link-button"
              onClick={() => setEditing(!editing)}
            >
              {editing ? 'Done' : 'Edit'}
            </button>

            {/* Only for holdings nothing was ever recorded against. Everything
                else keeps its history — a sold-out holding still realised a gain
                that has been reported (ADR-14). */}
            {position.transaction_count === 0 && (
              <button
                type="button"
                className="link-button link-button--breach"
                onClick={() => remove.mutate(position.id)}
              >
                Delete
              </button>
            )}
          </div>
        </td>
      </tr>

      {/* Flagged, never blocked. The figures above still stand. */}
      {!position.consistent &&
        position.inconsistencies.map((problem) => (
          <tr className="table__message-row" key={problem.transaction_id}>
            <td colSpan={10}>
              <div className="advisory" role="status">
                <span className="advisory__label">Advisory · Retroactively invalid</span>
                <span className="advisory__body">{problem.message}</span>
              </div>
            </td>
          </tr>
        ))}

      {/* Neither action asks first, so a refusal has to be visible: it is the
          only thing distinguishing a rejected edit from one that did nothing. */}
      {(update.error ?? remove.error) !== null && (
        <tr className="table__message-row">
          <td colSpan={10}>
            <ErrorBanner error={update.error ?? remove.error} />
          </td>
        </tr>
      )}
    </>
  )
}

/**
 * Three tables stacked down the page only read as one register if their columns
 * line up, and separate tables under auto layout each size to their own
 * content. `.table--fixed` plus this shared colgroup pins the geometry, as it
 * does on Accounts.
 */
function HoldingColumns() {
  return (
    <colgroup>
      {/* A third of the register to the name, and it earns it twice over: it is
          the only column with no fixed vocabulary and no bound on its length —
          "Betashares Wealth Builder Diversified All Growth Geared (30-40% LVR)
          Complex ETF" is a real holding — and it is the column the edit row puts
          a free-text field and a symbol field into. Every other column here
          holds a term this application already fixed, a figure of known width,
          or two link labels. */}
      <col style={{ width: '28%' }} />
      <col style={{ width: '7%' }} />
      <col style={{ width: '11%' }} />
      <col style={{ width: '9%' }} />
      <col style={{ width: '9%' }} />
      <col style={{ width: '5%' }} />
      <col style={{ width: '9%' }} />
      <col style={{ width: '6%' }} />
      <col style={{ width: '6%' }} />
      <col style={{ width: '10%' }} />
    </colgroup>
  )
}

function HoldingTable({
  heading,
  positions,
}: {
  readonly heading: string
  readonly positions: readonly Position[]
}) {
  // An empty group is not a fact worth a panel of its own.
  if (positions.length === 0) return null

  return (
    <section className="panel">
      <h2 className="panel__heading">{heading}</h2>

      <table className="table table--fixed">
        <HoldingColumns />
        <thead>
          <tr>
            <th>Holding</th>
            <th>Type</th>
            <th>Account</th>
            <th className="numeric">Quantity</th>
            <th className="numeric">Cost Basis</th>
            <th>Currency</th>
            <th className="numeric">Realised Gain</th>
            <th className="numeric">% Gain</th>
            <th className="numeric">Est. Tax</th>
            <th aria-label="Actions" />
          </tr>
        </thead>
        <tbody>
          {positions.map((position) => (
            <HoldingRow key={position.id} position={position} />
          ))}
        </tbody>
      </table>
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
      {/* The note that stood here — a holding belongs to one account and cannot
          be moved, and the same instrument at two brokers is two holdings with
          independent FIFO queues — was removed at the Product Owner's
          instruction. The rule still holds and the API still enforces it: the
          account field is absent from the update serialiser, so the move is
          rejected rather than merely undocumented (§13.4). */}
      <ErrorBanner error={create.error} />

      <form className="invest__form invest__form--holding" onSubmit={submit}>
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
            Est. tax %
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
        <button
          type="submit"
          className="btn btn--primary invest__submit"
          disabled={create.isPending}
        >
          Add
        </button>
      </form>
    </section>
  )
}

// ---------------------------------------------------------------------------

export function Investments() {
  const holdings = useHoldings()
  const [showSold, setShowSold] = useState(false)

  if (holdings.isPending) return <div className="boot">Loading…</div>
  if (!holdings.data) return <ErrorBanner error={holdings.error} />

  const { holdings: positions } = holdings.data

  /**
   * Grouped on lot count and transaction count, never on a quantity compared
   * against zero: the two are integers the server counted, and a holding is
   * held exactly when it has an open lot.
   *
   * Sold-out holdings hide behind a disclosure rather than vanishing, for the
   * same reason closed accounts do — a sold-out holding realised a gain that
   * has been reported, and the screen has to admit where it went.
   */
  const held = positions.filter((position) => position.lot_count > 0)
  const untraded = positions.filter((position) => position.transaction_count === 0)
  const soldOut = positions.filter(
    (position) => position.lot_count === 0 && position.transaction_count > 0,
  )

  return (
    <div className="invest">
      {/* The subhead and the two prohibition paragraphs were removed from this
          screen at the Product Owner's instruction. Both are departures worth
          naming rather than losing.

          The subhead: the design handoff has every screen state which view
          control it obeys, because a control that silently does nothing is worse
          than one that is visibly inert. The rail still renders the currency
          toggle at 40% opacity here; nothing now says why.

          The prohibitions: the BRD and the handoff both require them in copy on
          the screen, not merely in the implementation. They are still stated on
          a holding's own page, beside the figures they govern, and the API still
          returns them so any screen can state them again. */}

      {/* Above the register, as the create form is on Accounts: the thing that
          makes a row exist comes before the rows. */}
      <NewHolding />

      {positions.length === 0 ? (
        <section className="panel">
          <h2 className="panel__heading">Nothing Here Yet</h2>
          <p className="fx__note">
            The system starts empty and is never seeded. Add a holding above, then
            record what you bought.
          </p>
        </section>
      ) : (
        <>
          <HoldingTable heading="Holdings Held" positions={held} />
          <HoldingTable heading="Holdings Not Yet Traded" positions={untraded} />
          {showSold && <HoldingTable heading="Sold-Out Holdings" positions={soldOut} />}

          {/* Silent when nothing is sold out — an empty disclosure invites a
              click that reveals nothing. */}
          {soldOut.length > 0 && (
            <p className="accounts__disclosure">
              <button
                type="button"
                className="link-button accounts__disclosure-button"
                onClick={() => setShowSold(!showSold)}
              >
                {icons[showSold ? 'hide' : 'show']}
                {showSold ? 'Hide Sold-Out Holdings' : 'Show Sold-Out Holdings'}
              </button>
            </p>
          )}
        </>
      )}

      {/* Entry is not on this screen. Recording a transaction happens on the
          holding's own page, at the Product Owner's instruction — see the note
          in components/Holding.tsx for what that trades away. Open a holding
          from the register above. */}

      {/* The Realised Gains panel that stood here was removed from this screen
          at the Product Owner's instruction. Two things it did are worth naming
          rather than losing.

          It stated the grouping rule in copy — by currency, never summed across
          them (BR-18) — and it was the only place a sale's proceeds, fees and
          cost basis appeared beside the gain they produced. Both survive: the
          register above now carries realised gain and its percentage per
          holding, a holding's own page lists its sales with the lots each one
          consumed, and `/api/investments/realised-gains/` still serves the
          report unchanged (REP-11) for the CSV export. */}
    </div>
  )
}
