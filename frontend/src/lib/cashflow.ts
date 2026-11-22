/**
 * Cash flow — types and server state.
 *
 * Note what is missing and always will be: nothing here returns a balance or a
 * net worth figure. Cash flow is a parallel ledger, and no report sums it
 * together with balance figures (BR-12).
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api, type Envelope } from './api'
import type { Provenance } from './fx'
import type { CurrencyCode, Money, ReportingCurrencyCode } from './money'

export type Direction = 'Income' | 'Expense'
export type Frequency = 'Weekly' | 'Fortnightly' | 'Monthly'

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
  /**
   * This amount in the reporting currency, and the rate it was reached by.
   *
   * **Null on the responses to entry and to an edit**, which named no reporting
   * currency to state it in. That is a different fact from the one inside it: a
   * restatement whose `amount` is null is a row that *was* asked about and had
   * no rate on its own date, where the column withholds a figure rather than
   * showing a zero (FR-46). The entered amount beside it is unaffected either
   * way.
   */
  readonly restatement: Restatement | null
}

/**
 * One transaction restated, with what qualifies it.
 *
 * The rate is this row's own. Two purchases in one currency a fortnight apart
 * are translated at two different rates, so the provenance and the staleness
 * belong against the row and not against the table.
 */
export interface Restatement {
  /** Null where no rate exists on or before this row's date. Never zero. */
  readonly amount: Money | null
  /** Null where the row is already in the reporting currency: no rate was used. */
  readonly rate: {
    readonly pair: string
    readonly as_at: string
    readonly provenance: Provenance
    readonly stale: boolean
  } | null
  readonly exclusion_reason: string | null
}

/**
 * A month's transactions, and what qualifies the restated column beside them.
 *
 * A list rather than a total, but it carries a translated figure, so it travels
 * with the same three things every translated figure does: which currencies
 * were excluded for want of a rate, where the rates it did use came from, and
 * whether any of them is stale (§8.2).
 */
export interface TransactionList {
  readonly month: string
  readonly currency: ReportingCurrencyCode
  readonly rows: readonly TransactionRow[]
  /** How many rows each currency lost, and why. Not always all of them. */
  readonly exclusions: readonly {
    currency: CurrencyCode
    count: number
    reason: string
  }[]
  /** One row per currency: the oldest rate the month leaned on. */
  readonly rate_provenance: readonly {
    currency: CurrencyCode
    pair: string
    as_at: string
    provenance: Provenance
    stale: boolean
  }[]
  /** Present only when a contributing rate is stale. Silence is the signal. */
  readonly as_at: string | null
  readonly any_stale: boolean
}

export interface RecurringTemplate {
  readonly id: number
  readonly name: string
  readonly amount: string
  readonly currency: CurrencyCode
  readonly direction: Direction
  readonly category_id: number
  readonly category: string
  readonly parent: string
  readonly frequency: Frequency
  /** The first occurrence. Every later one is counted from it. */
  readonly anchor_date: string
  /** The last date it proposes on. Null while it runs indefinitely. */
  readonly end_date: string | null
  readonly is_active: boolean
}

/**
 * Three, not two. An occurrence nobody has answered and one deliberately
 * skipped are different facts about the month, and both stay on the list.
 */
export type ProposalStatus = 'Outstanding' | 'Confirmed' | 'Skipped'

export interface Proposal {
  readonly template_id: number
  readonly name: string
  /** The date this occurrence falls on — its identity, and what it would carry. */
  readonly occurrence: string
  readonly amount: string
  readonly currency: CurrencyCode
  readonly direction: Direction
  readonly category_id: number
  readonly category: string
  readonly status: ProposalStatus
  /**
   * What the confirmed transaction actually carries, which is not always what
   * the template proposed — the amount is adjustable at confirmation and the
   * date can be moved off the occurrence. Null until confirmed.
   */
  readonly recorded_amount: string | null
  readonly recorded_date: string | null
}

/**
 * A figure's movement on the month before it, computed by the server through the
 * one definition of a change. Both halves null where there is nothing to
 * compare; the percentage alone null against a month of zero, because a rise
 * from nothing has no proportion.
 */
export interface Movement {
  readonly change: string | null
  readonly change_percent: string | null
}

export interface CategoryTotal {
  readonly category_id: number
  readonly category: string
  readonly parent: string
  readonly direction: Direction
  readonly currency: CurrencyCode
  readonly total: string
  readonly count: number
  readonly change: Movement
  /**
   * The transactions this total is the sum of, newest first — the third level
   * of the report, revealed under the subcategory that totals them.
   *
   * `restatement` is null on every one of them, and that is the report being
   * consistent rather than a figure going missing: this endpoint names no
   * reporting currency and translates nothing, so a row here is stated in the
   * currency of the block it sits in and in no other. The restated column
   * belongs to the ledger, which was asked.
   */
  readonly transactions: readonly TransactionRow[]
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
    readonly change: Movement
  }[]
  readonly children: readonly CategoryTotal[]
}

/**
 * The month's categories combined into one currency — one figure per category,
 * however many currencies it was spent in.
 *
 * The counterpart to CurrencyBlock and the only translated thing in this
 * module. Everything else here is exact and per currency; this applies a rate,
 * so it carries what qualifies a translated total: which currencies were
 * excluded for want of one, and where the rates it did use came from (§8.2).
 */
export interface CategoryFlowRow {
  readonly category_id: number
  readonly category: string
  readonly parent: string
  readonly direction: Direction
  readonly total: Money
  readonly count: number
}

export interface CategoryFlow {
  readonly month: string
  readonly currency: ReportingCurrencyCode
  /** False where the month is empty, and where every currency was excluded. */
  readonly reportable: boolean
  readonly income: Money
  readonly expense: Money
  readonly net: Money
  readonly parents: readonly {
    readonly parent: string
    readonly direction: Direction
    readonly total: Money
    readonly count: number
  }[]
  readonly children: readonly CategoryFlowRow[]
  readonly exclusions: readonly {
    currency: CurrencyCode
    count: number
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
  // The currency is part of the key because it is part of the answer: the
  // restated column is a different set of figures in a different currency.
  transactions: (month: string, currency: string) =>
    ['cashflow', 'transactions', month, currency] as const,
  categories: ['cashflow', 'categories'] as const,
  proposals: (month: string) => ['cashflow', 'proposals', month] as const,
  templates: ['cashflow', 'templates'] as const,
  report: (month: string) => ['cashflow', 'report', month] as const,
  flow: (month: string, currency: string) =>
    ['cashflow', 'flow', month, currency] as const,
  trend: (from: string, to: string) => ['cashflow', 'trend', from, to] as const,
}

export function useTransactions(month: string, currency: ReportingCurrencyCode) {
  return useQuery({
    queryKey: cashflowKeys.transactions(month, currency),
    queryFn: () =>
      api
        .get<{ data: TransactionList }>(
          `/cashflow/transactions/?month=${month}&currency=${currency}`,
        )
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

/**
 * Every occurrence falling in one month, answered or not.
 *
 * The month is part of the key because it is part of the answer. Older
 * occurrences still awaiting a decision are counted on the dashboard's tasks
 * panel, which is where work left undone belongs (OI-09).
 */
export function useProposals(month: string) {
  return useQuery({
    queryKey: cashflowKeys.proposals(month),
    queryFn: () =>
      api
        .get<{ data: Proposal[] }>(`/cashflow/recurring/proposals/?month=${month}`)
        .then((r) => r.data),
  })
}

/**
 * Every template, ended ones included — the management list, not the proposing
 * one. An ended template is still worth seeing: it explains the transactions it
 * left behind.
 */
export function useTemplates() {
  return useQuery({
    queryKey: cashflowKeys.templates,
    queryFn: () =>
      api.get<{ data: RecurringTemplate[] }>('/cashflow/recurring/').then((r) => r.data),
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

/**
 * The combined breakdown, in the reporting currency the header is set to.
 *
 * The currency is part of the key because it is part of the answer: the same
 * month translated into two currencies is two different sets of figures, not
 * one set rendered twice.
 */
export function useCategoryFlow(month: string, currency: ReportingCurrencyCode) {
  return useQuery({
    queryKey: cashflowKeys.flow(month, currency),
    queryFn: () =>
      api
        .get<{ data: CategoryFlow }>(
          `/cashflow/category-flow/?month=${month}&currency=${currency}`,
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

/**
 * Everything is editable at any time, including history (BR-23).
 *
 * Only the fields that actually changed are sent. That is not a bandwidth
 * nicety: re-sending an unchanged category would put it back through the
 * active-category check, and a transaction sitting on a since-deactivated
 * category would then be unable to have its note corrected — which is the
 * opposite of "its history stays intact".
 */
export function useUpdateTransaction() {
  const invalidate = useCashflowInvalidation()
  return useMutation({
    mutationFn: ({
      id,
      ...changes
    }: {
      id: number
      date?: string
      amount?: string
      currency?: string
      category_id?: number
      note?: string
    }) => api.patch<Envelope<TransactionRow>>(`/cashflow/transactions/${id}/`, changes),
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
    mutationFn: (input: { template_id: number; occurrence: string; amount?: string }) =>
      api.post<Envelope<TransactionRow>>('/cashflow/recurring/confirm/', input),
    onSuccess: invalidate,
  })
}

export function useDismissProposal() {
  const invalidate = useCashflowInvalidation()
  return useMutation({
    mutationFn: (input: { template_id: number; occurrence: string }) =>
      api.post<void>('/cashflow/recurring/dismiss/', input),
    onSuccess: invalidate,
  })
}

export function useCreateTemplate() {
  const invalidate = useCashflowInvalidation()
  return useMutation({
    mutationFn: (input: {
      name: string
      amount: string
      currency: string
      category_id: number
      frequency: Frequency
      anchor_date: string
      end_date?: string | null
    }) => api.post<{ data: { id: number } }>('/cashflow/recurring/', input),
    onSuccess: invalidate,
  })
}

/** Stop future proposals. The template and its history stay (BR-14). */
export function useEndTemplate() {
  const invalidate = useCashflowInvalidation()
  return useMutation({
    mutationFn: ({ id, end_date }: { id: number; end_date?: string }) =>
      api.post<{ data: RecurringTemplate }>(`/cashflow/recurring/${id}/end/`, {
        end_date,
      }),
    onSuccess: invalidate,
  })
}

/**
 * Amend what a running template proposes. Confirmed transactions never change;
 * a change of anchor or frequency applies forward only, and the server refuses
 * one whose anchor falls on or before an occurrence already decided.
 */
export function useUpdateTemplate() {
  const invalidate = useCashflowInvalidation()
  return useMutation({
    mutationFn: ({
      id,
      ...changes
    }: {
      id: number
      name?: string
      amount?: string
      category_id?: number
      anchor_date?: string
      frequency?: Frequency
    }) => api.patch<{ data: RecurringTemplate }>(`/cashflow/recurring/${id}/`, changes),
    onSuccess: invalidate,
  })
}

/** Start an ended template again, on a new anchor and cadence. The gap stays silent. */
export function useRestartTemplate() {
  const invalidate = useCashflowInvalidation()
  return useMutation({
    mutationFn: ({
      id,
      ...input
    }: {
      id: number
      anchor_date: string
      frequency: Frequency
    }) => api.post<{ data: RecurringTemplate }>(`/cashflow/recurring/${id}/restart/`, input),
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
