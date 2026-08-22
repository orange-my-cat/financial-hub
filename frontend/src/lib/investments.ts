/**
 * Investments — types and server state.
 *
 * Every figure is in its holding's own currency and is never translated
 * (BR-18). Translating performance would conflate market movement with currency
 * movement, producing a figure that answers neither question.
 *
 * There is no market price type here, and no unrealised gain, because neither
 * exists in this system.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from './api'
import type { CurrencyCode } from './money'

/**
 * Four, not five. A distribution and the reinvestment it funded are one
 * transaction, and a distribution taken as cash is not entered at all — it
 * reaches an account, and shows up in that account's balance at the next close.
 */
export type InvestmentAction = 'Buy' | 'Sell' | 'Split' | 'Reinvestment'

export const INSTRUMENT_TYPES = ['Equity', 'ETF', 'Fund', 'Bond', 'Other'] as const

export interface Lot {
  readonly transaction_id: number
  readonly acquired: string
  readonly remaining_quantity: string
  readonly unit_cost: string
  readonly remaining_cost: string
  readonly from_reinvestment: boolean
}

export interface Inconsistency {
  readonly transaction_id: number
  readonly date: string
  readonly requested: string
  readonly available: string
  readonly message: string
}

export interface Position {
  readonly id: number
  readonly name: string
  readonly symbol: string
  readonly instrument_type: string
  readonly currency: CurrencyCode
  readonly account_id: number
  readonly account: string
  readonly estimated_tax_percent: string | null
  readonly total_quantity: string
  readonly total_cost_basis: string
  /**
   * Closed gains on this holding, in this holding's currency. Null — not `"0"` —
   * where nothing has been sold: nothing realised is not a realisation of zero.
   */
  readonly realised_gain: string | null
  /** That gain over what the sold units cost. Null wherever the gain is. */
  readonly realised_gain_percent: string | null
  readonly lot_count: number
  /** Every transaction ever recorded, live or not — what decides deletability. */
  readonly transaction_count: number
  readonly distributions: string
  /** False where a historic edit invalidated a sale. Flagged, never blocking. */
  readonly consistent: boolean
  readonly inconsistencies: readonly Inconsistency[]
  readonly lots: readonly Lot[]
}

/** One lot's contribution to one sale — where its cost basis came from. */
export interface Consumption {
  readonly lot_transaction_id: number
  readonly acquired: string
  readonly quantity: string
  readonly cost_basis: string
}

export interface Sale {
  readonly transaction_id: number
  readonly date: string
  readonly holding: string
  readonly holding_id: number
  readonly quantity: string
  readonly proceeds: string
  readonly fees: string
  readonly net_proceeds: string
  readonly cost_basis: string
  readonly realised_gain: string
  readonly estimated_tax_percent: string | null
  readonly net_realised_gain: string
  readonly tax_applied: boolean
  readonly is_loss: boolean
  /** The lots the sale took its units from, oldest first. */
  readonly consumed: readonly Consumption[]
}

/** What a purchase added to cost basis, and what is left of the lot it opened. */
export interface Acquired {
  readonly cost: string
  readonly from_reinvestment: boolean
  /** `"0"` for a lot sold down to nothing — empty, which is a figure. */
  readonly remaining_quantity: string
  readonly remaining_cost: string
}

/**
 * One row of a holding's register, and what replay made of it.
 *
 * `acquired`, `realised` and `distributed` are the three money effects. Null
 * means the action does not have that effect, never that the effect was zero: a
 * split moves no money and carries none of them.
 *
 * A reinvestment is the one row that carries two — the cash the distribution
 * paid, and the units that cash bought. Every other action carries exactly one.
 */
export interface HoldingTransaction {
  readonly id: number
  readonly action: InvestmentAction
  readonly date: string
  readonly quantity: string
  readonly unit_price: string
  readonly fees: string
  readonly split_ratio: string
  readonly cash_amount: string
  readonly note: string
  readonly acquired: Acquired | null
  readonly realised: Sale | null
  readonly distributed: string | null
  /** A sale a later edit invalidated. Flagged on its row, never blocking. */
  readonly flagged: boolean
}

/**
 * One month end: what was still held, and what those units had cost.
 *
 * Neither figure is a value. No market price is stored, so a month here says
 * what was bought and kept, never what it became worth.
 */
export interface HoldingMonth {
  readonly month: string
  readonly quantity: string
  readonly cost_basis: string
}

export interface HoldingDetailPayload extends Position {
  /** Newest month first, continuous from the holding's first transaction. */
  readonly history: readonly HoldingMonth[]
  readonly transactions: readonly HoldingTransaction[]
  readonly realised: { readonly gross: string; readonly sales: readonly Sale[] }
  readonly prohibitions: Prohibitions
}

export interface GainsBlock {
  readonly currency: CurrencyCode
  readonly gross: string
  readonly net: string
  readonly tax_applied: boolean
  readonly sales: readonly Sale[]
}

export interface Prohibitions {
  readonly unrealised_gain: string
  readonly estimated_tax: string
}

// ---------------------------------------------------------------------------

export const investmentKeys = {
  all: ['investments'] as const,
  holdings: ['investments', 'holdings'] as const,
  holding: (id: number) => ['investments', 'holding', id] as const,
  gains: ['investments', 'gains'] as const,
}

export function useHoldings() {
  return useQuery({
    queryKey: investmentKeys.holdings,
    queryFn: () =>
      api
        .get<{ data: { holdings: Position[]; prohibitions: Prohibitions } }>(
          '/investments/holdings/',
        )
        .then((r) => r.data),
  })
}

/**
 * One holding, its open lots and its transaction register.
 *
 * A second request rather than a slice of the holdings list: the register is
 * the whole point of the subpage and the list has no business carrying every
 * holding's full history to draw a table of totals.
 */
export function useHolding(id: number) {
  return useQuery({
    queryKey: investmentKeys.holding(id),
    queryFn: () =>
      api
        .get<{ data: HoldingDetailPayload }>(`/investments/holdings/${id}/`)
        .then((r) => r.data),
  })
}

export function useRealisedGains() {
  return useQuery({
    queryKey: investmentKeys.gains,
    queryFn: () =>
      api
        .get<{ data: { currencies: GainsBlock[]; prohibitions: Prohibitions } }>(
          '/investments/realised-gains/',
        )
        .then((r) => r.data),
  })
}

function useInvestmentInvalidation() {
  const queryClient = useQueryClient()
  return () => {
    void queryClient.invalidateQueries({ queryKey: investmentKeys.all })
  }
}

export function useCreateHolding() {
  const invalidate = useInvestmentInvalidation()
  return useMutation({
    mutationFn: (input: {
      name: string
      symbol?: string
      instrument_type: string
      currency: string
      account_id: number
      estimated_tax_percent?: string | null
    }) => api.post<{ data: Position }>('/investments/holdings/', input),
    onSuccess: invalidate,
  })
}

/**
 * A holding's editable facts, and only those.
 *
 * Neither the currency nor the account is here, and their absence is the rule
 * rather than an omission: the currency every figure is stated in cannot change
 * under the figures, and a holding is scoped to one account as a one-way door —
 * merging two brokers' queues later would need a decision about which lots came
 * first that the data cannot answer (BR-18, §13.4). The API's update serialiser
 * declines both for the same reason, so the move is refused, not merely absent
 * from this screen.
 */
export function useUpdateHolding() {
  const invalidate = useInvestmentInvalidation()
  return useMutation({
    mutationFn: ({
      id,
      ...changes
    }: {
      id: number
      name?: string
      symbol?: string
      instrument_type?: string
      estimated_tax_percent?: string | null
    }) => api.patch<{ data: Position }>(`/investments/holdings/${id}/`, changes),
    onSuccess: invalidate,
  })
}

export function useDeleteHolding() {
  const invalidate = useInvestmentInvalidation()
  return useMutation({
    mutationFn: (id: number) => api.delete<void>(`/investments/holdings/${id}/`),
    onSuccess: invalidate,
  })
}

/**
 * Removing a transaction restates everything after it, for free — nothing was
 * stored, so there is nothing to recompute and nothing to migrate (ADR-06). The
 * row is soft-deleted and recoverable through the admin, as every delete is.
 */
export function useDeleteTransaction() {
  const invalidate = useInvestmentInvalidation()
  return useMutation({
    mutationFn: (id: number) => api.delete<void>(`/investments/transactions/${id}/`),
    onSuccess: invalidate,
  })
}

export function useRecordInvestment() {
  const invalidate = useInvestmentInvalidation()
  return useMutation({
    mutationFn: ({
      holdingId,
      ...body
    }: {
      holdingId: number
      action: InvestmentAction
      date: string
      quantity?: string
      unit_price?: string
      fees?: string
      split_ratio?: string
      cash_amount?: string
      note?: string
    }) =>
      api.post<{ data: { id: number; position: Position } }>(
        `/investments/holdings/${holdingId}/transactions/`,
        body,
      ),
    onSuccess: invalidate,
  })
}
