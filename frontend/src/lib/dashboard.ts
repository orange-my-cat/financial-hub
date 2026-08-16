/**
 * Dashboard, spine, task badges and CSV export.
 */

import { useQuery } from '@tanstack/react-query'

import { api } from './api'
import type { Completeness, CompletenessState } from './accounts'
import type { CurrencyCode, Money } from './money'

export interface Task {
  readonly kind: string
  readonly count: number
  readonly message: string
  readonly route: string
  /** True where the consequence is an excluded figure, not merely a stale one. */
  readonly breach: boolean
}

export interface BackupStatus {
  readonly destination: string
  readonly configured: boolean
  readonly state: string
  readonly healthy: boolean
  readonly stale: boolean
  readonly newest_at: string | null
  readonly newest_name: string | null
  readonly size_bytes: number | null
  readonly count: number
  readonly newest_data_at: string | null
}

/** One figure's month-on-month movement. Both halves absent where undefined. */
export interface FigureChange {
  readonly change: string | null
  readonly change_percent: string | null
}

export interface DashboardPayload {
  readonly month: string
  readonly currency: CurrencyCode
  readonly net_worth: {
    readonly total: { amount: string; currency: CurrencyCode } | null
    readonly reportable: boolean
    readonly change: string | null
    readonly change_percent: string | null
    readonly previous_month: string
    readonly as_at: string | null
    readonly any_stale: boolean
  }
  readonly completeness: Completeness
  readonly exclusions: readonly { account: string; reason: string }[]
  readonly rate_provenance: readonly {
    pair: string
    as_at: string
    provenance: string
    stale: boolean
  }[]
  readonly trend: readonly {
    month: string
    total: string | null
    completeness: CompletenessState
  }[]
  readonly tasks: readonly Task[]
  /**
   * The month's flow in the reporting currency — one figure per line, not a
   * breakdown. A currency with no rate at the month's as-at date — its
   * month-end, or today while it is still running — is withheld from all four
   * figures and named in `exclusions`, never counted as zero (FR-46).
   */
  readonly cashflow: {
    readonly month: string
    readonly currency: CurrencyCode
    readonly reportable: boolean
    readonly income: Money | null
    readonly expense: Money | null
    readonly net: Money | null
    /** Net as a percentage of income. Null where income is zero. */
    readonly savings_rate: string | null
    readonly exclusions: readonly { currency: CurrencyCode; reason: string }[]
    readonly rate_provenance: readonly {
      currency: CurrencyCode
      pair: string
      as_at: string
      provenance: string
      stale: boolean
    }[]
    readonly as_at: string | null
    readonly any_stale: boolean
    readonly previous_month: string
    /**
     * Each figure's movement on the month before.
     *
     * `change_percent` is null against a zero prior month — a rise from nothing
     * has no proportion. `savings_rate` moves in percentage points and never
     * carries a percent of its own: a proportion of a proportion is a figure
     * nobody can check by hand.
     */
    readonly change: {
      readonly income: FigureChange
      readonly expense: FigureChange
      readonly net: FigureChange
      readonly savings_rate: FigureChange
    }
  }
  /**
   * 24 months of the same four figures, latest last.
   *
   * Money is zero for a month with nothing recorded — the one place absence and
   * zero coincide, because a month with no spending genuinely spent nothing.
   * `savings_rate` stays null there: no income is no denominator.
   */
  readonly cashflow_trend: readonly {
    month: string
    income: string
    expense: string
    net: string
    savings_rate: string | null
  }[]
  readonly investments: readonly {
    currency: CurrencyCode
    holdings: number
    cost_basis: string
    realised_gain_this_year: string
  }[]
  readonly backup: BackupStatus
}

export interface SpineMonth {
  readonly month: string
  readonly state: CompletenessState
}

export function useDashboard(month: string, currency: string) {
  return useQuery({
    queryKey: ['dashboard', month, currency],
    queryFn: () =>
      api
        .get<{ data: DashboardPayload }>(`/dashboard/?month=${month}&currency=${currency}`)
        .then((r) => r.data),
  })
}

/**
 * The spine's months.
 *
 * `extend` asks for that many months before the first recorded one. The
 * response says whether asking for more would show anything new, so the
 * control that drives it can retire itself instead of going quietly dead.
 */
export function useSpine(through: string, extend = 0) {
  return useQuery({
    queryKey: ['spine', through, extend],
    queryFn: () =>
      api.get<{ data: SpineMonth[]; extendable: boolean }>(
        `/spine/?through=${through}&extend=${extend}`,
      ),
  })
}

export function useTaskCounts() {
  return useQuery({
    queryKey: ['tasks'],
    queryFn: () => api.get<{ data: Record<string, number> }>('/tasks/').then((r) => r.data),
  })
}

/**
 * CSV export.
 *
 * A plain navigation rather than a fetch-and-blob: the file is generated
 * server-side and streamed with a Content-Disposition, so the browser's own
 * download handling does the work and the bytes never pass through JavaScript
 * that could reformat them.
 */
export function exportUrl(report: string, params: Record<string, string>): string {
  const query = new URLSearchParams(params).toString()
  return `/api/export/${report}/${query ? `?${query}` : ''}`
}
