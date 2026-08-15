/**
 * Cash flow — types and server state.
 *
 * Note what is missing and always will be: nothing here returns a balance or a
 * net worth figure. Cash flow is a parallel ledger, and no report sums it
 * together with balance figures (BR-12).
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api, type Envelope } from './api'
import type { CurrencyCode } from './money'

export type Direction = 'Income' | 'Expense'
export type Frequency = 'Monthly' | 'Quarterly' | 'Annual'

export interface CategoryChild {
  readonly id: number
  readonly name: string
  readonly direction: Direction
  readonly is_active: boolean
  /** Transactions using it. Non-zero means deactivate, never delete. */
  readonly used: number
  readonly path: string
}

export interface CategoryParent {
  readonly id: number
  readonly name: string
  readonly direction: Direction
  readonly is_active: boolean
  readonly children: readonly CategoryChild[]
}

export interface TransactionRow {
  readonly id: number
  readonly date: string
  readonly amount: string
  readonly currency: CurrencyCode
  readonly direction: Direction
  readonly category_id: number
  readonly category: string
  readonly parent: string
  readonly note: string
  readonly from_recurring: boolean
}

export interface Proposal {
  readonly template_id: number
  readonly name: string
  readonly period: string
  readonly amount: string
  readonly currency: CurrencyCode
  readonly direction: Direction
  readonly category_id: number
  readonly category: string
  readonly suggested_date: string
}

export interface CategoryTotal {
  readonly category_id: number
  readonly category: string
  readonly parent: string
  readonly direction: Direction
  readonly currency: CurrencyCode
  readonly total: string
  readonly count: number
}

export interface CurrencyBlock {
  readonly currency: CurrencyCode
  readonly income: string
  readonly expense: string
  readonly net: string
  readonly parents: readonly {
    readonly parent: string
    readonly direction: Direction
    readonly total: string
    readonly count: number
  }[]
  readonly children: readonly CategoryTotal[]
}

export interface CategoryTrend {
  readonly months: readonly string[]
  readonly series: readonly {
    readonly currency: CurrencyCode
    readonly direction: Direction
    readonly points: readonly string[]
  }[]
}

// ---------------------------------------------------------------------------

export const cashflowKeys = {
  all: ['cashflow'] as const,
  transactions: (month: string) => ['cashflow', 'transactions', month] as const,
  categories: ['cashflow', 'categories'] as const,
  proposals: ['cashflow', 'proposals'] as const,
  report: (month: string) => ['cashflow', 'report', month] as const,
  trend: (from: string, to: string) => ['cashflow', 'trend', from, to] as const,
}

export function useTransactions(month: string) {
  return useQuery({
    queryKey: cashflowKeys.transactions(month),
    queryFn: () =>
      api
        .get<{ data: TransactionRow[] }>(`/cashflow/transactions/?month=${month}`)
        .then((r) => r.data),
  })
}

export function useCategories() {
  return useQuery({
    queryKey: cashflowKeys.categories,
    queryFn: () =>
      api.get<{ data: CategoryParent[] }>('/cashflow/categories/').then((r) => r.data),
  })
}

export function useProposals() {
  return useQuery({
    queryKey: cashflowKeys.proposals,
    queryFn: () =>
      api.get<{ data: Proposal[] }>('/cashflow/recurring/proposals/').then((r) => r.data),
  })
}

export function useCategoryReport(month: string) {
  return useQuery({
    queryKey: cashflowKeys.report(month),
    queryFn: () =>
      api
        .get<{ data: { month: string; currencies: CurrencyBlock[] } }>(
          `/cashflow/category-report/?month=${month}`,
        )
        .then((r) => r.data),
  })
}

export function useCategoryTrend(from: string, to: string) {
  return useQuery({
    queryKey: cashflowKeys.trend(from, to),
    queryFn: () =>
      api
        .get<{ data: CategoryTrend }>(
          `/cashflow/category-trend/?from_month=${from}&to_month=${to}`,
        )
        .then((r) => r.data),
  })
}

// ---------------------------------------------------------------------------

function useCashflowInvalidation() {
  const queryClient = useQueryClient()
  return () => {
    void queryClient.invalidateQueries({ queryKey: cashflowKeys.all })
  }
}

export function useRecordTransaction() {
  const invalidate = useCashflowInvalidation()
  return useMutation({
    mutationFn: (input: {
      date: string
      amount: string
      currency: string
      category_id: number
      note?: string
    }) => api.post<Envelope<TransactionRow>>('/cashflow/transactions/', input),
    onSuccess: invalidate,
  })
}

export function useDeleteTransaction() {
  const invalidate = useCashflowInvalidation()
  return useMutation({
    mutationFn: (id: number) => api.delete<void>(`/cashflow/transactions/${id}/`),
    onSuccess: invalidate,
  })
}

export function useConfirmProposal() {
  const invalidate = useCashflowInvalidation()
  return useMutation({
    mutationFn: (input: { template_id: number; period: string; amount?: string }) =>
      api.post<Envelope<TransactionRow>>('/cashflow/recurring/confirm/', input),
    onSuccess: invalidate,
  })
}

export function useDismissProposal() {
  const invalidate = useCashflowInvalidation()
  return useMutation({
    mutationFn: (input: { template_id: number; period: string }) =>
      api.post<void>('/cashflow/recurring/dismiss/', input),
    onSuccess: invalidate,
  })
}

export function useUpdateCategory() {
  const invalidate = useCashflowInvalidation()
  return useMutation({
    mutationFn: ({ id, ...changes }: { id: number; name?: string; is_active?: boolean }) =>
      api.patch<{ data: { id: number; name: string } }>(
        `/cashflow/categories/${id}/`,
        changes,
      ),
    onSuccess: invalidate,
  })
}

export function useAddCategory() {
  const invalidate = useCashflowInvalidation()
  return useMutation({
    mutationFn: (input: { name: string; parent_id: number }) =>
      api.post<{ data: { id: number; name: string } }>('/cashflow/categories/', input),
    onSuccess: invalidate,
  })
}

export function useDeleteCategory() {
  const invalidate = useCashflowInvalidation()
  return useMutation({
    mutationFn: (id: number) => api.delete<void>(`/cashflow/categories/${id}/`),
    onSuccess: invalidate,
  })
}
