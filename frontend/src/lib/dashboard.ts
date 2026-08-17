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
  /**
   * Which month the figures are for, and why.
   *
   * `closed` — the last month that has ended and has balances recorded, which is
   * the usual answer: balances are entered when a month ends, so the month in
   * progress holds nothing until it closes. `current` — the month in progress,
   * closed early, meaning every balance it requires is already in. `requested` —
   * asked for explicitly in the URL. `empty` — nothing has ever been recorded, so
   * there is no close to report.
   */
  readonly reporting_month: {
    readonly month: string
    readonly basis: 'closed' | 'current' | 'requested' | 'empty'
    readonly current_month: string
    readonly is_current: boolean
  }
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
  /**
   * What is held **now**, combined into the reporting currency.
   *
   * A departure from the BRD and from BR-18, made deliberately: the system has no
   * market prices, so `estimated_value` is each holding's units at the last price
   * it was transacted at, and `estimated_gain` is that less what those units cost
   * — the figure the documents call unrealised gain. Both are estimates and both
   * are labelled as such wherever they are rendered.
   *
   * `priced_from` is the oldest price the estimate rests on: a holding untouched
   * since 2019 is "valued" at its 2019 price, and the panel says so rather than
   * implying the figure is current. `unpriced` names held holdings with no price
   * on record — left out of the estimate rather than valued at nothing — and
   * `priced_cost_basis` is what the gain was measured against when those two sets
   * differ, so the figures on screen always reconcile with each other.
   */
  readonly investments: {
    readonly currency: CurrencyCode
    readonly holdings: number
    readonly cost_basis: Money
    readonly estimated_value: Money | null
    readonly estimated_gain: Money | null
    readonly priced_cost_basis: Money | null
    readonly priced_from: string | null
    readonly unpriced: readonly string[]
    readonly exclusions: readonly {
      holding: string
      currency: CurrencyCode
      reason: string
    }[]
    readonly rate_provenance: readonly {
      currency: CurrencyCode
      pair: string
      as_at: string
      provenance: string
      stale: boolean
    }[]
    readonly as_at: string | null
    readonly any_stale: boolean
  }
  /**
   * The same 24-month window as the trends above — the position **as at** each
   * month, so a sale lands in the month it happened rather than being plotted
   * backwards over months when the units were still held.
   *
   * Money is zero for a month with nothing held, which is honest here: holdings
   * are derived from transactions rather than entered, so no transactions means
   * nothing was owned. `estimated_value` is null only where something was held and
   * none of it could be estimated, so the line breaks instead of dropping to zero.
   */
  readonly investments_trend: readonly {
    month: string
    cost_basis: string
    estimated_value: string | null
  }[]
  readonly backup: BackupStatus
}

export interface SpineMonth {
  readonly month: string
  readonly state: CompletenessState
}

/**
 * The dashboard's figures. No month is sent, and that is the point.
 *
 * Which month the dashboard reports is a rule about the data — the last month
 * that has ended and has balances recorded, or the month in progress once it is
 * complete — so it is answered by the one service that owns it and stated back in
 * `reporting_month`. A month resolved here from `new Date()` would be a second
 * definition of the same thing, and would disagree with the server's on either
 * side of midnight on the first of a month.
 */
export function useDashboard(currency: string) {
  return useQuery({
    queryKey: ['dashboard', currency],
    queryFn: () =>
      api
        .get<{ data: DashboardPayload }>(`/dashboard/?currency=${currency}`)
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
