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
} from 'recharts'

import { ErrorBanner } from '@/components/Advisories'
import { StateGlyph } from '@/components/Provenance'
import {
  useNetWorth,
  useNetWorthSlice,
  useNetWorthTrend,
  type CompletenessState,
} from '@/lib/accounts'
import { formatDate, formatDecimal } from '@/lib/format'
import { useViewState } from '@/lib/viewState'

const DIMENSIONS = [
  { key: 'type', label: 'Account type' },
  { key: 'liquidity', label: 'Liquidity tier' },
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

export function NetWorth() {
  const { currency, from, to } = useViewState()
  const [dimension, setDimension] = useState<string>('type')

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

  if (netWorth.isPending) return <div className="boot">Loading…</div>
  if (!netWorth.data) return <ErrorBanner error={netWorth.error} />

  const { data, completeness, exclusions, rate_provenance: provenance } = netWorth.data
  const points = trend.data?.points ?? []
  const latest = points[points.length - 1]
  const previous = points[points.length - 2]

  return (
    <div className="networth">
      <p className="screen__subhead">
        Obeys both the reporting currency and the date range. Both are in the URL.
      </p>

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

          {data.total && latest?.change && (
            <div className="networth__change mono">
              {latest.change.startsWith('-') ? '' : '+'}
              {formatDecimal(latest.change)} {data.total.currency} on {previous?.month}
            </div>
          )}

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

        <div className="networth__chart">
          {chart.length > 0 && (
            <ResponsiveContainer width="100%" height={200}>
              <LineChart data={chart} margin={{ top: 8, right: 8, bottom: 8, left: 8 }}>
                <CartesianGrid stroke="rgba(233,233,237,.06)" vertical={false} />
                <XAxis
                  dataKey="month"
                  tick={{ fill: 'rgba(233,233,237,.45)', fontSize: 11 }}
                  tickLine={false}
                  axisLine={{ stroke: 'rgba(233,233,237,.10)' }}
                />
                <YAxis
                  tick={{ fill: 'rgba(233,233,237,.45)', fontSize: 11 }}
                  tickLine={false}
                  axisLine={false}
                  width={80}
                />
                <Tooltip
                  contentStyle={{
                    background: '#232532',
                    border: '1px solid rgba(233,233,237,.16)',
                    borderRadius: 8,
                    fontSize: 12,
                  }}
                />
                <Line
                  type="linear"
                  dataKey="total"
                  stroke="#9184d9"
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
                  </tr>
                ))}
                <tr className="table__total">
                  <td>Net worth</td>
                  <td />
                  <td className="numeric">
                    <Amount value={slice.data.data.total.amount} currency={currency} />
                  </td>
                </tr>
              </tbody>
            </table>
          )}
        </section>

        <section className="panel">
          <h2 className="panel__heading">Month on month</h2>
          <table className="table">
            <thead>
              <tr>
                <th>Month</th>
                <th className="numeric">Net worth</th>
                <th className="numeric">Change</th>
                <th />
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
                  <td className="numeric secondary">
                    {point.change ? formatDecimal(point.change) : '—'}
                  </td>
                  <td>
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
