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

/**
 * A reference series — a baseline the eye measures another line against.
 *
 * Deliberately not Rise or Breach: those two carry a judgement, and a cost basis
 * is neither good nor bad news. Ink at 45%, so the line it is there to be
 * compared with stays the one that reads first.
 */
export const REFERENCE = 'rgba(233,233,237,.45)'

/** The dash pattern for a reference series. Dashed reads as "given", not "measured". */
export const DASH = '4 3'

/**
 * A node that is neither income nor expense — the month itself, standing in the
 * middle of a flow diagram. Ink rather than a third hue, for the same reason
 * REFERENCE is: the month is not good news or bad news, and a coloured node
 * there would read as a verdict on the net.
 */
export const NEUTRAL = 'rgba(233,233,237,.32)'

/** Flow geometry. The ribbons carry the figures, so the nodes stay slight. */
export const SANKEY_NODE_WIDTH = 11
/** Deep enough to print a label in the gap above an interior node. */
export const SANKEY_NODE_PADDING = 20
/** The vertical room one node needs before its label crowds its neighbour's. */
export const SANKEY_ROW = 30
/** Wide enough for the longest category name and its figure, either side. */
export const SANKEY_MARGIN = { top: 22, right: 172, bottom: 14, left: 172 } as const
/** Ribbons are read as widths, not as fills; opaque ones bury the ones behind. */
export const LINK_OPACITY = 0.24

export const AXIS_WIDTH = 72
export const CHART_HEIGHT = 208
export const CHART_MARGIN = { top: 8, right: 8, bottom: 4, left: 8 } as const

export const GRID = 'rgba(233,233,237,.06)'
export const AXIS_TICK = { fill: 'rgba(233,233,237,.45)', fontSize: 11 } as const
export const AXIS_LINE = { stroke: 'rgba(233,233,237,.10)' } as const
export const BAND = 'rgba(233,233,237,.07)'

/** One month's slot, wide enough to read as a band and not as a rule. */
export const BAND_WIDTH = 22

/**
 * The hover mark on a **dense** axis — a day-by-day series, where the month
 * band's 22px would cover a fortnight and read as a range rather than as the
 * one date under the pointer. A rule at that date instead, in the band's ink at
 * an axis line's weight. Stated here for the same reason the band is: a screen
 * that picks its own hover ink makes the same gesture look like two.
 */
export const CURSOR = { stroke: 'rgba(233,233,237,.16)', strokeWidth: 1 } as const

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

/**
 * A y-axis fitted to its data, not anchored to zero.
 *
 * Recharts defaults a numeric axis to `[0, 'auto']`, which is right for the bars
 * — an income bar is read as a quantity from nothing. It is wrong for a level
 * plotted over years: a net worth that moves between 180k and 210k, drawn from
 * zero, is a flat line, and the movement the chart exists to show is compressed
 * into a tenth of the panel. Fitting the axis to the data spends the height on
 * the change.
 *
 * Shared for the same reason the geometry above is shared: net worth appears on
 * two screens, and an axis chosen per chart would make one history read as two.
 */
export const FIT_DOMAIN: ['auto', 'auto'] = ['auto', 'auto']
