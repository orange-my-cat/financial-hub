/**
 * Reporting currency and date range — persistent view state, not filters.
 *
 * Both live in the chrome, both are reflected in the URL, and every view is
 * bookmarkable and refresh-survivable. That matters most in the one place it
 * is easiest to overlook: a reload part-way through a monthly close.
 *
 * They are also explicit query parameters on every reporting endpoint, never
 * inferred from server-side session state, so a URL fully determines its
 * response (§8.2). Holding them here and in the address bar is the same
 * decision seen from the browser's side.
 *
 * The default currency setting is what the reporting currency starts at when
 * the URL is silent, and nothing more. It is resolved here, in the browser, and
 * sent onward as an explicit parameter — the server never reads it for a
 * report, which is what keeps the sentence above true.
 */

import { useCallback, useMemo } from 'react'
import { useSearchParams } from 'react-router-dom'

import { useDefaultCurrency } from './fx'
import { REPORTING_CURRENCIES, type ReportingCurrencyCode } from './money'

/** How many months the reports show by default. */
const DEFAULT_RANGE_MONTHS = 24

function monthKey(date: Date): string {
  return `${date.getUTCFullYear()}-${String(date.getUTCMonth() + 1).padStart(2, '0')}`
}

function shiftMonths(from: string, months: number): string {
  const [year, month] = from.split('-').map(Number)
  const date = new Date(Date.UTC(year ?? 1970, (month ?? 1) - 1 + months, 1))
  return monthKey(date)
}

export interface ViewState {
  readonly currency: ReportingCurrencyCode
  readonly from: string
  readonly to: string
  /**
   * The single month being worked on — what the spine selects and what Month
   * Close and Cash flow entry operate on. Deliberately *not* the range: those
   * screens state that the date range does not apply to them, and selecting a
   * month to close must not quietly restate the reports.
   */
  readonly month: string
  setCurrency: (currency: ReportingCurrencyCode) => void
  setRange: (from: string, to: string) => void
  setMonth: (month: string) => void
}

export function useViewState(): ViewState {
  const [params, setParams] = useSearchParams()
  const defaultCurrency = useDefaultCurrency()

  // The URL wins where it names a currency, and the stored default fills the
  // silence — so a bookmarked report keeps its meaning while a fresh visit
  // opens in the currency the user works in.
  //
  // A hand-typed `?currency=XAU` falls back to the default rather than being
  // honoured: gold denominates balances, never a reported total.
  const currency = useMemo<ReportingCurrencyCode>(() => {
    const raw = params.get('currency')
    return (REPORTING_CURRENCIES as readonly string[]).includes(raw ?? '')
      ? (raw as ReportingCurrencyCode)
      : defaultCurrency
  }, [params, defaultCurrency])

  const to = params.get('to') ?? monthKey(new Date())
  const from = params.get('from') ?? shiftMonths(to, -(DEFAULT_RANGE_MONTHS - 1))
  // Defaults to the end of the range, which is where a month-at-a-time screen
  // would have started anyway. Once selected it is held separately.
  const month = params.get('month') ?? to

  const setCurrency = useCallback(
    (next: ReportingCurrencyCode) => {
      setParams(
        (current) => {
          const updated = new URLSearchParams(current)
          updated.set('currency', next)
          return updated
        },
        { replace: true },
      )
    },
    [setParams],
  )

  const setRange = useCallback(
    (nextFrom: string, nextTo: string) => {
      setParams(
        (current) => {
          const updated = new URLSearchParams(current)
          updated.set('from', nextFrom)
          updated.set('to', nextTo)
          return updated
        },
        { replace: true },
      )
    },
    [setParams],
  )

  const setMonth = useCallback(
    (next: string) => {
      setParams(
        (current) => {
          const updated = new URLSearchParams(current)
          updated.set('month', next)
          return updated
        },
        { replace: true },
      )
    },
    [setParams],
  )

  return { currency, from, to, month, setCurrency, setRange, setMonth }
}
