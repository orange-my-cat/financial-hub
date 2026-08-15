/**
 * Accounts, balances, Month Close and net worth — types and server state.
 *
 * Every figure here is a string the server computed. Nothing in this module
 * adds, subtracts or translates anything, and the `Money` type makes attempting
 * it a compile error (ADR-02, ADR-12).
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api, type Advisory, type AggregateEnvelope, type Envelope } from './api'
import type { CurrencyCode } from './money'

export type AccountStatus = 'Open' | 'Dormant' | 'Closed'
export type CompletenessState = 'Complete' | 'Incomplete' | 'Missing' | 'Outside Range'

export const ACCOUNT_TYPES = [
  'Current/Checking',
  'Savings/Deposit',
  'Investment/Brokerage',
  'Pension/Retirement',
  'Property',
  'Physical Asset',
  'Credit Card',
  'Loan/Mortgage',
  'Other Liability',
] as const

export const LIQUIDITY_TIERS = ['Instant', 'Short', 'Long', 'Locked'] as const

export interface Account {
  readonly id: number
  readonly name: string
  readonly account_type: string
  readonly liquidity_tier: string
  readonly status: AccountStatus
  readonly currency: CurrencyCode
  readonly opened_month: string
  readonly closed_month: string | null
  readonly is_liability: boolean
  /** Fixed once balances exist (BR-08). Drives the superscript lock. */
  readonly currency_locked: boolean
  readonly has_history: boolean
  readonly balance_count: number
}

export interface Completeness {
  readonly month: string
  readonly state: CompletenessState
  readonly balances: { readonly expected: number; readonly recorded: number }
  readonly rates: { readonly expected: number; readonly recorded: number }
  readonly outstanding_accounts: readonly string[]
  readonly outstanding_currencies: readonly string[]
}

export interface MonthCloseRate {
  readonly currency: string
  readonly pair: string
  readonly quote_label: string
  readonly example: string
  readonly rate: string | null
  readonly recorded: boolean
  readonly effective_rate: string | null
  readonly effective_as_at: string | null
  readonly provenance: 'exact' | 'carried' | 'triangulated' | null
  readonly stale: boolean
}

export interface MonthCloseRow {
  readonly account_id: number
  readonly name: string
  readonly type: string
  readonly liquidity_tier: string
  readonly currency: CurrencyCode
  readonly status: AccountStatus
  readonly is_liability: boolean
  readonly prior: string | null
  readonly prior_month: string
  readonly current: string | null
  readonly saved: boolean
}

export interface MonthCloseView {
  readonly month: string
  readonly as_at: string
  readonly completeness: Completeness
  readonly rates: readonly MonthCloseRate[]
  readonly rows: readonly MonthCloseRow[]
}

export interface Contribution {
  readonly account_id: number
  readonly name: string
  readonly type: string
  readonly liquidity_tier: string
  readonly status: AccountStatus
  readonly currency: CurrencyCode
  readonly is_liability: boolean
  readonly entered: { readonly amount: string; readonly currency: CurrencyCode }
  readonly source_month: string
  readonly carried: boolean
  readonly translated: string | null
  readonly as_at: string | null
  readonly provenance: 'exact' | 'carried' | 'triangulated' | null
  readonly stale: boolean
  readonly excluded: boolean
  readonly exclusion_reason: string | null
}

export interface NetWorthPayload {
  readonly month: string
  /** Null where the month has no balances at all — not zero. */
  readonly total: { readonly amount: string; readonly currency: CurrencyCode } | null
  readonly reportable: boolean
  /** Present only when a contributing rate is stale. Silence is the signal. */
  readonly as_at: string | null
  readonly any_stale: boolean
  readonly has_carried_balances: boolean
  readonly accounts: readonly Contribution[]
}

export interface TrendPoint {
  readonly month: string
  /** Null for a month with no balances. The chart breaks its line here. */
  readonly total: { readonly amount: string; readonly currency: CurrencyCode } | null
  readonly change: string | null
  readonly completeness: CompletenessState
  readonly any_stale: boolean
  readonly excluded: number
}

export interface SliceRow {
  readonly key: string
  readonly label: string
  readonly amount: string
  readonly is_liability: boolean
  readonly accounts: number
  readonly excluded: number
}

export interface SlicePayload {
  readonly month: string
  readonly dimension: string
  readonly total: { readonly amount: string; readonly currency: CurrencyCode }
  readonly rows: readonly SliceRow[]
}

export interface HistoryRow {
  readonly month: string
  readonly amount: string
  readonly change: string | null
  readonly previous_month: string | null
}

// ---------------------------------------------------------------------------

export const accountKeys = {
  all: ['accounts'] as const,
  list: ['accounts', 'list'] as const,
  detail: (id: number) => ['accounts', 'detail', id] as const,
  history: (id: number) => ['accounts', 'history', id] as const,
  monthClose: (month: string) => ['accounts', 'month-close', month] as const,
  netWorth: (month: string, currency: string) =>
    ['accounts', 'net-worth', month, currency] as const,
  trend: (from: string, to: string, currency: string) =>
    ['accounts', 'trend', from, to, currency] as const,
  slice: (month: string, currency: string, dimension: string) =>
    ['accounts', 'slice', month, currency, dimension] as const,
}

export function useAccounts() {
  return useQuery({
    queryKey: accountKeys.list,
    queryFn: () => api.get<{ data: Account[] }>('/accounts/').then((r) => r.data),
  })
}

export function useMonthClose(month: string) {
  return useQuery({
    queryKey: accountKeys.monthClose(month),
    queryFn: () =>
      api.get<{ data: MonthCloseView }>(`/month-close/?month=${month}`).then((r) => r.data),
  })
}

export function useNetWorth(month: string, currency: string) {
  return useQuery({
    queryKey: accountKeys.netWorth(month, currency),
    queryFn: () =>
      api.get<AggregateEnvelope<NetWorthPayload, Completeness>>(
        `/net-worth/?month=${month}&currency=${currency}`,
      ),
  })
}

export function useNetWorthTrend(from: string, to: string, currency: string) {
  return useQuery({
    queryKey: accountKeys.trend(from, to, currency),
    queryFn: () =>
      api
        .get<{ data: { currency: string; points: TrendPoint[] } }>(
          `/net-worth/trend/?from_month=${from}&to_month=${to}&currency=${currency}`,
        )
        .then((r) => r.data),
  })
}

export function useNetWorthSlice(month: string, currency: string, dimension: string) {
  return useQuery({
    queryKey: accountKeys.slice(month, currency, dimension),
    queryFn: () =>
      api.get<AggregateEnvelope<SlicePayload, Completeness>>(
        `/net-worth/slices/?month=${month}&currency=${currency}&dimension=${dimension}`,
      ),
  })
}

export function useAccountHistory(id: number) {
  return useQuery({
    queryKey: accountKeys.history(id),
    queryFn: () =>
      api
        .get<{ data: { account: Account; history: HistoryRow[] } }>(
          `/accounts/${id}/history/`,
        )
        .then((r) => r.data),
  })
}

// ---------------------------------------------------------------------------
// Mutations
// ---------------------------------------------------------------------------

/**
 * Every figure is computed on read, so a stale cache after an edit is a wrong
 * number on screen. Invalidation is deliberately broad: the dataset is ~20,000
 * rows and a refetch is cheap, while a missed invalidation is not.
 */
function useAccountInvalidation() {
  const queryClient = useQueryClient()
  return () => {
    void queryClient.invalidateQueries({ queryKey: accountKeys.all })
  }
}

export function useCreateAccount() {
  const invalidate = useAccountInvalidation()
  return useMutation({
    mutationFn: (input: {
      name: string
      account_type: string
      liquidity_tier: string
      currency: string
      opened_month: string
    }) => api.post<{ data: Account }>('/accounts/', input),
    onSuccess: invalidate,
  })
}

export function useUpdateAccount() {
  const invalidate = useAccountInvalidation()
  return useMutation({
    mutationFn: ({ id, ...changes }: { id: number } & Partial<Account>) =>
      api.patch<Envelope<Account>>(`/accounts/${id}/`, changes),
    onSuccess: invalidate,
  })
}

export function useCloseAccount() {
  const invalidate = useAccountInvalidation()
  return useMutation({
    mutationFn: (input: { id: number; closed_month: string }) =>
      api.post<{ data: Account }>(`/accounts/${input.id}/close/`, {
        closed_month: input.closed_month,
      }),
    onSuccess: invalidate,
  })
}

export function useSetDormant() {
  const invalidate = useAccountInvalidation()
  return useMutation({
    mutationFn: (id: number) => api.post<{ data: Account }>(`/accounts/${id}/dormant/`),
    onSuccess: invalidate,
  })
}

export function useReopenAccount() {
  const invalidate = useAccountInvalidation()
  return useMutation({
    mutationFn: (id: number) => api.post<{ data: Account }>(`/accounts/${id}/reopen/`),
    onSuccess: invalidate,
  })
}

export function useDeleteAccount() {
  const invalidate = useAccountInvalidation()
  return useMutation({
    mutationFn: (id: number) => api.delete<void>(`/accounts/${id}/`),
    onSuccess: invalidate,
  })
}

/**
 * The Month Close write. One field, one call, on blur.
 *
 * Deliberately not batched: an interruption mid-close must not cost the entry,
 * and a partly closed month is a legitimate state rather than an error
 * requiring rollback — so atomicity would buy nothing and cost the work
 * (ADR-15, §9.6).
 */
export function useSaveBalance() {
  const invalidate = useAccountInvalidation()
  return useMutation({
    mutationFn: (input: { accountId: number; month: string; amount: string }) =>
      api.put<{ data: { account_id: number; month: string; amount: string } }>(
        `/accounts/${input.accountId}/balances/${input.month}/`,
        { amount: input.amount },
      ),
    onSuccess: invalidate,
  })
}

export type { Advisory }
