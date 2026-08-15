/**
 * Dashboard, spine, task badges and CSV export.
 */

import { useQuery } from '@tanstack/react-query'

import { api } from './api'
import type { Completeness, CompletenessState } from './accounts'
import type { CurrencyBlock } from './cashflow'
import type { CurrencyCode } from './money'

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
  readonly cashflow: readonly CurrencyBlock[]
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

export function useSpine(through: string) {
  return useQuery({
    queryKey: ['spine', through],
    queryFn: () =>
      api.get<{ data: SpineMonth[] }>(`/spine/?through=${through}`).then((r) => r.data),
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
