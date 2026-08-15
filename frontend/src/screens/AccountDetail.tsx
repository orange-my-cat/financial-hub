/**
 * Account detail — the screen the driving question is actually asked of.
 *
 *     Is the balance of this account increasing, and what is its trend?
 *     For any single account, in under thirty seconds.
 *
 * Everything is in **the account's own currency**. The reporting-currency
 * control does not apply and says so: translating would fold rate movement into
 * a figure the user wants to read as their own money.
 *
 * And a standing note, because the system cannot answer the obvious follow-up:
 * balances are entered snapshots, so it can show *that* a balance moved but
 * generally not *why*.
 */

import { useMemo } from 'react'
import { Link, useParams } from 'react-router-dom'
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
import { useAccountHistory } from '@/lib/accounts'
import { formatDecimal } from '@/lib/format'

function direction(history: readonly { amount: string }[]): string {
  if (history.length < 2) return 'Not enough history to state a direction yet.'

  const window = history.slice(0, 12)
  let rises = 0
  for (let index = 0; index < window.length - 1; index += 1) {
    if (Number(window[index]!.amount) > Number(window[index + 1]!.amount)) rises += 1
  }
  const compared = window.length - 1
  const trend = rises * 2 >= compared ? 'Increasing' : 'Decreasing'
  return `${trend}. Up in ${rises} of the last ${compared} month${compared === 1 ? '' : 's'}.`
}

export function AccountDetail() {
  const { accountId } = useParams()
  const query = useAccountHistory(Number(accountId))

  const chart = useMemo(
    () =>
      [...(query.data?.history ?? [])]
        .reverse()
        .slice(-12)
        .map((row) => ({ month: row.month, amount: Number(row.amount) })),
    [query.data],
  )

  if (query.isPending) return <div className="boot">Loading…</div>
  if (!query.data) return <ErrorBanner error={query.error} />

  const { account, history } = query.data
  const latest = history[0]
  const twelveAgo = history[12]

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
        <span className="secondary">Opened {account.opened_month}</span>
        {account.closed_month && (
          <span className="secondary">Closed {account.closed_month}</span>
        )}
      </div>

      <p className="screen__subhead">
        Figures are in {account.currency}, this account’s own currency — the reporting
        currency control does not apply. Balances are entered snapshots: the system can
        show that a balance moved, not why.
      </p>

      {history.length === 0 ? (
        <section className="panel">
          <p className="fx__note">No balances recorded for this account yet.</p>
        </section>
      ) : (
        <div className="detail__body">
          <section className="panel detail__figure">
            <span className="label">Balance · {latest?.month}</span>
            <div className="networth__total mono">
              {formatDecimal(latest?.amount ?? '0')}
              <span className="money__code">{account.currency}</span>
            </div>

            <p className="detail__direction">{direction(history)}</p>

            <dl className="detail__stats">
              <div>
                <dt className="label">Month on month</dt>
                <dd className="mono">
                  {latest?.change ? formatDecimal(latest.change) : '—'}
                </dd>
              </div>
              <div>
                <dt className="label">Twelve months</dt>
                <dd className="mono">
                  {twelveAgo && latest
                    ? formatDecimal(
                        String(Number(latest.amount) - Number(twelveAgo.amount)),
                      )
                    : '—'}
                </dd>
              </div>
              <div>
                <dt className="label">Months recorded</dt>
                <dd className="mono">{history.length}</dd>
              </div>
            </dl>
          </section>

          <section className="panel detail__trend">
            {chart.length > 1 && (
              <ResponsiveContainer width="100%" height={180}>
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
                    dataKey="amount"
                    stroke="#9184d9"
                    strokeWidth={2}
                    dot={{ r: 2 }}
                    isAnimationActive={false}
                  />
                </LineChart>
              </ResponsiveContainer>
            )}

            <table className="table">
              <thead>
                <tr>
                  <th>Month</th>
                  <th className="numeric">Balance</th>
                  <th className="numeric">Change</th>
                </tr>
              </thead>
              <tbody>
                {history.map((row) => (
                  <tr key={row.month}>
                    <td className="mono">{row.month}</td>
                    <td className="numeric">{formatDecimal(row.amount)}</td>
                    <td className="numeric secondary">
                      {row.change ? formatDecimal(row.change) : '—'}
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
