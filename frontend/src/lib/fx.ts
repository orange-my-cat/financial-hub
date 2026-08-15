/**
 * FX and settings — types and server state.
 *
 * Rates cross as strings, exactly as money does. A rate is a decimal, and
 * `JSON.parse` turns a decimal into a float just as readily as it does an
 * amount — a rate rendered through a float would misvalue every balance in that
 * currency (ADR-12).
 *
 * The currency registry is **fetched, not hard-coded**. AUD and MYR are quoted
 * in opposite market conventions, and a second copy of that fact in the browser
 * is a second place for it to be wrong.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api, type Advisory, type Envelope } from './api'

export type Provenance = 'exact' | 'carried' | 'triangulated'

export interface CurrencyDefinition {
  readonly code: string
  readonly name: string
  readonly convention: 'usd_per_unit' | 'units_per_usd'
  /** `USD per 1 AUD`, `MYR per 1 USD` — shown beside the field. */
  readonly quote_label: string
  readonly example: string
  readonly is_base: boolean
  readonly pair: string
}

export interface CurrencyRegistry {
  readonly base: string
  readonly currencies: readonly CurrencyDefinition[]
  readonly quoted: readonly string[]
}

export interface DailyRateEntry {
  readonly currency: string
  readonly pair: string
  readonly quote_label: string
  readonly rate: string
  readonly as_at: string
  readonly provenance: Provenance
  readonly stale: boolean
  /** False where this date has no stored row and the figure is carried. */
  readonly recorded: boolean
}

export interface DailyRateRow {
  readonly date: string
  readonly entries: readonly DailyRateEntry[]
}

export interface RateStatusRow {
  readonly currency: string
  readonly pair: string
  readonly quote_label: string
  readonly rate: string | null
  readonly as_at: string | null
  readonly age_days: number | null
  readonly missing: boolean
  readonly stale: boolean
  /** The word, so the meaning survives without the colour. */
  readonly state: string
}

export interface RateStatusSummary {
  readonly as_of: string
  readonly staleness_days: number
  readonly pairs: readonly RateStatusRow[]
}

export interface TrendPoint {
  readonly date: string
  readonly rate: string
  readonly provenance: Provenance
  readonly derived: boolean
}

export interface RateTrend {
  readonly pair: string
  readonly from_currency: string
  readonly to_currency: string
  readonly derived: boolean
  readonly points: readonly TrendPoint[]
}

export interface AppSettings {
  readonly reporting_currency: string
  readonly timezone: string
  readonly rate_staleness_days: number
  readonly rate_variance_percent: string
}

// ---------------------------------------------------------------------------
// Queries
// ---------------------------------------------------------------------------

export const fxKeys = {
  currencies: ['fx', 'currencies'] as const,
  rates: (start: string, end: string) => ['fx', 'rates', start, end] as const,
  status: (asOf: string) => ['fx', 'status', asOf] as const,
  trend: (from: string, to: string, start: string, end: string) =>
    ['fx', 'trend', from, to, start, end] as const,
  settings: ['settings'] as const,
}

export function useCurrencies() {
  return useQuery({
    queryKey: fxKeys.currencies,
    queryFn: () => api.get<{ data: CurrencyRegistry }>('/fx/currencies/').then((r) => r.data),
    // The registry changes when a currency is added to the system, which is a
    // deploy, not a session.
    staleTime: Infinity,
  })
}

export function useDailyRates(start: string, end: string) {
  return useQuery({
    queryKey: fxKeys.rates(start, end),
    queryFn: () =>
      api
        .get<{ data: DailyRateRow[] }>(`/fx/rates/?start=${start}&end=${end}`)
        .then((r) => r.data),
  })
}

export function useRateStatus(asOf: string) {
  return useQuery({
    queryKey: fxKeys.status(asOf),
    queryFn: () =>
      api.get<{ data: RateStatusSummary }>(`/fx/status/?as_of=${asOf}`).then((r) => r.data),
  })
}

export function useRateTrend(from: string, to: string, start: string, end: string) {
  return useQuery({
    queryKey: fxKeys.trend(from, to, start, end),
    queryFn: () =>
      api
        .get<{ data: RateTrend }>(
          `/fx/trend/?from_currency=${from}&to_currency=${to}&start=${start}&end=${end}`,
        )
        .then((r) => r.data),
  })
}

export function useSettings() {
  return useQuery({
    queryKey: fxKeys.settings,
    queryFn: () => api.get<{ data: AppSettings }>('/settings/').then((r) => r.data),
  })
}

// ---------------------------------------------------------------------------
// Mutations
// ---------------------------------------------------------------------------

/**
 * Everything in this system is computed on read, so a stale cache after an edit
 * shows a wrong figure. Every mutation invalidates the whole `fx` tree rather
 * than trying to be surgical — the dataset is small, and a missed invalidation
 * is a wrong number on screen (ADR-15).
 */
function useFxInvalidation() {
  const queryClient = useQueryClient()
  return () => {
    void queryClient.invalidateQueries({ queryKey: ['fx'] })
  }
}

export interface BulkEntryResult {
  readonly rate_date: string
  readonly saved: readonly { currency: string; pair: string; rate: string }[]
}

export function useBulkRateEntry() {
  const invalidate = useFxInvalidation()

  return useMutation({
    mutationFn: (input: { rate_date: string; rates: Record<string, string> }) =>
      api.post<Envelope<BulkEntryResult>>('/fx/rates/bulk/', input),
    onSuccess: invalidate,
  })
}

export function useRateEntry() {
  const invalidate = useFxInvalidation()

  return useMutation({
    mutationFn: (input: { currency: string; rate_date: string; rate: string }) =>
      api.post<Envelope<{ currency: string; pair: string; rate: string }>>(
        '/fx/rates/',
        input,
      ),
    onSuccess: invalidate,
  })
}

export function useDeleteRate() {
  const invalidate = useFxInvalidation()

  return useMutation({
    mutationFn: (input: { currency: string; rate_date: string }) =>
      api.delete<void>(`/fx/rates/${input.currency}/${input.rate_date}/`),
    onSuccess: invalidate,
  })
}

export function useUpdateSettings() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (changes: Partial<Omit<AppSettings, 'timezone'>>) =>
      api.patch<{ data: AppSettings }>('/settings/', changes),
    onSuccess: (response) => {
      queryClient.setQueryData(fxKeys.settings, response.data)
      // The staleness threshold feeds every rate status and every translated
      // figure, so changing it restates what is on screen.
      void queryClient.invalidateQueries({ queryKey: ['fx'] })
    },
  })
}

export type { Advisory }
