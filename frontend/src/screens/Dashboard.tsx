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
 *   1. Net worth and its 24-month trend
 *   2. **Outstanding tasks** — the only bordered panel on the screen, because
 *      it is the product's conscience. Everything else reports; this asks.
 *   3. Cash flow by currency, with a note that it touches no balance
 *   4. Investments by currency, never combined
 *   5. Backup status
 *
 * Two things appear only when they need to. When every contributing rate is
 * fresh there is no as-at strip and no disclosure control; when nothing is
 * outstanding the tasks panel says so in one line. Silence is the signal.
 */

import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { Link } from 'react-router-dom'

import { ErrorBanner } from '@/components/Advisories'
import { StateGlyph } from '@/components/Provenance'
import { useDashboard } from '@/lib/dashboard'
import { formatDate, formatDecimal } from '@/lib/format'
import { useViewState } from '@/lib/viewState'

function Amount({ value, currency }: { readonly value: string; readonly currency: string }) {
  return (
    <span className={`money ${value.startsWith('-') ? 'money--breach' : ''}`.trim()}>
      {formatDecimal(value)}
      <span className="money__code">{currency}</span>
    </span>
  )
}

export function Dashboard() {
  const { currency, to } = useViewState()
  const dashboard = useDashboard(to, currency)

  if (dashboard.isPending) return <div className="boot">Loading…</div>
  if (!dashboard.data) return <ErrorBanner error={dashboard.error} />

  const data = dashboard.data
  const chart = data.trend.map((point) => ({
    month: point.month,
    total: point.total ? Number(point.total) : null,
  }))
  const hasHistory = chart.some((point) => point.total !== null)

  return (
    <div className="dash">
      <p className="screen__subhead">
        Obeys the reporting currency. Fixed to {data.month} — the date range does not
        apply here.
      </p>

      {/* 1 — Net worth */}
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
                  {data.net_worth.change.startsWith('-') ? '' : '+'}
                  {formatDecimal(data.net_worth.change)}{' '}
                  {data.net_worth.change_percent && (
                    <span className="secondary">
                      ({data.net_worth.change_percent}%)
                    </span>
                  )}{' '}
                  <span className="secondary">on {data.net_worth.previous_month}</span>
                </div>
              )}
            </>
          ) : (
            <div className="networth__none">
              No balances recorded for {data.month} yet.
            </div>
          )}

          <div className="networth__state">
            <StateGlyph state={data.completeness.state} />
            {data.completeness.state}
            <span className="secondary">
              {data.completeness.balances.recorded} of{' '}
              {data.completeness.balances.expected} balances
            </span>
          </div>

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
            <ResponsiveContainer width="100%" height={180}>
              <LineChart data={chart} margin={{ top: 8, right: 8, bottom: 8, left: 8 }}>
                <CartesianGrid stroke="rgba(233,233,237,.06)" vertical={false} />
                <XAxis
                  dataKey="month"
                  tick={{ fill: 'rgba(233,233,237,.45)', fontSize: 11 }}
                  tickLine={false}
                  axisLine={{ stroke: 'rgba(233,233,237,.10)' }}
                  interval="preserveStartEnd"
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
                  dot={false}
                  connectNulls={false}
                  isAnimationActive={false}
                />
              </LineChart>
            </ResponsiveContainer>
          )}
        </div>
      </section>

      {/* 2 — Outstanding tasks. The only bordered panel on this screen. */}
      <section className="tasks">
        <h2 className="panel__heading">Outstanding</h2>
        {data.tasks.length === 0 ? (
          <p className="fx__note">Nothing outstanding.</p>
        ) : (
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
        )}
      </section>

      {/* 3 — Cash flow. Never added to a balance. */}
      <section className="panel">
        <h2 className="panel__heading">Cash flow · {data.month}</h2>
        <p className="fx__note">
          These figures do not affect any account balance, and are never added to one.
        </p>
        {data.cashflow.length === 0 ? (
          <p className="fx__note">Nothing recorded.</p>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>Currency</th>
                <th className="numeric">Income</th>
                <th className="numeric">Expense</th>
                <th className="numeric">Net</th>
              </tr>
            </thead>
            <tbody>
              {data.cashflow.map((block) => (
                <tr key={block.currency}>
                  <td className="mono">{block.currency}</td>
                  <td className="numeric">{formatDecimal(block.income)}</td>
                  <td className="numeric">{formatDecimal(block.expense)}</td>
                  <td className="numeric">
                    <span className={block.net.startsWith('-') ? 'money--breach' : 'money--rise'}>
                      {formatDecimal(block.net)}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
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
