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
import { BASE_CURRENCY, REPORTING_CURRENCIES, type ReportingCurrencyCode } from './money'

export type Provenance = 'exact' | 'carried' | 'triangulated'

export interface CurrencyDefinition {
  readonly code: string
  readonly name: string
  readonly convention: 'usd_per_unit' | 'units_per_usd'
  /** `USD per 1 AUD`, `MYR per 1 USD` — shown beside the field. */
  readonly quote_label: string
  readonly example: string
  readonly is_base: boolean
  /**
   * Whether net worth may be *stated* in this unit. A balance may be held in
   * any currency here; gold denominates one and does not report.
   */
  readonly can_report: boolean
  readonly pair: string
}

export interface CurrencyRegistry {
  readonly base: string
  readonly currencies: readonly CurrencyDefinition[]
  readonly quoted: readonly string[]
  /** The codes the reporting-currency toggle may offer. Served, not inferred. */
  readonly reporting: readonly string[]
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
  /**
   * What every currency selector starts at — the reporting-currency control in
   * the header, and the currency field on each entry form. A default, not an
   * override: an explicit choice, in the URL or in a form, always wins.
   */
  readonly default_currency: string
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

/**
 * The currency every selector in the application starts at.
 *
 * The shell waits for settings before rendering a screen, so by the time any
 * selector mounts this is the stored value rather than the fallback. The
 * fallback covers exactly one case — the settings request failed — where USD is
 * the honest answer: it is the base currency, the one figure that needs no rate
 * to be stated.
 *
 * Narrowed to a reporting currency rather than trusted as served. The server
 * refuses to store XAU here, and a code that slipped through would otherwise
 * reach the header toggle, which has no button to show for it.
 */
export function useDefaultCurrency(): ReportingCurrencyCode {
  const settings = useSettings()
  const code = settings.data?.default_currency
  return (REPORTING_CURRENCIES as readonly string[]).includes(code ?? '')
    ? (code as ReportingCurrencyCode)
    : BASE_CURRENCY
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
    // And the accounts tree, which every rate reaches: net worth and the
    // month's completeness are both derived through these rates, and neither
    // restates itself.
    void queryClient.invalidateQueries({ queryKey: ['accounts'] })
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

/** What one pair's load did. Counts, not figures — the table shows the rates. */
export interface RateLoadPair {
  readonly currency: string
  readonly pair: string
  readonly fetched: number
  readonly written: number
  readonly replaced: number
  /** Dates left alone because the rate there was typed by hand (BRD §4.3). */
  readonly kept_manual: number
  readonly first_date: string | null
  readonly last_date: string | null
}

export interface RateLoadResult {
  readonly provider: string
  readonly start: string
  readonly end: string
  readonly dry_run: boolean
  readonly fetched: number
  readonly written: number
  readonly kept_manual: number
  readonly pairs: readonly RateLoadPair[]
}

/**
 * Load the last 365 days of daily closes from the provider.
 *
 * Takes a few seconds and no arguments: the window is fixed on the server, so
 * the browser cannot ask for a decade through a synchronous endpoint. Safe to
 * run repeatedly — a re-fetch replaces only rows an earlier fetch wrote, and
 * never a rate that was typed.
 */
export function useLoadRates() {
  const invalidate = useFxInvalidation()

  return useMutation({
    mutationFn: () => api.post<Envelope<RateLoadResult>>('/fx/rates/load/', {}),
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
