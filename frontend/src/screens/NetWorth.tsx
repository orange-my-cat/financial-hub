/**
 * Net worth — the landing report, and the screen answering the driving question.
 *
 * Slice toggles are the whole interaction model. Toggling swaps the grouping of
 * the lower table only; the chart and the headline are unchanged, and there is
 * **no drill-down** anywhere.
 *
 * The slice table sorts on its three real columns — the group, the amount and
 * the share of gross assets — and its column widths are pinned, so a toggle
 * changes what the rows say and never where the columns are. Sorting is a
 * rearrangement of rows the server already sent, in the browser: no figure is
 * recomputed, and the amounts are ordered as exact decimals rather than parsed
 * to floats to be compared (ADR-12).
 *
 * The screen reads two different questions at once, and the two view controls
 * divide cleanly between them. The **date range** governs the trend plot and
 * the month-on-month table below it — how net worth moved. The **spine**
 * selects the single month the headline figure and the slice table report —
 * what it is at a moment. Changing months on the spine therefore restates the
 * top figure and re-slices the table beneath it, and leaves the plot and the
 * month-on-month table exactly as they were.
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
  FIT_DOMAIN,
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
  movementClass,
} from '@/lib/format'
import { compareDecimals } from '@/lib/money'
import { shiftMonths, useViewState } from '@/lib/viewState'
import { icons } from '@/shell/icons'

const DIMENSIONS = [
  { key: 'type', label: 'Account Type' },
  { key: 'liquidity', label: 'Liquidity Tier' },
  { key: 'currency', label: 'Currency' },
  { key: 'account', label: 'Account' },
] as const

type SortColumn = 'group' | 'amount' | 'percent'
type SortDirection = 'asc' | 'desc'

interface Sort {
  readonly column: SortColumn
  readonly direction: SortDirection
}

/**
 * Which way a column runs when it is first clicked.
 *
 * Descending on the two figures, because a reader clicking Amount is looking
 * for the largest thing in the table and not the smallest. Ascending on Group,
 * which is the order the table already arrived in — the first click on it is a
 * way back rather than a rearrangement.
 */
const FIRST_DIRECTION: Record<SortColumn, SortDirection> = {
  group: 'asc',
  amount: 'desc',
  percent: 'desc',
}

/** A comparison read the way the column is running. */
function direct(ranking: number, direction: SortDirection): number {
  return direction === 'asc' ? ranking : -ranking
}

/**
 * The slice table's columns, pinned.
 *
 * Under automatic layout each slicing sizes its own columns to its own
 * content, so toggling from Currency to Account Type — three-letter labels to
 * "Investment/Brokerage" — walks the Amount column across the panel and the
 * reader re-finds the figures every time they change the question. The whole
 * interaction model of this screen is toggling that grouping, which makes the
 * jump land on the one control the screen is built around. Pinned as they are
 * on Accounts, Investments and Cash flow.
 *
 * The label takes the width because it is the only column with no fixed
 * vocabulary and no bound on its length: an account name is free text, where
 * every other column here holds a figure of known width or one of two words.
 */
function SliceColumns() {
  return (
    <colgroup>
      <col style={{ width: '32%' }} />
      <col style={{ width: '18%' }} />
      <col style={{ width: '26%' }} />
      <col style={{ width: '24%' }} />
    </colgroup>
  )
}

/**
 * A column heading that sorts, and states which way it is running.
 *
 * `aria-sort` is on the cell rather than the button because that is the
 * element a screen reader announces as the column heading, and it carries the
 * direction in words — so the arrow beside the label is free to be decoration
 * and is hidden from the reading.
 */
function SortHeader({
  column,
  label,
  sort,
  onSort,
  className,
}: {
  readonly column: SortColumn
  readonly label: string
  readonly sort: Sort
  readonly onSort: (column: SortColumn) => void
  readonly className?: string
}) {
  const active = sort.column === column
  // Unsorted, the arrow shows the direction a click would give, not a state the
  // column is in — which is why it only surfaces on hover.
  const direction = active ? sort.direction : FIRST_DIRECTION[column]

  return (
    <th
      className={`sortable${className ? ` ${className}` : ''}`}
      aria-sort={active ? (sort.direction === 'asc' ? 'ascending' : 'descending') : 'none'}
    >
      <button type="button" className="sort" onClick={() => onSort(column)}>
        {label}
        <span className="sort__arrow">
          {direction === 'asc' ? icons.sortAscending : icons.sortDescending}
        </span>
      </button>
    </th>
  )
}

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
  // `month` is the spine's selection; `from`/`to` are the reporting range. The
  // two are separate values and this screen is the reason: it reports one month
  // and a run of months side by side.
  const { currency, from, to, month } = useViewState()
  const [dimension, setDimension] = useState<string>('type')
  /**
   * How the slice table is ordered — kept across a change of slicing, because
   * "largest first" is a question about the table and not about which grouping
   * is under it, and a reader comparing the top of one slicing against the top
   * of another would otherwise have to re-sort at every toggle.
   */
  const [sort, setSort] = useState<Sort>({ column: 'group', direction: 'asc' })
  /** Which month the pointer is over — the plot draws its own band, as the
      dashboard's three do, so the highlight sits behind the line. */
  const [hover, setHover] = useState<string | null>(null)

  const netWorth = useNetWorth(month, currency)
  const trend = useNetWorthTrend(from, to, currency)
  const slice = useNetWorthSlice(month, currency, dimension)

  /**
   * How the selected month moved — its own two-month window, not a reading off
   * the plot's trend.
   *
   * The net worth payload carries a total and no movement, so the change has to
   * come from the trend service either way; the question is which trend. Taking
   * it from the plot's would tie the headline to the reporting range, and the
   * same selected month would gain and lose its change line as the reader
   * moved the range end around it — or lose it outright for a month the spine
   * can reach but the range does not cover. The headline is a month-at-a-time
   * figure and asks a month-at-a-time question.
   *
   * The server computes the movement, as it must: money carries no arithmetic
   * in the browser (ADR-12), so subtracting two totals here is not an option.
   */
  const movement = useNetWorthTrend(shiftMonths(month, -1), month, currency)

  /**
   * The slice rows in the reader's order.
   *
   * Sorted here rather than asked of the server: the rows are a dozen at most,
   * they are already in hand, and a round trip to reverse a column the reader
   * is looking at would put a spinner in the way of a rearrangement.
   *
   * Ordering only — no figure is computed, combined or re-derived, and the
   * amounts are compared as the exact decimals the server sent (ADR-12).
   * `Number(a) - Number(b)` would be the ordinary way to do this and it is a
   * float comparison of money, which is the one thing this application does
   * not do.
   *
   * Group is the order the payload arrived in, which is the dimension's own:
   * the vocabulary sequence for Account Type and Liquidity Tier, alphabetical
   * for Currency and Account. That matters more than it looks — sorting the
   * tiers by their labels would order them Instant, Locked, Long, Short and
   * destroy the one thing the tier names mean, which is how soon the money can
   * be reached.
   */
  const rows = useMemo(() => {
    const delivered = slice.data?.data.rows ?? []
    const indexed = delivered.map((row, index) => ({ row, index }))

    indexed.sort((a, b) => {
      if (sort.column === 'percent') {
        const left = a.row.percent_of_gross
        const right = b.row.percent_of_gross
        // A row with no proportion is not a row with a small one — nothing is
        // owned to measure it against. It keeps the foot of the table whichever
        // way the column runs, rather than being ranked as if it were zero.
        if (left === null || right === null) {
          if (left === right) return a.index - b.index
          return left === null ? 1 : -1
        }
        return direct(compareDecimals(left, right), sort.direction) || a.index - b.index
      }

      if (sort.column === 'amount') {
        return (
          direct(compareDecimals(a.row.amount, b.row.amount), sort.direction) ||
          a.index - b.index
        )
      }

      return direct(a.index - b.index, sort.direction)
    })

    return indexed.map((entry) => entry.row)
  }, [slice.data, sort])

  const resort = (column: SortColumn) =>
    setSort((current) =>
      current.column === column
        ? { column, direction: current.direction === 'asc' ? 'desc' : 'asc' }
        : { column, direction: FIRST_DIRECTION[column] },
    )

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
    const hovered = state?.activeLabel
    if (typeof hovered === 'string') setHover(hovered)
  }

  if (netWorth.isPending) return <div className="boot">Loading…</div>
  if (!netWorth.data) return <ErrorBanner error={netWorth.error} />

  const { data, completeness, exclusions, rate_provenance: provenance } = netWorth.data
  const points = trend.data?.points ?? []
  // Keyed by month rather than taken from the end of the two: the window's
  // second point is the selected month, and saying so is cheaper to read than
  // trusting the order.
  const selected = movement.data?.points.find((point) => point.month === month)

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
          {data.total && selected?.change && (
            <div className="networth__change mono">
              <span className={movementClass(selected.change)}>
                {selected.change.startsWith('-') ? '' : '+'}
                {formatDecimal(selected.change)}{' '}
                {selected.change_percent && (
                  <span className="secondary">({selected.change_percent}%)</span>
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
                  domain={FIT_DOMAIN}
                />
                {/* No cursor rule: the band under the line is the highlight,
                    as it is on the dashboard. */}
                <Tooltip cursor={false} content={<TrendTooltip points={figures} />} />
                <Line
                  type="linear"
                  dataKey="total"
                  stroke={ACCENT}
                  strokeWidth={2}
                  dot={false}
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
            <table className="table table--fixed">
              <SliceColumns />
              <thead>
                <tr>
                  <SortHeader column="group" label="Group" sort={sort} onSort={resort} />
                  {/* Unheaded, and unsortable with it: the column carries a
                      row's side of the balance sheet and its exclusions, both
                      of which are attributes of the group named beside them
                      rather than a column a reader arranges the table by. */}
                  <th />
                  <SortHeader
                    column="amount"
                    label="Amount"
                    sort={sort}
                    onSort={resort}
                    className="numeric"
                  />
                  <SortHeader
                    column="percent"
                    label="% of Gross Assets"
                    sort={sort}
                    onSort={resort}
                    className="numeric"
                  />
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
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
