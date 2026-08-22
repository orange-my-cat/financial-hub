/**
 * Account detail — the screen the driving question is actually asked of.
 *
 *     Is the balance of this account increasing, and what is its trend?
 *     For any single account, in under thirty seconds.
 *
 * Answered by showing the shape, not by narrating it: the plot, the month-on-
 * month and twelve-month figures, and the table underneath.
 *
 * Everything is in **the account's own currency**. The reporting-currency
 * control does not apply: translating would fold rate movement into a figure the
 * user wants to read as their own money. The currency tag carries this; there is
 * no explanatory subhead.
 *
 * Balances are entered snapshots, so the screen can show *that* a balance moved
 * but generally not *why*.
 */

import { useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import {
  CartesianGrid,
  Line,
  LineChart,
  type MouseHandlerDataParam,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import { ErrorBanner } from '@/components/Advisories'
import { MonthBand } from '@/components/MonthBand'
import { type HistoryRow, useAccountHistory } from '@/lib/accounts'
import {
  ACCENT,
  AXIS_LINE,
  AXIS_TICK,
  AXIS_WIDTH,
  CHART_HEIGHT,
  CHART_MARGIN,
  compactTick,
  FIT_DOMAIN,
  GRID,
  MIN_TICK_GAP,
} from '@/lib/charts'
import {
  formatDecimal,
  formatMonth,
  formatMonthShort,
  formatPercent,
  movementClass,
} from '@/lib/format'
import { DEFAULT_RANGE_MONTHS, shiftMonths } from '@/lib/viewState'

/**
 * The dashboard's hover treatment, on this screen's one plot.
 *
 * Same box as the net worth trend — month at the head, a two-column list under
 * it — because a reader moving between the two screens is reading the same kind
 * of line and a differently arranged box would make the figures look like
 * different figures. It states the balance and nothing else: the change and its
 * proportion belong to the table below, and this account's line has only one
 * figure per month to give.
 *
 * The figure is formatted from the server's string, never from the float the
 * chart plots with: the geometry may be approximate, the figure never is. The
 * month comes from `label` rather than the payload, as it does on net worth.
 */
function BalanceTooltip({
  active,
  label,
  currency,
  balances,
}: {
  readonly active?: boolean
  readonly label?: string | number
  readonly currency: string
  readonly balances: Readonly<Record<string, HistoryRow>>
}) {
  const month = active && typeof label === 'string' ? label : undefined
  const row = month ? balances[month] : undefined
  if (!month || !row) return null

  return (
    <div className="charttip">
      <div className="charttip__month mono">{formatMonth(month)}</div>
      <dl className="charttip__list">
        <dt>Balance</dt>
        <dd className="mono">
          {formatDecimal(row.amount)} {currency}
        </dd>
      </dl>
    </div>
  )
}

export function AccountDetail() {
  const { accountId } = useParams()
  const query = useAccountHistory(Number(accountId))
  /** Which month the pointer is over — the plot draws its own band, as the
      dashboard's three do, so the highlight sits behind the line. */
  const [hover, setHover] = useState<string | null>(null)

  /**
   * Contiguous months ending at the latest recorded one — not the latest N
   * *records*. An account with a gap in its history has to plot that gap as a
   * gap: laying the records side by side would join across a month nobody
   * recorded and draw a trend that did not happen, which is the reason the
   * dashboard's plot carries nulls too.
   *
   * The window is the reports' own default length, so the plot spans the same
   * months the dashboard's does.
   */
  const chart = useMemo(() => {
    const history = query.data?.history ?? []
    const latest = history[0]?.month
    if (!latest) return []

    const recorded = new Map(history.map((row) => [row.month, Number(row.amount)]))
    return Array.from({ length: DEFAULT_RANGE_MONTHS }, (_, offset) => {
      const month = shiftMonths(latest, offset - (DEFAULT_RANGE_MONTHS - 1))
      // null, not 0. Recharts breaks the line on a null, which is the honest
      // rendering of a month with no balance recorded (BR-04).
      return { month, amount: recorded.get(month) ?? null }
    })
  }, [query.data])

  /** How many months the line actually has. One point is not a trend. */
  const plotted = chart.filter((point) => point.amount !== null).length

  /** The exact figures, by month — what the tooltip states, never the floats
      the chart plots with. */
  const balances = useMemo(
    () =>
      Object.fromEntries((query.data?.history ?? []).map((row) => [row.month, row])),
    [query.data],
  )

  /** `activeLabel` is the month, the same handler shape the dashboard uses. */
  const track = (state: MouseHandlerDataParam) => {
    const hovered = state?.activeLabel
    if (typeof hovered === 'string') setHover(hovered)
  }

  if (query.isPending) return <div className="boot">Loading…</div>
  if (!query.data) return <ErrorBanner error={query.error} />

  const { account, history, movement } = query.data
  const latest = history[0]

  /** The panel's three rows, in the order it states them. */
  const offsets = [
    { label: 'Month on month', moved: movement.month_on_month },
    { label: 'Quarter on quarter', moved: movement.quarter_on_quarter },
    { label: 'Year on year', moved: movement.year_on_year },
  ]

  return (
    <div className="detail">
      <nav className="detail__crumb">
        <Link to="/accounts">Accounts</Link>
        <span className="secondary"> / {account.name}</span>
      </nav>

      <h2 className="detail__name">{account.name}</h2>

      <div className="detail__tags">
        <span className="tag">{account.account_type}</span>
        <span className="tag">{account.liquidity_tier}</span>
        <span className="tag">{account.status}</span>
        <span className="tag mono">{account.currency}</span>
        <span className="secondary">Opened {formatMonth(account.opened_month)}</span>
        {account.closed_month && (
          <span className="secondary">Closed {formatMonth(account.closed_month)}</span>
        )}
      </div>

      {history.length === 0 ? (
        <section className="panel">
          <p className="fx__note">No balances recorded for this account yet.</p>
        </section>
      ) : (
        <div className="detail__body">
          <section className="panel detail__figure">
            <span className="label">
              Balance · {latest && formatMonth(latest.month)}
            </span>
            <div className="networth__total mono">
              {formatDecimal(latest?.amount ?? '0')}
              <span className="money__code">{account.currency}</span>
            </div>

            {/* All three from the server, over calendar offsets. An em dash
                where the month being compared against has no balance — the
                account has not been going a year, or that month was never
                recorded, and neither is a movement of zero. */}
            <dl className="detail__stats">
              {offsets.map(({ label, moved }) => (
                <div key={label}>
                  <dt className="label">{label}</dt>
                  <dd
                    className={`mono ${movementClass(
                      moved.change,
                      account.is_liability,
                    )}`.trim()}
                  >
                    {moved.change ? formatDecimal(moved.change) : '—'}
                    {/* The same movement stated a second way, not a separate
                        qualifier — so it takes the colour of the figure it
                        follows and carries no sign of its own. Absent against a
                        zero prior month, where a rise from nothing has no
                        proportion. */}
                    {moved.change && moved.change_percent && (
                      <span className="secondary">
                        {' '}
                        ({formatDecimal(moved.change_percent, 1)}%)
                      </span>
                    )}
                  </dd>
                </div>
              ))}
            </dl>
          </section>

          {/* The dashboard's net worth plot, on this account's balances: the
              same geometry from @/lib/charts, the same drawn month band and the
              same hover box, because a reader moving from the dashboard to one
              account is comparing shapes, and a shorter plot or a narrower
              gutter exaggerates the same movement. */}
          {plotted > 1 && (
            <section className="panel detail__trend">
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
                  <Tooltip
                    cursor={false}
                    content={
                      <BalanceTooltip currency={account.currency} balances={balances} />
                    }
                  />
                  <Line
                    type="linear"
                    dataKey="amount"
                    stroke={ACCENT}
                    strokeWidth={2}
                    dot={false}
                    // A gap stays a gap, as on the dashboard.
                    connectNulls={false}
                    isAnimationActive={false}
                  />
                </LineChart>
              </ResponsiveContainer>
            </section>
          )}

          <section className="panel detail__history">
            <table className="table">
              <thead>
                <tr>
                  <th>Month</th>
                  <th className="numeric">Balance</th>
                  <th className="numeric">Change</th>
                  <th className="numeric">Change %</th>
                </tr>
              </thead>
              <tbody>
                {history.map((row) => (
                  <tr key={row.month}>
                    {/* The month key, not a formatted month: the column is a
                        list of keys to scan and sort by, and it matches the
                        trend table on Net Worth. */}
                    <td className="mono">{row.month}</td>
                    <td className="numeric">{formatDecimal(row.amount)}</td>
                    {/* Rise or Breach on the sign, inverted for an account
                        that is owed: a credit card climbing is more debt, not a
                        good month. */}
                    <td
                      className={`numeric ${movementClass(
                        row.change,
                        account.is_liability,
                      )}`.trim()}
                    >
                      {row.change ? formatDecimal(row.change) : '—'}
                    </td>
                    {/* Em dash on both halves for the oldest month, which has
                        nothing behind it to move from; on the percentage alone
                        where the month before was zero, because a rise from
                        nothing has no proportion. */}
                    <td
                      className={`numeric ${movementClass(
                        row.change_percent,
                        account.is_liability,
                      )}`.trim()}
                    >
                      {row.change_percent ? formatPercent(row.change_percent) : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        </div>
      )}
    </div>
  )
}
