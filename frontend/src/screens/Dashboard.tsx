/**
 * Dashboard — fixed layout, built last, deliberately.
 *
 * RISK-06 notes this is the most expensive screen and the most likely to be
 * rebuilt once real use reveals what is actually looked at. So it does one
 * thing, in one order, and offers nothing to configure: no widgets, no drag and
 * drop, no personalisation.
 *
 * Panel order is fixed:
 *
 *   1. **Outstanding tasks** — the only bordered panel on the screen, because
 *      it is the product's conscience. Everything else reports; this asks, so
 *      it asks before anything else has a chance to reassure.
 *   2. Net worth and its 24-month trend
 *   3. Cash flow for the month in the reporting currency — income, expenses,
 *      net and savings rate
 *   4. Investments by currency, never combined
 *   5. Backup status
 *
 * Two things appear only when they need to. When every contributing rate is
 * fresh there is no as-at strip and no disclosure control; when nothing is
 * outstanding the tasks panel is absent entirely, rather than saying so. Both
 * are the same rule: silence is the signal, and a panel that is present has
 * something to say.
 */

import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  type MouseHandlerDataParam,
} from 'recharts'
import { useState } from 'react'
import { Link } from 'react-router-dom'

import { ErrorBanner } from '@/components/Advisories'
import { MonthBand } from '@/components/MonthBand'
import {
  ACCENT,
  AXIS_LINE,
  AXIS_TICK,
  AXIS_WIDTH,
  BREACH,
  CHART_HEIGHT,
  CHART_MARGIN,
  GRID,
  MIN_TICK_GAP,
  RISE,
  compactTick,
} from '@/lib/charts'
import { useDashboard, type FigureChange } from '@/lib/dashboard'
import { formatDate, formatDecimal, formatMonth, formatMonthShort } from '@/lib/format'
import { useViewState } from '@/lib/viewState'

function Amount({ value, currency }: { readonly value: string; readonly currency: string }) {
  return (
    <span className={`money ${value.startsWith('-') ? 'money--breach' : ''}`.trim()}>
      {formatDecimal(value)}
      <span className="money__code">{currency}</span>
    </span>
  )
}

/**
 * A figure's month-on-month movement, under the figure itself.
 *
 * `goodWhenRising` is the whole point of the prop. Income up is Rise and income
 * down is Breach — but **expenses up is Breach**, because more spending is not
 * good news, and painting it green because the number grew would be the colour
 * contradicting the figure. Direction and judgement are two different things,
 * and only the figure knows which way round they sit.
 *
 * `unit` is `pts` for the savings rate: the change in a percentage is
 * percentage points, not a percentage, and the two are not the same figure.
 */
function Change({
  change,
  goodWhenRising = true,
  unit = '',
}: {
  readonly change: FigureChange
  readonly goodWhenRising?: boolean
  readonly unit?: string
}) {
  if (change.change === null) return null

  const falling = change.change.startsWith('-')
  const good = falling !== goodWhenRising

  return (
    <div className="cashsum__change mono">
      {/* The percentage sits inside the colour, as it does on net worth: it is
          the same movement stated a second way, not a separate qualifier. */}
      <span className={good ? 'money--rise' : 'money--breach'}>
        {falling ? '' : '+'}
        {formatDecimal(change.change, unit ? 1 : 2)}
        {unit}{' '}
        {change.change_percent && (
          <span className="secondary">({change.change_percent}%)</span>
        )}
      </span>
    </div>
  )
}

/** Which of the three plots the pointer is over, and on which month. */
interface Hover {
  readonly plot: 'worth' | 'flow' | 'rate'
  readonly month: string
}

/** Everything the screen knows about one month, in one place. */
interface MonthFigures {
  readonly worth: string | null
  readonly completeness: string
  readonly income: string
  readonly expense: string
  readonly net: string
  readonly savings_rate: string | null
}

/**
 * One tooltip for all three plots, stating all five figures for the month.
 *
 * The same box wherever the pointer is, because the question a shared axis
 * invites is "what else was happening that month" — answering it differently
 * depending on which plot happened to be under the cursor would make the
 * reader hunt for the panel that shows the figure they want.
 *
 * Every figure is formatted from the server's string, never from the float the
 * chart plots with: the geometry may be approximate, the figures never are.
 * The month comes from `label` rather than from the payload, because a month
 * with no net worth has no payload entry on the trend and would otherwise
 * silently lose its tooltip.
 */
function MonthTooltip({
  active,
  label,
  currency,
  show,
  figures,
}: {
  readonly active?: boolean
  readonly label?: string | number
  readonly currency: string
  readonly show: boolean
  readonly figures: Readonly<Record<string, MonthFigures>>
}) {
  const month = active && show && typeof label === 'string' ? label : undefined
  const row = month ? figures[month] : undefined
  if (!month || !row) return null

  return (
    <div className="charttip">
      <div className="charttip__month mono">{formatMonth(month)}</div>
      <dl className="charttip__list">
        <dt>Net Worth</dt>
        <dd className="mono">
          {/* A month before any balance existed has no net worth — not one of
              zero (BR-04). The tooltip says so rather than printing a figure. */}
          {row.worth === null ? '—' : `${formatDecimal(row.worth)} ${currency}`}
        </dd>
        <dt>Income</dt>
        <dd className="mono" style={{ color: RISE }}>
          {formatDecimal(row.income)} {currency}
        </dd>
        <dt>Expenses</dt>
        <dd className="mono" style={{ color: BREACH }}>
          {formatDecimal(row.expense)} {currency}
        </dd>
        <dt>Net</dt>
        <dd
          className={`mono ${row.net.startsWith('-') ? 'money--breach' : 'money--rise'}`}
        >
          {formatDecimal(row.net)} {currency}
        </dd>
        <dt>Savings Rate</dt>
        <dd className="mono">
          {/* No income is no denominator, in the tooltip as on the figure. */}
          {row.savings_rate === null ? '—' : `${row.savings_rate}%`}
        </dd>
      </dl>
    </div>
  )
}

export function Dashboard() {
  const { currency, to } = useViewState()
  const dashboard = useDashboard(to, currency)
  const [hover, setHover] = useState<Hover | null>(null)

  /** One handler shape for all three plots — `activeLabel` is the month. */
  const track = (plot: Hover['plot']) => (state: MouseHandlerDataParam) => {
    const month = state?.activeLabel
    if (typeof month === 'string') setHover({ plot, month })
  }

  if (dashboard.isPending) return <div className="boot">Loading…</div>
  if (!dashboard.data) return <ErrorBanner error={dashboard.error} />

  const data = dashboard.data
  const flow = data.cashflow

  /*
    Income above the baseline, expenses below it. Position carries the
    distinction, not colour: green against red is the one pair a red-green
    colour-blind reader cannot separate (ΔE 5.4 under deuteranopia), and the
    palette is fixed by the design handoff, so the encoding has to survive
    without it. Rise and Breach then reinforce what the baseline already said.
  */
  const flowChart = data.cashflow_trend.map((point) => ({
    month: point.month,
    income: Number(point.income),
    expense: -Number(point.expense),
    rate: point.savings_rate === null ? null : Number(point.savings_rate),
  }))
  const hasFlow = flowChart.some((p) => p.income !== 0 || p.expense !== 0)

  const chart = data.trend.map((point) => ({
    month: point.month,
    total: point.total ? Number(point.total) : null,
  }))
  const hasHistory = chart.some((point) => point.total !== null)

  /*
    The two trends, merged by month for the shared tooltip. Keyed by month
    rather than zipped by index: the server sends one window to both, and a
    lookup that would produce nothing if that ever stopped being true is
    better than one that would quietly pair the wrong figures.
  */
  const flowByMonth = new Map(data.cashflow_trend.map((row) => [row.month, row]))
  const figures: Record<string, MonthFigures> = {}
  for (const worth of data.trend) {
    const cash = flowByMonth.get(worth.month)
    if (!cash) continue
    figures[worth.month] = {
      worth: worth.total,
      completeness: worth.completeness,
      income: cash.income,
      expense: cash.expense,
      net: cash.net,
      savings_rate: cash.savings_rate,
    }
  }

  return (
    <div className="dash">
      {/*
        1 — Outstanding tasks, first on the screen and the only bordered panel
        on it, because this panel is the product's conscience. Everything else
        reports; this asks.

        It is not rendered at all when nothing is outstanding — no heading, no
        "nothing outstanding" line. Silence is the signal, so the panel's
        presence alone means there is something to do.
      */}
      {data.tasks.length > 0 && (
        <section className="tasks">
          <h2 className="panel__heading">Outstanding</h2>
          <ul className="tasks__list">
            {data.tasks.map((task) => (
              <li className="tasks__row" key={task.kind}>
                <span className={`tasks__count mono ${task.breach ? 'breach' : 'carry'}`}>
                  {task.count}
                </span>
                <span className="tasks__message">{task.message}</span>
                <Link className="tasks__link" to={task.route}>
                  Resolve
                </Link>
              </li>
            ))}
          </ul>
        </section>
      )}

      {/* 2 — Net worth */}
      <section className="panel dash__networth">
        <div className="dash__figure">
          <span className="label">Net worth</span>

          {data.net_worth.total ? (
            <>
              <div className="networth__total mono">
                <Amount
                  value={data.net_worth.total.amount}
                  currency={data.net_worth.total.currency}
                />
              </div>
              {data.net_worth.change && (
                <div className="networth__change mono">
                  <span
                    className={
                      data.net_worth.change.startsWith('-')
                        ? 'money--breach'
                        : 'money--rise'
                    }
                  >
                    {data.net_worth.change.startsWith('-') ? '' : '+'}
                    {formatDecimal(data.net_worth.change)}{' '}
                    {data.net_worth.change_percent && (
                      <span className="secondary">
                        ({data.net_worth.change_percent}%)
                      </span>
                    )}
                  </span>
                </div>
              )}
            </>
          ) : (
            <div className="networth__none">
              No balances recorded for {data.month} yet.
            </div>
          )}

          {/* Only when a contributing rate is stale. */}
          {data.net_worth.any_stale && data.net_worth.as_at && (
            <details className="asat">
              <summary className="asat__summary">
                Rates as at {formatDate(data.net_worth.as_at)}
              </summary>
              <table className="table asat__detail">
                <tbody>
                  {data.rate_provenance.map((row) => (
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

          {/* Only when an account had no rate. Never shown as zero. */}
          {data.exclusions.length > 0 && (
            <p className="exclusion-notice">
              Excludes {data.exclusions.length} account
              {data.exclusions.length === 1 ? '' : 's'} —{' '}
              {data.exclusions.map((row) => row.reason).join('; ')}
            </p>
          )}
        </div>

        <div className="dash__chart">
          {hasHistory && (
            <ResponsiveContainer width="100%" height={CHART_HEIGHT}>
              <LineChart
                data={chart}
                margin={CHART_MARGIN}
                onMouseMove={track('worth')}
                onMouseLeave={() => setHover(null)}
              >
                <CartesianGrid stroke={GRID} vertical={false} />
                <MonthBand month={hover?.month} />
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
                <Tooltip
                  cursor={false}
                  content={
                    <MonthTooltip
                      currency={currency}
                      show={hover?.plot === 'worth'}
                      figures={figures}
                    />
                  }
                />
                <Line
                  type="linear"
                  dataKey="total"
                  stroke={ACCENT}
                  strokeWidth={2}
                  dot={false}
                  connectNulls={false}
                  isAnimationActive={false}
                />
              </LineChart>
            </ResponsiveContainer>
          )}
        </div>
      </section>

      {/*
        3 — Cash flow. In the reporting currency, never added to a balance.

        Laid out like net worth above it and on the same grid: the month's
        figures in the 330px column, the plots in the rest. That is what puts
        all three plots on one x axis — one column width, one axis gutter, one
        24-month window, so a month sits at the same place down the whole page.
      */}
      <section className="panel dash__networth">
        {!flow.income || !flow.expense || !flow.net ? (
          <>
            <div className="dash__figure">
              <p className="fx__note">Nothing recorded.</p>
            </div>
            <div />
          </>
        ) : (
          <>
            <div className="dash__figure">
              <div className="cashsum">
                <div className="cashsum__figure">
                  <span className="label">Income</span>
                  <div className="cashsum__value mono">
                    <Amount value={flow.income.amount} currency={flow.income.currency} />
                  </div>
                  <Change change={flow.change.income} />
                </div>
                <div className="cashsum__figure">
                  <span className="label">Expenses</span>
                  <div className="cashsum__value mono">
                    <Amount value={flow.expense.amount} currency={flow.expense.currency} />
                  </div>
                  {/* The one figure where up is the bad direction. */}
                  <Change change={flow.change.expense} goodWhenRising={false} />
                </div>
                <div className="cashsum__figure">
                  <span className="label">Net</span>
                  <div
                    className={`cashsum__value mono ${
                      flow.net.amount.startsWith('-') ? 'money--breach' : 'money--rise'
                    }`}
                  >
                    <Amount value={flow.net.amount} currency={flow.net.currency} />
                  </div>
                  <Change change={flow.change.net} />
                </div>
                <div className="cashsum__figure">
                  <span className="label">Savings rate</span>
                  <div className="cashsum__value mono">
                    {flow.savings_rate === null ? (
                      /* No income is no denominator. Not a rate of zero. */
                      <span className="secondary">—</span>
                    ) : (
                      <span
                        className={
                          flow.savings_rate.startsWith('-')
                            ? 'money--breach'
                            : 'money--rise'
                        }
                      >
                        {flow.savings_rate}%
                      </span>
                    )}
                  </div>
                  <Change change={flow.change.savings_rate} unit=" pts" />
                </div>
              </div>

              {/* Only when a contributing rate is stale. */}
              {flow.any_stale && flow.as_at && (
                <details className="asat">
                  <summary className="asat__summary">
                    Rates as at {formatDate(flow.as_at)}
                  </summary>
                  <table className="table asat__detail">
                    <tbody>
                      {flow.rate_provenance.map((row) => (
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

              {/* A currency with no rate is withheld from all four figures — it
                  is never counted as zero, and the omission is stated (FR-46). */}
              {flow.exclusions.length > 0 && (
                <p className="exclusion-notice">
                  Excludes {flow.exclusions.map((row) => row.currency).join(', ')} —{' '}
                  {flow.exclusions.map((row) => row.reason).join('; ')}
                </p>
              )}
            </div>

            {/*
              Two plots, one shared month axis — never one plot with two y
              scales. Money and a percentage have no common scale, and aligning
              them invents a correlation the data does not contain.
            */}
            <div className="dash__chart">
              {hasFlow && (
                <div className="flowchart">
                  {/* The height includes the axis band, so the plot itself is
                      not squeezed by the months printed under it. */}
                  <ResponsiveContainer width="100%" height={CHART_HEIGHT}>
                    <BarChart
                      data={flowChart}
                      margin={CHART_MARGIN}
                      barCategoryGap="28%"
                      onMouseMove={track('flow')}
                      onMouseLeave={() => setHover(null)}
                    >
                      <CartesianGrid stroke={GRID} vertical={false} />
                      <MonthBand month={hover?.month} />
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
                      <ReferenceLine y={0} stroke="rgba(233,233,237,.22)" />
                      <Tooltip
                        cursor={false}
                        content={
                          <MonthTooltip
                            currency={currency}
                            show={hover?.plot === 'flow'}
                            figures={figures}
                          />
                        }
                      />
                      {/* One slot per month: positives stack up, negatives down. */}
                      <Bar
                        dataKey="income"
                        stackId="flow"
                        fill={RISE}
                        radius={[4, 4, 0, 0]}
                        maxBarSize={14}
                        isAnimationActive={false}
                      />
                      <Bar
                        dataKey="expense"
                        stackId="flow"
                        fill={BREACH}
                        radius={[0, 0, 4, 4]}
                        maxBarSize={14}
                        isAnimationActive={false}
                      />
                    </BarChart>
                  </ResponsiveContainer>

                  <ResponsiveContainer width="100%" height={CHART_HEIGHT}>
                    <LineChart
                      data={flowChart}
                      margin={CHART_MARGIN}
                      onMouseMove={track('rate')}
                      onMouseLeave={() => setHover(null)}
                    >
                      <CartesianGrid stroke={GRID} vertical={false} />
                      <MonthBand month={hover?.month} />
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
                        tickFormatter={(value: number) => `${value}%`}
                        width={AXIS_WIDTH}
                      />
                      <ReferenceLine y={0} stroke="rgba(233,233,237,.22)" />
                      <Tooltip
                        cursor={false}
                        content={
                          <MonthTooltip
                            currency={currency}
                            show={hover?.plot === 'rate'}
                            figures={figures}
                          />
                        }
                      />
                      {/* A month that earned nothing has no rate, so the line
                          breaks rather than dropping through zero. */}
                      <Line
                        type="linear"
                        dataKey="rate"
                        stroke={ACCENT}
                        strokeWidth={2}
                        dot={false}
                        connectNulls={false}
                        isAnimationActive={false}
                      />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              )}
            </div>
          </>
        )}
      </section>

      {/* 4 — Investments. Never combined across currencies. */}
      <section className="panel">
        <h2 className="panel__heading">Investments</h2>
        <p className="fx__note">
          In each holding’s own currency, never combined. Realised gains only — no
          unrealised gain exists in this system.
        </p>
        {data.investments.length === 0 ? (
          <p className="fx__note">No holdings.</p>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>Currency</th>
                <th className="numeric">Holdings</th>
                <th className="numeric">Cost basis</th>
                <th className="numeric">Realised gain this year</th>
              </tr>
            </thead>
            <tbody>
              {data.investments.map((block) => (
                <tr key={block.currency}>
                  <td className="mono">{block.currency}</td>
                  <td className="numeric secondary">{block.holdings}</td>
                  <td className="numeric">{formatDecimal(block.cost_basis)}</td>
                  <td className="numeric">{formatDecimal(block.realised_gain_this_year)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      {/* 5 — Backup. The control that closes RISK-02 in fact. */}
      <section className={`backup ${data.backup.healthy ? '' : 'backup--warn'}`.trim()}>
        <span className={`backup__dot ${data.backup.healthy ? 'ok' : 'warn'}`} />
        <span className="backup__state">{data.backup.state}</span>
        {data.backup.newest_at && (
          <span className="secondary mono">
            {formatDate(data.backup.newest_at.slice(0, 10))}
            {data.backup.count > 1 && ` · ${data.backup.count} retained`}
          </span>
        )}
        {data.backup.destination && (
          <span className="secondary mono backup__path">{data.backup.destination}</span>
        )}
        <Link className="tasks__link" to="/settings">
          Settings
        </Link>
      </section>
    </div>
  )
}
