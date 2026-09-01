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
 *   * **A dormant row arrives finished, and there is nothing here about it.**
 *     A dormant account's balance does not change, so every month of its that
 *     has no figure is written with the last one server-side
 *     (`accounts.services.dormant`). The row that arrives is an ordinary saved
 *     row: same ink, same wash, same tick, no mark, no second field, no branch
 *     in this file. The close pass tabs past it.
 *
 *     A deliberate departure from FR-10, which asks for a carried balance to be
 *     marked as such. It was marked, with the `c` a carried rate wears, and the
 *     mark was removed on instruction: a row that is finished should read as
 *     finished. The one thing the screen still does differently is withhold the
 *     discard bin — see `hasStored`.
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
import {
  useClearBalance,
  useMonthClose,
  useSaveBalance,
  type MonthCloseRow,
} from '@/lib/accounts'
import {
  formatDecimal,
  formatMonth,
  formatPercent,
  movementClass,
  parseAmountInput,
  roundDecimal,
} from '@/lib/format'
import { useViewState } from '@/lib/viewState'
import { icons } from '@/shell/icons'

// `cleared` is not `idle`: between discarding a figure and the refetch that
// confirms it, the row still carries the old `saved` from the server, and idle
// would keep showing the tick for a figure that is already gone.
type RowState = 'idle' | 'saving' | 'saved' | 'cleared' | 'error'

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
  const [state, setState] = useState<RowState>('idle')
  const [error, setError] = useState<string | null>(null)
  const save = useSaveBalance()
  const clear = useClearBalance()
  const lastCommitted = useRef(entered)

  // Only when the stored figure itself changes — a refetch that returns the
  // same string leaves the row alone, so a tick survives the invalidation its
  // own save triggered.
  useEffect(() => {
    setValue(entered)
    lastCommitted.current = entered
    setState('idle')
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

  // Discards the stored figure rather than writing a zero: the row goes back to
  // never having been entered, which is what Missing means. No confirmation —
  // the number is one keystroke to retype, and a dialogue on every row would
  // cost more than the mistake.
  function discard() {
    setState('saving')
    setError(null)
    clear.mutate(
      { accountId: row.account_id, month },
      {
        onSuccess: () => {
          lastCommitted.current = ''
          setValue('')
          setState('cleared')
        },
        onError: (caught) => {
          setState('error')
          setError(caught instanceof ApiError ? caught.message : 'Not cleared.')
        },
      },
    )
  }

  const isSaved = state === 'saved' || (state === 'idle' && row.saved)
  // What there is to discard is what the server holds, not what is in the box:
  // an untouched row and a half-typed one both have nothing to clear. The bin
  // keeps its space on those rows and goes invisible rather than absent, so
  // twenty boxes stay in one line — and twenty dead bins do not sit above a
  // month that has not been entered yet.
  //
  // Never on a dormant row. What sits in that box is a property of dormancy —
  // the account is not being touched, so the month holds what the month before
  // it held — and the server writes it back on the next read. A bin that undoes
  // itself is worse than no bin. To stop carrying a figure, set the account back
  // to Open on the Accounts screen, or close it.
  const hasStored = row.saved && state !== 'cleared' && row.status !== 'Dormant'

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
        {/* The bin draws to the left of the box but comes after it in the
            DOM, and the stylesheet reorders the two. Tab therefore reaches the
            box first and the bin second, which is the order they are used in;
            putting the bin first in source would make every account's balance
            two keystrokes away instead of one, in a pass built around Tab
            landing on the next number.

            No `tabIndex={-1}`: a control reachable only by pointer is a
            control some people do not have. It is skipped on the rows where it
            is disabled — which is every row with nothing yet to discard — so
            a first pass through an empty month never meets it. */}
        <div className="cell-balance__field">
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
          <button
            type="button"
            className={`btn btn--icon cell-balance__clear${
              hasStored ? '' : ' cell-balance__clear--absent'
            }`}
            onClick={discard}
            disabled={!hasStored || state === 'saving'}
            aria-label={`Clear ${row.name} balance`}
            title="Clear the saved balance for this month"
          >
            {icons.clear}
          </button>
        </div>
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
          where that would be noticed.

          What it notices is bounded by the staleness threshold, not by the day.
          A month that has ended counts a rate carried from within that threshold
          as satisfied, because a month-end falling on a weekend has no close to
          enter and was otherwise un-closable — see
          `NetWorthService._rates_satisfying`. So a lapsed load shows here once it
          exceeds the threshold rather than immediately. The month in progress
          still requires a rate on the day, which is the case a same-day tripwire
          was really for. */}
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

                The name takes 26% and the tick 36px, which is all a glyph
                needs. Balance takes 14% rather than the even 10%: it holds the
                bin as well as the box, and a fixed layout will not lend it the
                width from anywhere. The four it is borrowed from carry a word
                or a figure each and had room to spare. */}
            <colgroup>
              <col style={{ width: '26%' }} />
              <col style={{ width: '10%' }} />
              <col style={{ width: '10%' }} />
              <col style={{ width: '10%' }} />
              <col style={{ width: '10%' }} />
              <col style={{ width: '10%' }} />
              <col style={{ width: '14%' }} />
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
