/**
 * Month Close — the most important screen in the system.
 *
 * Twenty rows, optimised for a person typing twenty numbers without lifting
 * their hands. Everything here follows from that:
 *
 *   * **The prior balance sits immediately left of the input.** That adjacency
 *     is the point of the screen — it is how you notice a number that is wrong.
 *   * **Autosave on blur, and deliberately no save button.** An interruption
 *     mid-close must not cost the entry, and a partly closed month is a
 *     legitimate state (Incomplete) rather than an error requiring rollback, so
 *     atomicity would buy nothing (ADR-15, §9.6).
 *   * **Tab advances to the next account.** Which is just DOM order, and is the
 *     reason the inputs are a flat sequence rather than nested in per-row forms.
 *
 * The month being closed is chosen on the spine, which is always shown here.
 * Neither view control applies, and both render inert: the reporting currency
 * governed the rate section, and rates are loaded from the provider now
 * (`manage.py load_rates`) rather than typed here. Balances were always
 * untouched by it and stay in each account's own currency.
 *
 * The completeness readout still counts rates, which is not a leftover. A
 * missing rate excludes an account from the translated total rather than
 * zeroing it (FR-46), so a load that quietly failed yields a total that looks
 * finished and is not — and this is the screen where that gets noticed.
 */

import { useEffect, useRef, useState, type FocusEvent } from 'react'

import { ErrorBanner } from '@/components/Advisories'
import { StateGlyph } from '@/components/Provenance'
import { ApiError } from '@/lib/api'
import { useMonthClose, useSaveBalance, type MonthCloseRow } from '@/lib/accounts'
import {
  formatDecimal,
  formatMonth,
  formatPercent,
  parseAmountInput,
  roundDecimal,
} from '@/lib/format'
import { useViewState } from '@/lib/viewState'
import { icons } from '@/shell/icons'

type RowState = 'idle' | 'saving' | 'saved' | 'error'

/**
 * Rise or Breach, by sign and by whether the balance is owed.
 *
 * A liability moving up is more debt, which is not a rise, so the colour
 * inverts on it: green means the month moved in your favour here exactly as it
 * does everywhere else. A movement of zero takes neither colour — nothing
 * moved, and painting that green reports a rise that did not happen. The test
 * is on the string rather than on `Number(value)`: money carries no arithmetic
 * in the browser, and asking whether a figure is signed is not arithmetic.
 */
function movementClass(value: string | null, isLiability: boolean): string {
  if (!value || /^-?0(\.0*)?$/.test(value)) return ''
  return value.startsWith('-') === isLiability ? 'money--rise' : 'money--breach'
}

// ---------------------------------------------------------------------------

function CompletenessReadout({
  state,
  balances,
  rates,
  outstandingAccounts,
  outstandingCurrencies,
}: {
  readonly state: 'Complete' | 'Incomplete' | 'Missing' | 'Outside Range'
  readonly balances: { expected: number; recorded: number }
  readonly rates: { expected: number; recorded: number }
  readonly outstandingAccounts: readonly string[]
  readonly outstandingCurrencies: readonly string[]
}) {
  const remaining = [
    outstandingAccounts.length > 0
      ? `${outstandingAccounts.length} balance${outstandingAccounts.length === 1 ? '' : 's'}`
      : null,
    outstandingCurrencies.length > 0
      ? `${outstandingCurrencies.join(', ')} rate${outstandingCurrencies.length === 1 ? '' : 's'}`
      : null,
  ].filter(Boolean)

  return (
    <div className="readout">
      <span className="readout__state">
        <StateGlyph state={state} />
        {state}
      </span>
      <span className="readout__counts mono">
        {balances.recorded} of {balances.expected} balances · {rates.recorded} of{' '}
        {rates.expected} rates
      </span>
      {remaining.length > 0 && (
        <span className="readout__remaining">Outstanding: {remaining.join(' · ')}</span>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------

function BalanceRow({
  row,
  month,
}: {
  readonly row: MonthCloseRow
  readonly month: string
}) {
  // Two places, not the four the column stores. Storage keeps NUMERIC(19,4) and
  // reads back as `10000.0000`; nobody enters a balance to a hundredth of a
  // cent, and four places of padding in a box about to be retyped is noise.
  const entered = row.current === null ? '' : roundDecimal(row.current)

  const [value, setValue] = useState(entered)
  const [state, setState] = useState<RowState>(row.saved ? 'idle' : 'idle')
  const [error, setError] = useState<string | null>(null)
  const save = useSaveBalance()
  const lastCommitted = useRef(entered)

  useEffect(() => {
    setValue(entered)
    lastCommitted.current = entered
  }, [entered])

  function commit(event: FocusEvent<HTMLInputElement>) {
    const raw = event.target.value
    if (raw.trim() === '' || raw === lastCommitted.current) return

    const parsed = parseAmountInput(raw)
    if (parsed === null) {
      setState('error')
      setError('Enter a number.')
      return
    }

    setState('saving')
    setError(null)
    save.mutate(
      { accountId: row.account_id, month, amount: parsed },
      {
        onSuccess: () => {
          lastCommitted.current = raw
          setState('saved')
        },
        onError: (caught) => {
          setState('error')
          setError(caught instanceof ApiError ? caught.message : 'Not saved.')
        },
      },
    )
  }

  const isSaved = state === 'saved' || (state === 'idle' && row.saved)

  return (
    <tr>
      <td>{row.name}</td>
      <td className="secondary">{row.type}</td>
      {/* Which side of net worth the figure lands on. The nine account types
          carry it already, but only if you know all nine by heart — and it is
          what decides whether a rising balance is a rise. */}
      <td className="secondary">{row.is_liability ? 'Liability' : 'Asset'}</td>
      <td className="secondary">{row.liquidity_tier}</td>
      <td className="secondary mono">{row.currency}</td>
      {/* The adjacency that is the point of this screen. */}
      <td className="numeric secondary">
        {row.prior !== null ? formatDecimal(row.prior) : <span className="ink-30">—</span>}
      </td>
      <td className="cell-balance">
        <input
          className={`input input--grid mono numeric-input${isSaved ? ' input--saved' : ''}${
            state === 'error' ? ' input--error' : ''
          }`}
          inputMode="decimal"
          value={value}
          onChange={(event) => setValue(event.target.value)}
          onBlur={commit}
          aria-label={`${row.name} balance`}
        />
        {error && <span className="field__error">{error}</span>}
      </td>
      {/* Left-aligned, unlike the state columns elsewhere: the tick belongs to
          the box it follows, not to the percentage after it. Its width is the
          colgroup's, like every other column here. */}
      <td>
        {/* The icon carries no meaning on its own, so the word is still there
            for anyone reading by screen reader or hovering to check. */}
        {isSaved && (
          <span className="saved" role="img" aria-label="Saved" title="Saved">
            {icons.saved}
          </span>
        )}
        {state === 'saving' && <span className="secondary">…</span>}
        {!isSaved && state !== 'saving' && state !== 'error' && (
          <span className="ink-30">—</span>
        )}
      </td>
      {/* The typed figure against the one beside it, stated as a proportion.
          Em dash on both halves until this month is entered — a month nobody
          recorded is not a month worth zero — and on the percentage alone
          where the prior month was zero, because a rise from nothing has no
          proportion. The value shown is the saved one: it appears once the
          input commits, not while it is being typed. */}
      <td className={`numeric ${movementClass(row.change_percent, row.is_liability)}`.trim()}>
        {row.change_percent ? formatPercent(row.change_percent) : <span className="ink-30">—</span>}
      </td>
    </tr>
  )
}

// ---------------------------------------------------------------------------

export function MonthClose() {
  // The month lives in the URL and is chosen on the spine, which is always
  // present on this screen. A second selector here would be a second face of
  // the same value with nothing to add, sitting above a rail that already shows
  // which months still need the work.
  const { month } = useViewState()
  const close = useMonthClose(month)

  if (close.isPending) return <div className="boot">Loading…</div>
  if (!close.data) return <ErrorBanner error={close.error} />

  const view = close.data

  return (
    <div className="close">
      <CompletenessReadout
        state={view.completeness.state}
        balances={view.completeness.balances}
        rates={view.completeness.rates}
        outstandingAccounts={view.completeness.outstanding_accounts}
        outstandingCurrencies={view.completeness.outstanding_currencies}
      />

      {/* Balances. Rates used to be section 1 here, entered by hand and quoted
          against the reporting currency; they are loaded from the provider now
          (`manage.py load_rates`), so the pass is balances alone.

          The readout above still counts them, and that is deliberate rather
          than a leftover. A missing rate does not zero an account, it excludes
          it from the translated total (FR-46) — so a load that silently did not
          run produces a total that looks complete and is not. This screen is
          where that would be noticed. */}
      <section className="panel">
        <h2 className="panel__heading">Balances for {formatMonth(view.month)}</h2>

        {view.rows.length === 0 ? (
          <p className="fx__note">
            No accounts are active in this month. Create one on the Accounts screen first.
          </p>
        ) : (
          <table className="table table--fixed table--close">
            {/* Fixed layout and pinned widths, because auto layout sizes each
                column to its own content: the account name — the longest thing
                in the row and its subject — is squeezed to the width of the
                word "Liquidity" while the columns beside it, each holding a
                word or a figure, take an unequal share of what is left.

                The name takes 30% and the tick 36px, which is all a glyph
                needs; the seven columns that carry a value divide the rest
                evenly. */}
            <colgroup>
              <col style={{ width: '30%' }} />
              <col style={{ width: '10%' }} />
              <col style={{ width: '10%' }} />
              <col style={{ width: '10%' }} />
              <col style={{ width: '10%' }} />
              <col style={{ width: '10%' }} />
              <col style={{ width: '10%' }} />
              <col style={{ width: '36px' }} />
              <col style={{ width: '10%' }} />
            </colgroup>
            <thead>
              <tr>
                <th>Account</th>
                <th>Type</th>
                <th>Category</th>
                <th>Liquidity</th>
                <th>Currency</th>
                <th className="numeric">Previous Month</th>
                <th className="numeric">Balance</th>
                <th aria-label="Saved" />
                <th className="numeric">% Change</th>
              </tr>
            </thead>
            <tbody>
              {view.rows.map((row) => (
                <BalanceRow key={row.account_id} row={row} month={view.month} />
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  )
}
