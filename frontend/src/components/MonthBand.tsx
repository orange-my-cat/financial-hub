/**
 * The month highlight every trend plot shares.
 *
 * Recharts can synchronise charts by `syncId`, but synchronised charts each
 * open their own tooltip, so hovering one month produced three boxes at once.
 * The highlight is therefore drawn rather than synchronised: one piece of React
 * state says which month is under the pointer, and every plot draws a band on
 * that month whether or not it is the plot being hovered. Only the plot under
 * the pointer opens a tooltip.
 *
 * Drawn before the marks, so it sits behind them — a band under the data, not
 * a rule across it. Kept here rather than on either screen because the band is
 * chart geometry: a screen that restates its width locally makes the same month
 * look wider on one page than on the next.
 */

import { ReferenceLine } from 'recharts'

import { BAND, BAND_WIDTH } from '@/lib/charts'

export function MonthBand({ month }: { readonly month: string | undefined }) {
  if (month === undefined) return null
  return <ReferenceLine x={month} stroke={BAND} strokeWidth={BAND_WIDTH} />
}
