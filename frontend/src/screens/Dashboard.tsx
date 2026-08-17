/**
 * Dashboard — fixed layout, built last, deliberately.
 *
 * RISK-06 notes this is the most expensive screen and the most likely to be
 * rebuilt once real use reveals what is actually looked at. So it does one
 * thing, in one order, and offers nothing to configure: no widgets, no drag and
 * drop, no personalisation.
 *
 * **It reports the last closed month, not the present.** Balances are entered
 * when a month ends, so a dashboard fixed to the month in progress would be empty
 * for all but the last day of it. Which month that is is decided server-side by
 * one service (`core.services.reporting_month`) and named in the subhead — the
 * screen states its period rather than letting a month-old total pass for today's.
 * The outstanding tasks panel is the exception, and stays anchored to now.
 *
 * Panel order is fixed:
 *
 *   1. **Outstanding tasks** — the only bordered panel on the screen, because
 *      it is the product's conscience. Everything else reports; this asks, so
 *      it asks before anything else has a chance to reassure.
 *   2. Net worth and its 24-month trend
 *   3. Cash flow for the month in the reporting currency — income, expenses,
 *      net and savings rate
 *   4. Holdings — cost basis, estimated value and estimated gain, with the two
 *      plotted over the same months
 *   5. Backup status
 *
 * The holdings panel is a **deliberate departure** from the BRD and the HLD, made
 * at the Product Owner's instruction. This system has no market prices, so it has
 * no unrealised gain; the panel estimates one anyway from the last price each
 * holding was transacted at, and combines across currencies, which BR-18 forbids.
 * Both departures are made in the open: every figure says `estimated`, the oldest
 * price the estimate rests on is printed under it, an unpriced or untranslatable
 * holding is named rather than valued at zero, and the Investments screen's own
 * prohibitions are untouched.
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
  DASH,
  GRID,
  MIN_TICK_GAP,
  REFERENCE,
  RISE,
  compactTick,
} from '@/lib/charts'
import { useDashboard, type DashboardPayload, type FigureChange } from '@/lib/dashboard'
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

/** Which of the four plots the pointer is over, and on which month. */
interface Hover {
  readonly plot: 'worth' | 'flow' | 'rate' | 'holdings'
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
  readonly cost_basis: string | null
  readonly estimated_value: string | null
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
  holdings = false,
}: {
  readonly active?: boolean
  readonly label?: string | number
  readonly currency: string
  readonly show: boolean
  readonly figures: Readonly<Record<string, MonthFigures>>
  /** Whether anything is held at all. Two rows of zeros are not worth the space. */
  readonly holdings?: boolean
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
        {holdings && (
          <>
            <dt>Cost Basis</dt>
            <dd className="mono">
              {row.cost_basis === null
                ? '—'
                : `${formatDecimal(row.cost_basis)} ${currency}`}
            </dd>
            <dt>Estimated Value</dt>
            <dd className="mono">
              {/* Held, but with no price to value it at — not a value of zero. */}
              {row.estimated_value === null
                ? '—'
                : `${formatDecimal(row.estimated_value)} ${currency}`}
            </dd>
          </>
        )}
      </dl>
    </div>
  )
}

/**
 * Which month the figures are for, in words, above everything else.
 *
 * The dashboard does not report the present, and a screen showing last month's
 * net worth without saying so is a screen that will be misread once — which is
 * once too often for a net worth figure. The month is named, and so is the reason
 * it is that month.
 */
function Period({ reporting }: { readonly reporting: DashboardPayload['reporting_month'] }) {
  const month = formatMonth(reporting.month)
  const current = formatMonth(reporting.current_month)

  if (reporting.basis === 'closed') {
    return (
      <p className="screen__subhead">
        Figures for <strong>{month}</strong> — the last month with balances recorded.
        Balances are stated as at a month’s last day, so {current} appears here once it
        has been closed.
      </p>
    )
  }

  if (reporting.basis === 'current') {
    return (
      <p className="screen__subhead">
        Figures for <strong>{month}</strong> — the month in progress, closed early:
        every balance it requires is recorded.
      </p>
    )
  }

  if (reporting.basis === 'empty') {
    return (
      <p className="screen__subhead">
        Figures for <strong>{month}</strong>. Nothing has been recorded yet — the
        dashboard reports the last closed month as soon as there is one.
      </p>
    )
  }

  // Asked for explicitly in the URL, which is the one case where the month is
  // the caller's choice rather than this screen's rule.
  return (
    <p className="screen__subhead">
      Figures for <strong>{month}</strong>, as named in this link.
    </p>
  )
}

export function Dashboard() {
  const { currency } = useViewState()
  const dashboard = useDashboard(currency)
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
    Holdings: what was paid against what it is estimated to be worth, per month.
    A month with nothing held plots zero for both — that is what owning nothing
    looks like — but an *unpriced* month breaks the value line instead, because
    "no price on record" is not "worth nothing".
  */
  const held = data.investments
  const holdingsChart = data.investments_trend.map((point) => ({
    month: point.month,
    cost: Number(point.cost_basis),
    value: point.estimated_value === null ? null : Number(point.estimated_value),
  }))
  const hasHoldings = holdingsChart.some((point) => point.cost !== 0 || point.value)

  /*
    The two trends, merged by month for the shared tooltip. Keyed by month
    rather than zipped by index: the server sends one window to both, and a
    lookup that would produce nothing if that ever stopped being true is
    better than one that would quietly pair the wrong figures.
  */
  const flowByMonth = new Map(data.cashflow_trend.map((row) => [row.month, row]))
  const heldByMonth = new Map(data.investments_trend.map((row) => [row.month, row]))
  const figures: Record<string, MonthFigures> = {}
  for (const worth of data.trend) {
    const cash = flowByMonth.get(worth.month)
    if (!cash) continue
    const holding = heldByMonth.get(worth.month)
    figures[worth.month] = {
      worth: worth.total,
      completeness: worth.completeness,
      income: cash.income,
      expense: cash.expense,
      net: cash.net,
      savings_rate: cash.savings_rate,
      cost_basis: holding?.cost_basis ?? null,
      estimated_value: holding?.estimated_value ?? null,
    }
  }

  return (
    <div className="dash">
      {/* The period every figure below is for. First, because it qualifies all
          of them. */}
      <Period reporting={data.reporting_month} />

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
              No balances recorded for {formatMonth(data.month)} yet.
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
                      holdings={hasHoldings}
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
                            holdings={hasHoldings}
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
                            holdings={hasHoldings}
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

      {/*
        4 — Holdings. What is held now: what it cost, what it is worth on the last
        price it traded at, and the difference.

        Laid out like the two panels above and on the same grid, so the fourth plot
        sits on the same x axis as the other three.
      */}
      <section className="panel dash__networth">
        {held.holdings === 0 ? (
          <>
            <div className="dash__figure">
              {/* Nothing held and everything excluded are different facts, and
                  a panel that reported the second as the first would be hiding
                  holdings behind a missing rate (FR-46). */}
              {held.exclusions.length > 0 ? (
                <p className="exclusion-notice">
                  Every holding is excluded —{' '}
                  {held.exclusions.map((row) => row.reason).join('; ')}. Nothing is
                  counted as zero.
                </p>
              ) : (
                <p className="fx__note">Nothing currently held.</p>
              )}
            </div>
            <div />
          </>
        ) : (
          <>
            <div className="dash__figure">
              <div className="holdings">
                <div className="holdings__figure">
                  <span className="label">Cost basis</span>
                  <div className="holdings__value mono">
                    <Amount
                      value={held.cost_basis.amount}
                      currency={held.cost_basis.currency}
                    />
                  </div>
                  <div className="holdings__note secondary">
                    {held.holdings} holding{held.holdings === 1 ? '' : 's'} held
                  </div>
                </div>

                <div className="holdings__figure">
                  <span className="label">Estimated value</span>
                  <div className="holdings__value mono">
                    {held.estimated_value ? (
                      <Amount
                        value={held.estimated_value.amount}
                        currency={held.estimated_value.currency}
                      />
                    ) : (
                      /* No price on record is not a value of nothing. */
                      <span className="secondary">—</span>
                    )}
                  </div>
                  {/* The whole basis of the figure above, in one line. An estimate
                      resting on a price from years ago is not a current value, and
                      this is the only place that can say so. */}
                  {held.priced_from && (
                    <div className="holdings__note secondary">
                      At each holding’s last traded price, oldest{' '}
                      {formatDate(held.priced_from)}
                    </div>
                  )}
                </div>

                <div className="holdings__figure">
                  <span className="label">Estimated gain</span>
                  <div
                    className={`holdings__value mono ${
                      held.estimated_gain?.amount.startsWith('-')
                        ? 'money--breach'
                        : 'money--rise'
                    }`}
                  >
                    {held.estimated_gain ? (
                      <Amount
                        value={held.estimated_gain.amount}
                        currency={held.estimated_gain.currency}
                      />
                    ) : (
                      <span className="secondary">—</span>
                    )}
                  </div>
                  <div className="holdings__note secondary">
                    Estimated, not realised. Nothing here has been sold.
                  </div>
                </div>
              </div>

              {/* Only when a contributing rate is stale — as on the two panels
                  above, and the same disclosure. */}
              {held.any_stale && held.as_at && (
                <details className="asat">
                  <summary className="asat__summary">
                    Rates as at {formatDate(held.as_at)}
                  </summary>
                  <table className="table asat__detail">
                    <tbody>
                      {held.rate_provenance.map((row) => (
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

              {/* Held, but with no price ever recorded. Named rather than valued
                  at zero, which would show the whole of its cost as a loss. */}
              {held.unpriced.length > 0 && (
                <p className="exclusion-notice">
                  The estimate omits {held.unpriced.join(', ')} — no price on record.
                  Measured against {held.priced_cost_basis
                    ? formatDecimal(held.priced_cost_basis.amount)
                    : '0.00'}{' '}
                  of the cost basis above.
                </p>
              )}

              {/* A holding whose currency has no rate leaves all three figures
                  rather than being counted as zero (FR-46). */}
              {held.exclusions.length > 0 && (
                <p className="exclusion-notice">
                  Excludes {held.exclusions.map((row) => row.holding).join(', ')} —{' '}
                  {held.exclusions.map((row) => row.reason).join('; ')}
                </p>
              )}
            </div>

            <div className="dash__chart">
              {hasHoldings && (
                <>
                  {/* Two series on one scale, which is legitimate here and is not
                      on the cash flow panel: both are money, in one currency, and
                      the distance between them *is* the figure being read. */}
                  <div className="chartkey secondary">
                    <span className="chartkey__item">
                      <svg width="22" height="8" aria-hidden="true">
                        <line
                          x1="0"
                          y1="4"
                          x2="22"
                          y2="4"
                          stroke={REFERENCE}
                          strokeWidth="2"
                          strokeDasharray={DASH}
                        />
                      </svg>
                      Cost basis
                    </span>
                    <span className="chartkey__item">
                      <svg width="22" height="8" aria-hidden="true">
                        <line x1="0" y1="4" x2="22" y2="4" stroke={ACCENT} strokeWidth="2" />
                      </svg>
                      Estimated value
                    </span>
                  </div>

                  <ResponsiveContainer width="100%" height={CHART_HEIGHT}>
                    <LineChart
                      data={holdingsChart}
                      margin={CHART_MARGIN}
                      onMouseMove={track('holdings')}
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
                            show={hover?.plot === 'holdings'}
                            figures={figures}
                            holdings={hasHoldings}
                          />
                        }
                      />
                      {/* Dashed and beneath: what was paid is the baseline the
                          solid line is read against. */}
                      <Line
                        type="linear"
                        dataKey="cost"
                        stroke={REFERENCE}
                        strokeWidth={2}
                        strokeDasharray={DASH}
                        dot={false}
                        connectNulls={false}
                        isAnimationActive={false}
                      />
                      <Line
                        type="linear"
                        dataKey="value"
                        stroke={ACCENT}
                        strokeWidth={2}
                        dot={false}
                        connectNulls={false}
                        isAnimationActive={false}
                      />
                    </LineChart>
                  </ResponsiveContainer>
                </>
              )}
            </div>
          </>
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
