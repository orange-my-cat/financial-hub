/**
 * Month Close — the most important screen in the system.
 *
 * Twenty rows, optimised for a person typing twenty numbers without lifting
 * their hands. Everything here follows from that:
 *
 *   * **Rates first**, so the whole pass runs in one tab order. Stopping
 *     halfway to go and find a rate is what ends a close.
 *   * **The prior balance sits immediately left of the input.** That adjacency
 *     is the point of the screen — it is how you notice a number that is wrong.
 *   * **Autosave on blur, and deliberately no save button.** An interruption
 *     mid-close must not cost the entry, and a partly closed month is a
 *     legitimate state (Incomplete) rather than an error requiring rollback, so
 *     atomicity would buy nothing (ADR-15, §9.6).
 *   * **Tab advances to the next account.** Which is just DOM order, and is the
 *     reason the inputs are a flat sequence rather than nested in per-row forms.
 *
 * Neither view control applies; both render inert.
 */

import { useEffect, useRef, useState, type FocusEvent } from 'react'

import { AdvisoryList, ErrorBanner } from '@/components/Advisories'
import { StateGlyph } from '@/components/Provenance'
import { ApiError, type Advisory } from '@/lib/api'
import {
  useMonthClose,
  useSaveBalance,
  type MonthCloseRate,
  type MonthCloseRow,
} from '@/lib/accounts'
import { formatDate, formatDecimal, parseAmountInput } from '@/lib/format'
import { useRateEntry } from '@/lib/fx'
import { useViewState } from '@/lib/viewState'

type RowState = 'idle' | 'saving' | 'saved' | 'error'

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
      <span className="readout__note">Autosaves on blur. There is no save button.</span>
    </div>
  )
}

// ---------------------------------------------------------------------------

function RateRow({
  rate,
  asAt,
  onAdvisories,
}: {
  readonly rate: MonthCloseRate
  readonly asAt: string
  readonly onAdvisories: (advisories: readonly Advisory[]) => void
}) {
  const [value, setValue] = useState(rate.rate ?? '')
  const [state, setState] = useState<RowState>('idle')
  const entry = useRateEntry()

  useEffect(() => {
    setValue(rate.rate ?? '')
    setState('idle')
  }, [rate.rate])

  function commit(event: FocusEvent<HTMLInputElement>) {
    const raw = event.target.value.trim()
    if (raw === '' || raw === (rate.rate ?? '')) return

    setState('saving')
    entry.mutate(
      { currency: rate.currency, rate_date: asAt, rate: raw },
      {
        onSuccess: (response) => {
          setState('saved')
          onAdvisories(response.advisories)
        },
        onError: () => setState('error'),
      },
    )
  }

  return (
    <tr>
      <td className="mono">{rate.pair}</td>
      <td className="secondary">{rate.quote_label}</td>
      <td className="numeric">
        {rate.effective_rate ?? <span className="excluded">none</span>}
        {rate.provenance === 'carried' && <sup className="mark mark--carried">c</sup>}
      </td>
      <td className="secondary">
        {rate.effective_as_at ? formatDate(rate.effective_as_at) : '—'}
      </td>
      <td>
        <input
          className={`input input--grid mono${state === 'saved' ? ' input--saved' : ''}`}
          inputMode="decimal"
          placeholder={rate.example}
          value={value}
          onChange={(event) => setValue(event.target.value)}
          onBlur={commit}
          aria-label={`${rate.pair} rate`}
        />
      </td>
      <td className="cell-state">
        {state === 'saved' && <span className="saved">saved</span>}
        {state === 'saving' && <span className="secondary">…</span>}
        {state === 'error' && <span className="excluded">not saved</span>}
      </td>
    </tr>
  )
}

// ---------------------------------------------------------------------------

function BalanceRow({
  row,
  index,
  month,
}: {
  readonly row: MonthCloseRow
  readonly index: number
  readonly month: string
}) {
  const [value, setValue] = useState(row.current ?? '')
  const [state, setState] = useState<RowState>(row.saved ? 'idle' : 'idle')
  const [error, setError] = useState<string | null>(null)
  const save = useSaveBalance()
  const lastCommitted = useRef(row.current ?? '')

  useEffect(() => {
    setValue(row.current ?? '')
    lastCommitted.current = row.current ?? ''
  }, [row.current])

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
      <td className="secondary row-number mono">{index + 1}</td>
      <td>{row.name}</td>
      <td className="secondary">{row.type}</td>
      <td className="secondary mono">{row.currency}</td>
      {/* The adjacency that is the point of this screen. */}
      <td className="numeric secondary">
        {row.prior !== null ? formatDecimal(row.prior) : <span className="ink-30">—</span>}
      </td>
      <td>
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
      <td className="cell-state">
        {isSaved && <span className="saved">saved</span>}
        {state === 'saving' && <span className="secondary">…</span>}
        {!isSaved && state !== 'saving' && state !== 'error' && (
          <span className="ink-30">—</span>
        )}
      </td>
    </tr>
  )
}

// ---------------------------------------------------------------------------

export function MonthClose() {
  const { to } = useViewState()
  const [month, setMonth] = useState(to)
  const close = useMonthClose(month)
  const [advisories, setAdvisories] = useState<readonly Advisory[]>([])

  if (close.isPending) return <div className="boot">Loading…</div>
  if (!close.data) return <ErrorBanner error={close.error} />

  const view = close.data

  return (
    <div className="close">
      <p className="screen__subhead">
        Neither the reporting currency nor the date range applies here. Balances are
        entered in each account’s own currency.
      </p>

      <div className="close__month">
        <label className="field__label" htmlFor="close-month">
          Month
        </label>
        <input
          id="close-month"
          type="month"
          className="input mono"
          value={month}
          onChange={(event) => setMonth(event.target.value)}
        />
      </div>

      <CompletenessReadout
        state={view.completeness.state}
        balances={view.completeness.balances}
        rates={view.completeness.rates}
        outstandingAccounts={view.completeness.outstanding_accounts}
        outstandingCurrencies={view.completeness.outstanding_currencies}
      />

      {/* Section 1 — rates first, so the whole pass runs in one tab order. */}
      <section className="panel">
        <h2 className="panel__heading">Exchange rates required for this month</h2>
        {view.rates.length === 0 ? (
          <p className="fx__note">
            Every account this month is in USD, so no rate is required.
          </p>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>Pair</th>
                <th>Quoted as</th>
                <th className="numeric">In effect</th>
                <th>As at</th>
                <th>Rate for {formatDate(view.as_at)}</th>
                <th aria-label="Saved" />
              </tr>
            </thead>
            <tbody>
              {view.rates.map((rate) => (
                <RateRow
                  key={rate.currency}
                  rate={rate}
                  asAt={view.as_at}
                  onAdvisories={setAdvisories}
                />
              ))}
            </tbody>
          </table>
        )}
        {/* Saves either way — the advisory sits beside the thing it concerns. */}
        <AdvisoryList advisories={advisories} />
      </section>

      {/* Section 2 — balances. */}
      <section className="panel">
        <h2 className="panel__heading">Balances as at {formatDate(view.as_at)}</h2>
        <p className="fx__note">
          Liabilities are entered as positive figures; the system applies the sign.
        </p>

        {view.rows.length === 0 ? (
          <p className="fx__note">
            No accounts are active in this month. Create one on the Accounts screen first.
          </p>
        ) : (
          <table className="table table--close">
            <thead>
              <tr>
                <th className="row-number">#</th>
                <th>Account</th>
                <th>Type</th>
                <th>Cur</th>
                <th className="numeric">{view.rows[0]?.prior_month ?? 'Prior'}</th>
                <th>Balance</th>
                <th aria-label="Saved" />
              </tr>
            </thead>
            <tbody>
              {view.rows.map((row, index) => (
                <BalanceRow
                  key={row.account_id}
                  row={row}
                  index={index}
                  month={view.month}
                />
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  )
}
