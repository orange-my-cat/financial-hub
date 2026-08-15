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

export type InvestmentAction = 'Buy' | 'Sell' | 'Split' | 'Distribution' | 'Reinvestment'

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
  readonly lot_count: number
  readonly distributions: string
  /** False where a historic edit invalidated a sale. Flagged, never blocking. */
  readonly consistent: boolean
  readonly inconsistencies: readonly Inconsistency[]
  readonly lots: readonly Lot[]
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

export function useUpdateHolding() {
  const invalidate = useInvestmentInvalidation()
  return useMutation({
    mutationFn: ({ id, ...changes }: { id: number; estimated_tax_percent?: string | null }) =>
      api.patch<{ data: Position }>(`/investments/holdings/${id}/`, changes),
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
