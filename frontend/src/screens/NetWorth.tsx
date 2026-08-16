/**
 * Net worth — the landing report, and the screen answering the driving question.
 *
 * Slice toggles are the whole interaction model. Toggling swaps the grouping of
 * the lower table only; the chart and the headline are unchanged, and there is
 * **no drill-down** anywhere.
 *
 * Two treatments are conditional, and their absence is the design:
 *
 *   * The **as-at strip** appears only when a contributing rate is stale. When
 *     everything is fresh, nothing is shown — no date, no disclosure control.
 *     Silence is the signal.
 *   * The **exclusion notice** appears only when an account had no rate. The
 *     excluded account keeps its own-currency figure elsewhere and is never
 *     shown as zero.
 */

import { useMemo, useState } from 'react'
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  type MouseHandlerDataParam,
} from 'recharts'

import { ErrorBanner } from '@/components/Advisories'
import { MonthBand } from '@/components/MonthBand'
import { StateGlyph } from '@/components/Provenance'
import {
  useNetWorth,
  useNetWorthSlice,
  useNetWorthTrend,
  type CompletenessState,
  type TrendPoint,
} from '@/lib/accounts'
import {
  ACCENT,
  AXIS_LINE,
  AXIS_TICK,
  AXIS_WIDTH,
  CHART_HEIGHT,
  CHART_MARGIN,
  GRID,
  MIN_TICK_GAP,
  compactTick,
} from '@/lib/charts'
import {
  formatDate,
  formatDecimal,
  formatMonth,
  formatMonthShort,
  formatPercent,
} from '@/lib/format'
import { useViewState } from '@/lib/viewState'

const DIMENSIONS = [
  { key: 'type', label: 'Account Type' },
  { key: 'liquidity', label: 'Liquidity Tier' },
  { key: 'currency', label: 'Currency' },
  { key: 'account', label: 'Account' },
] as const

function Amount({
  value,
  currency,
  className = '',
}: {
  readonly value: string
  readonly currency: string
  readonly className?: string
}) {
  const negative = value.startsWith('-')
  return (
    <span className={`money ${negative ? 'money--breach' : ''} ${className}`.trim()}>
      {formatDecimal(value)}
      <span className="money__code">{currency}</span>
    </span>
  )
}

/**
 * Rise or Breach, by sign — the one place this screen decides that.
 *
 * A movement of zero takes neither colour. Nothing moved, and painting that
 * green would report a rise that did not happen. The test is on the string
 * rather than on `Number(value)`: money carries no arithmetic in the browser,
 * and asking whether a figure is signed is not arithmetic.
 */
function movementClass(value: string | null): string {
  if (!value || /^-?0(\.0*)?$/.test(value)) return ''
  return value.startsWith('-') ? 'money--breach' : 'money--rise'
}

/**
 * The dashboard's hover treatment, on this screen's one plot.
 *
 * Same anatomy as the dashboard's tooltip — month at the head, figures in a
 * two-column list — because a reader moving between the two screens is reading
 * the same trend, and a box that arranged the month's figures differently here
 * would make them look like different figures. What it states is this screen's
 * business: the month's net worth and how it moved, the same three columns the
 * table below carries, so pointer and table agree.
 *
 * Every figure is formatted from the server's string, never from the float the
 * chart plots with: the geometry may be approximate, the figures never are. The
 * month comes from `label` rather than from the payload, because a month with
 * no net worth has no payload entry and would otherwise silently lose its
 * tooltip — which is exactly the month a reader points at to ask why the line
 * stops.
 */
function TrendTooltip({
  active,
  label,
  points,
}: {
  readonly active?: boolean
  readonly label?: string | number
  readonly points: Readonly<Record<string, TrendPoint>>
}) {
  const month = active && typeof label === 'string' ? label : undefined
  const point = month ? points[month] : undefined
  if (!month || !point) return null

  return (
    <div className="charttip">
      <div className="charttip__month mono">{formatMonth(month)}</div>
      <dl className="charttip__list">
        <dt>Net Worth</dt>
        <dd className="mono">
          {/* A month before any balance existed has no net worth — not one of
              zero (BR-04). The tooltip says so rather than printing a figure. */}
          {point.total === null
            ? '—'
            : `${formatDecimal(point.total.amount)} ${point.total.currency}`}
        </dd>
        <dt>Change</dt>
        <dd className={`mono ${movementClass(point.change)}`.trim()}>
          {point.change ? formatDecimal(point.change) : '—'}
        </dd>
        <dt>Change %</dt>
        {/* Absent against a zero prior month: a rise from nothing has no
            proportion. */}
        <dd className={`mono ${movementClass(point.change_percent)}`.trim()}>
          {point.change_percent ? formatPercent(point.change_percent) : '—'}
        </dd>
        <dt>Completeness</dt>
        <dd>
          <StateGlyph state={point.completeness} /> {point.completeness}
        </dd>
      </dl>
    </div>
  )
}

export function NetWorth() {
  const { currency, from, to } = useViewState()
  const [dimension, setDimension] = useState<string>('type')
  /** Which month the pointer is over — the plot draws its own band, as the
      dashboard's three do, so the highlight sits behind the line. */
  const [hover, setHover] = useState<string | null>(null)

  const netWorth = useNetWorth(to, currency)
  const trend = useNetWorthTrend(from, to, currency)
  const slice = useNetWorthSlice(to, currency, dimension)

  const chart = useMemo(
    () =>
      (trend.data?.points ?? []).map((point) => ({
        month: point.month,
        // null, not 0. Recharts breaks the line on a null, which is the honest
        // rendering of a month nobody recorded anything for.
        total: point.total ? Number(point.total.amount) : null,
        completeness: point.completeness,
      })),
    [trend.data],
  )

  /** The exact figures, by month — what the tooltip states, never the floats
      the chart plots with. */
  const figures = useMemo(
    () =>
      Object.fromEntries(
        (trend.data?.points ?? []).map((point) => [point.month, point]),
      ) as Record<string, TrendPoint>,
    [trend.data],
  )

  /** `activeLabel` is the month, the same handler shape the dashboard uses. */
  const track = (state: MouseHandlerDataParam) => {
    const month = state?.activeLabel
    if (typeof month === 'string') setHover(month)
  }

  if (netWorth.isPending) return <div className="boot">Loading…</div>
  if (!netWorth.data) return <ErrorBanner error={netWorth.error} />

  const { data, completeness, exclusions, rate_provenance: provenance } = netWorth.data
  const points = trend.data?.points ?? []
  const latest = points[points.length - 1]

  return (
    <div className="networth">
      <section className="panel networth__headline">
        <div className="networth__figure">
          <span className="label">Net worth · {data.month}</span>

          {data.total ? (
            <div className="networth__total mono">
              <Amount value={data.total.amount} currency={data.total.currency} />
            </div>
          ) : (
            /* Not zero. Nothing has been recorded for this month yet. */
            <div className="networth__none">
              No balances recorded for {data.month} yet.
            </div>
          )}

          {/* The dashboard's treatment exactly: a fall is Breach, a rise is
              Rise, and the percentage sits inside the colour because it is the
              same movement stated a second way, not a separate qualifier. The
              percentage is absent against a zero prior month, where a rise from
              nothing has no proportion. */}
          {data.total && latest?.change && (
            <div className="networth__change mono">
              <span className={movementClass(latest.change)}>
                {latest.change.startsWith('-') ? '' : '+'}
                {formatDecimal(latest.change)}{' '}
                {latest.change_percent && (
                  <span className="secondary">({latest.change_percent}%)</span>
                )}
              </span>
            </div>
          )}

          {/* Kept here, unlike the dashboard: this is the screen where the
              month's completeness is the reader's own business, not a summary
              of it. The dashboard raises an incomplete month as an outstanding
              task instead. */}
          <div className="networth__state">
            <StateGlyph state={completeness.state as CompletenessState} />
            {completeness.state}
            <span className="secondary">
              {completeness.balances.recorded} of {completeness.balances.expected} balances
            </span>
          </div>

          {/* Only when something is stale. Otherwise nothing is rendered here
              at all — not an empty strip, not a disclosure control. */}
          {data.any_stale && data.as_at && (
            <details className="asat">
              <summary className="asat__summary">
                Rates as at {formatDate(data.as_at)}
              </summary>
              <table className="table asat__detail">
                <tbody>
                  {provenance.map((row) => (
                    <tr key={row.pair}>
                      <td className="mono">{row.pair}</td>
                      <td className="secondary">{formatDate(row.as_at)}</td>
                      <td className="secondary">{row.provenance}</td>
                      <td>{row.stale ? <span className="carry">stale</span> : ''}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </details>
          )}

          {/* The balance is never treated as zero. */}
          {exclusions.length > 0 && (
            <p className="exclusion-notice">
              Excludes {exclusions.length} account{exclusions.length === 1 ? '' : 's'} —{' '}
              {exclusions.map((e) => e.reason).join('; ')}
            </p>
          )}
        </div>

        {/* The same geometry the dashboard's plots use, from @/lib/charts: a
            reader moving between the two screens is comparing shapes, and a
            shorter plot or a narrower gutter exaggerates the same movement. */}
        <div className="networth__chart">
          {chart.length > 0 && (
            <ResponsiveContainer width="100%" height={CHART_HEIGHT}>
              <LineChart
                data={chart}
                margin={CHART_MARGIN}
                onMouseMove={track}
                onMouseLeave={() => setHover(null)}
              >
                <CartesianGrid stroke={GRID} vertical={false} />
                <MonthBand month={hover ?? undefined} />
                <XAxis
                  dataKey="month"
                  scale="band"
                  tick={AXIS_TICK}
                  tickLine={false}
                  axisLine={AXIS_LINE}
                  tickFormatter={formatMonthShort}
                  interval="preserveStartEnd"
                  minTickGap={MIN_TICK_GAP}
                />
                <YAxis
                  tick={AXIS_TICK}
                  tickLine={false}
                  axisLine={false}
                  tickFormatter={compactTick}
                  width={AXIS_WIDTH}
                />
                {/* No cursor rule: the band under the line is the highlight,
                    as it is on the dashboard. */}
                <Tooltip cursor={false} content={<TrendTooltip points={figures} />} />
                <Line
                  type="linear"
                  dataKey="total"
                  stroke={ACCENT}
                  strokeWidth={2}
                  dot={{ r: 2 }}
                  // A gap stays a gap. Joining across months nobody recorded
                  // would draw a trend that did not happen.
                  connectNulls={false}
                  isAnimationActive={false}
                />
              </LineChart>
            </ResponsiveContainer>
          )}
        </div>
      </section>

      <div className="seg networth__toggles" role="group" aria-label="Slice by">
        <span className="label seg__legend">Slice by</span>
        {DIMENSIONS.map((option) => (
          <button
            key={option.key}
            type="button"
            className={`seg__option${dimension === option.key ? ' seg__option--on' : ''}`}
            aria-pressed={dimension === option.key}
            onClick={() => setDimension(option.key)}
          >
            {option.label}
          </button>
        ))}
      </div>

      <div className="networth__tables">
        <section className="panel">
          <h2 className="panel__heading">
            {DIMENSIONS.find((d) => d.key === dimension)?.label}
          </h2>
          {/* Consistent with the headline: a month with nothing recorded has no
              slice to show, rather than one totalling zero. */}
          {!data.total && (
            <p className="fx__note">Nothing recorded for {data.month}.</p>
          )}
          {data.total && slice.data && (
            <table className="table">
              <thead>
                <tr>
                  <th>Group</th>
                  <th />
                  <th className="numeric">Amount</th>
                  <th className="numeric">% of Gross Assets</th>
                </tr>
              </thead>
              <tbody>
                {slice.data.data.rows.map((row) => (
                  <tr key={row.key}>
                    <td>{row.label}</td>
                    <td className="secondary">
                      {row.is_liability ? 'liability' : 'asset'}
                      {row.excluded > 0 && (
                        <span className="excluded"> · {row.excluded} excluded</span>
                      )}
                    </td>
                    <td className="numeric">
                      <Amount value={row.amount} currency={currency} />
                    </td>
                    {/* The amount's own treatment, not the movement one: a
                        liability is Breach because it is owed, and an asset is
                        not a rise. Absent where nothing is owned. */}
                    <td
                      className={`numeric ${
                        row.percent_of_gross?.startsWith('-') ? 'money--breach' : ''
                      }`.trim()}
                    >
                      {row.percent_of_gross ? formatPercent(row.percent_of_gross) : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>

        <section className="panel">
          <h2 className="panel__heading">Month on Month</h2>
          <table className="table">
            <thead>
              <tr>
                <th>Month</th>
                <th className="numeric">Net worth</th>
                <th className="numeric">Change</th>
                <th className="numeric">Change %</th>
                <th className="state-col">Status</th>
              </tr>
            </thead>
            <tbody>
              {/* Months with nothing recorded are omitted entirely rather than
                  listed as zero. Twenty-four rows of 0.00 for months that
                  predate the first account is noise that buries the months that
                  matter. */}
              {[...points]
                .reverse()
                .filter((point) => point.total !== null)
                .map((point) => (
                <tr key={point.month}>
                  <td className="mono">{point.month}</td>
                  <td className="numeric">
                    <Amount value={point.total!.amount} currency={point.total!.currency} />
                  </td>
                  <td className={`numeric ${movementClass(point.change)}`.trim()}>
                    {point.change ? formatDecimal(point.change) : '—'}
                  </td>
                  {/* Em dash on both halves for the oldest month, which has
                      nothing behind it to move from; on the percentage alone
                      where the month before totalled zero, because a rise from
                      nothing has no proportion. */}
                  <td className={`numeric ${movementClass(point.change_percent)}`.trim()}>
                    {point.change_percent ? formatPercent(point.change_percent) : '—'}
                  </td>
                  {/* The glyph carries its state as its accessible name, so the
                      word is not lost with it — including Outside Range, which
                      is a month before the first account, not a failure. */}
                  <td className="state-col">
                    <StateGlyph state={point.completeness} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      </div>
    </div>
  )
}
