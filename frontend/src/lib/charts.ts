/**
 * Chart geometry and palette — stated once, used by every plot.
 *
 * Two screens draw trends over the same months, and a reader moving between
 * them is comparing shapes. A plot that is shorter, or whose axis gutter is
 * narrower, exaggerates the same movement and makes the same history look like
 * a different one. So the numbers below are not per-chart taste; they are the
 * thing that makes two charts comparable, and a chart that restates one of them
 * locally has quietly opted out.
 *
 * The colours are the design tokens, repeated here because SVG attributes
 * cannot read CSS custom properties. They must match `tokens.css`:
 *
 *   Accent  #9184d9  the trend line
 *   Rise    #6fae90  income, and an increase
 *   Breach  #d1756a  expenses, and a decrease
 */

export const ACCENT = '#9184d9'
export const RISE = '#6fae90'
export const BREACH = '#d1756a'

export const AXIS_WIDTH = 72
export const CHART_HEIGHT = 208
export const CHART_MARGIN = { top: 8, right: 8, bottom: 4, left: 8 } as const

export const GRID = 'rgba(233,233,237,.06)'
export const AXIS_TICK = { fill: 'rgba(233,233,237,.45)', fontSize: 11 } as const
export const AXIS_LINE = { stroke: 'rgba(233,233,237,.10)' } as const
export const BAND = 'rgba(233,233,237,.07)'

/** One month's slot, wide enough to read as a band and not as a rule. */
export const BAND_WIDTH = 22

/** Keeps 24 month labels from colliding on one line. */
export const MIN_TICK_GAP = 24

/** Recharts' own tooltip box, dressed as a surface panel. */
export const TOOLTIP_STYLE = {
  background: '#232532',
  border: '1px solid rgba(233,233,237,.16)',
  borderRadius: 8,
  fontSize: 12,
} as const

/**
 * Axis ticks only — never a figure the user reads as money.
 *
 * A chart needs pixels, and pixels need a float: ADR-02's one unavoidable
 * exception. Every exact figure on a chart panel comes from the server as a
 * string and is rendered from that string, so nothing here is arithmetic on
 * money — it is arithmetic on a tick label.
 */
export function compactTick(value: number): string {
  const magnitude = Math.abs(value)
  if (magnitude >= 1000) return `${(value / 1000).toFixed(magnitude >= 10_000 ? 0 : 1)}k`
  return String(value)
}
