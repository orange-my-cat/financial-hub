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
 */

import { useCallback, useMemo } from 'react'
import { useSearchParams } from 'react-router-dom'

import { CURRENCIES, type CurrencyCode } from './money'

export const DEFAULT_CURRENCY: CurrencyCode = 'USD'

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
  readonly currency: CurrencyCode
  readonly from: string
  readonly to: string
  setCurrency: (currency: CurrencyCode) => void
  setRange: (from: string, to: string) => void
}

export function useViewState(): ViewState {
  const [params, setParams] = useSearchParams()

  const currency = useMemo<CurrencyCode>(() => {
    const raw = params.get('currency')
    return (CURRENCIES as readonly string[]).includes(raw ?? '')
      ? (raw as CurrencyCode)
      : DEFAULT_CURRENCY
  }, [params])

  const to = params.get('to') ?? monthKey(new Date())
  const from = params.get('from') ?? shiftMonths(to, -(DEFAULT_RANGE_MONTHS - 1))

  const setCurrency = useCallback(
    (next: CurrencyCode) => {
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

  return { currency, from, to, setCurrency, setRange }
}
