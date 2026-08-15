/**
 * FX rates — the first screen built, because net worth cannot be tested without
 * translation (HLD §11.7).
 *
 * Four parts, in the order the handoff fixes them: bulk entry for a single
 * date, the missing-and-stale summary, the daily table with provenance per
 * rate, and the trend chart.
 *
 * The entry fields show the **inverse live as you type**, because the two pairs
 * are quoted in opposite directions and a wrong-way entry misvalues every
 * balance in that currency for the month. Nothing else in the system would
 * catch it.
 */

import { useMemo, useState, type FormEvent } from 'react'
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import { AdvisoryList, ErrorBanner } from '@/components/Advisories'
import { Rate, StateGlyph, type GlyphState } from '@/components/Provenance'
import { ApiError, type Advisory } from '@/lib/api'
import { formatDate } from '@/lib/format'
import {
  useBulkRateEntry,
  useCurrencies,
  useDailyRates,
  useDeleteRate,
  useRateStatus,
  useRateTrend,
  type CurrencyDefinition,
} from '@/lib/fx'
import { useViewState } from '@/lib/viewState'

/** The last calendar day of the month a date falls in — the reporting boundary. */
function monthEnd(iso: string): string {
  const [year, month] = iso.split('-').map(Number)
  return new Date(Date.UTC(year ?? 1970, month ?? 1, 0)).toISOString().slice(0, 10)
}

function todayIso(): string {
  return new Date().toISOString().slice(0, 10)
}

/**
 * The reciprocal, as a typing aid only.
 *
 * Float arithmetic, deliberately and safely: this figure is never stored, never
 * sent, and never totalled. It exists so that typing 4.20 where 0.66 belongs is
 * obvious at the moment of typing rather than at the next month close. Every
 * figure the application reports comes from the server.
 */
function inverseHint(raw: string): string | null {
  const value = Number(raw)
  if (!raw.trim() || !Number.isFinite(value) || value <= 0) return null
  return (1 / value).toFixed(4)
}

function statusGlyph(row: { missing: boolean; stale: boolean }): GlyphState {
  if (row.missing) return 'Missing'
  if (row.stale) return 'Incomplete'
  return 'Complete'
}

// ---------------------------------------------------------------------------

function BulkEntry({ currencies }: { readonly currencies: readonly CurrencyDefinition[] }) {
  const [rateDate, setRateDate] = useState(() => monthEnd(todayIso()))
  const [values, setValues] = useState<Record<string, string>>({})
  const [advisories, setAdvisories] = useState<readonly Advisory[]>([])
  const entry = useBulkRateEntry()

  const quoted = currencies.filter((currency) => !currency.is_base)
  const fieldError = (code: string) =>
    entry.error instanceof ApiError ? entry.error.fieldError(`rates.${code}`) : undefined

  function submit(event: FormEvent) {
    event.preventDefault()
    const rates = Object.fromEntries(
      Object.entries(values).filter(([, value]) => value.trim() !== ''),
    )
    if (Object.keys(rates).length === 0) return

    entry.mutate(
      { rate_date: rateDate, rates },
      {
        onSuccess: (response) => {
          setAdvisories(response.advisories)
          setValues({})
        },
      },
    )
  }

  return (
    <section className="panel fx__entry">
      <h2 className="panel__heading">Enter rates for a date</h2>
      <p className="fx__note">
        Only month-end rates are required. Any other date is optional and exists to enrich
        the trend chart.
      </p>

      <ErrorBanner error={entry.error} />

      <form onSubmit={submit} className="fx__form">
        <div className="field">
          <label className="field__label" htmlFor="rate-date">
            As at
          </label>
          <input
            id="rate-date"
            type="date"
            className="input"
            value={rateDate}
            onChange={(event) => setRateDate(event.target.value)}
            required
          />
        </div>

        {quoted.map((currency) => {
          const raw = values[currency.code] ?? ''
          const hint = inverseHint(raw)
          const error = fieldError(currency.code)

          return (
            <div className="field" key={currency.code}>
              <label className="field__label" htmlFor={`rate-${currency.code}`}>
                {currency.pair} <span className="fx__convention">{currency.quote_label}</span>
              </label>
              <input
                id={`rate-${currency.code}`}
                className={`input mono${error ? ' input--error' : ''}`}
                inputMode="decimal"
                placeholder={currency.example}
                value={raw}
                onChange={(event) =>
                  setValues((current) => ({ ...current, [currency.code]: event.target.value }))
                }
              />
              {/* The wrong-way check, at the moment of typing. */}
              {hint && (
                <span className="fx__inverse mono">
                  = {hint}{' '}
                  {currency.convention === 'usd_per_unit'
                    ? `${currency.code} per 1 USD`
                    : `USD per 1 ${currency.code}`}
                </span>
              )}
              {error && <span className="field__error">{error}</span>}
            </div>
          )
        })}

        <button type="submit" className="btn btn--primary" disabled={entry.isPending}>
          {entry.isPending ? 'Saving…' : 'Save all'}
        </button>
      </form>

      {/* Saved either way. That is what makes it an advisory. */}
      <AdvisoryList advisories={advisories} />
    </section>
  )
}

// ---------------------------------------------------------------------------

function StatusSummary({ asOf }: { readonly asOf: string }) {
  const status = useRateStatus(asOf)

  if (!status.data) return null

  return (
    <section className="panel">
      <h2 className="panel__heading">Missing and stale</h2>
      <p className="fx__note">
        A rate more than {status.data.staleness_days} days old on the date it is used is
        flagged. Carrying forward keeps reports working; it never silently hides its age.
      </p>

      <table className="table">
        <thead>
          <tr>
            <th>Pair</th>
            <th>Quoted as</th>
            <th className="numeric">Latest</th>
            <th>As at</th>
            <th>State</th>
          </tr>
        </thead>
        <tbody>
          {status.data.pairs.map((row) => (
            <tr key={row.currency}>
              <td className="mono">{row.pair}</td>
              <td className="secondary">{row.quote_label}</td>
              <td className="numeric">
                {row.rate ?? <span className="excluded">no rate on record</span>}
              </td>
              <td className="secondary">{row.as_at ? formatDate(row.as_at) : '—'}</td>
              <td>
                <span className="fx__state">
                  <StateGlyph state={statusGlyph(row)} />
                  {row.state}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  )
}

// ---------------------------------------------------------------------------

function DailyTable({ start, end }: { readonly start: string; readonly end: string }) {
  const rates = useDailyRates(start, end)
  const remove = useDeleteRate()

  if (!rates.data) return null

  if (rates.data.length === 0) {
    return (
      <section className="panel">
        <h2 className="panel__heading">Daily rates</h2>
        <p className="fx__note">No rates recorded in this range.</p>
      </section>
    )
  }

  return (
    <section className="panel">
      <h2 className="panel__heading">Daily rates</h2>
      <p className="fx__note">
        Every pair as a translation on that date would resolve it. A pair not entered that
        day is shown carried, with the date it came from — not left blank.
      </p>

      <table className="table">
        <thead>
          <tr>
            <th>Date</th>
            <th>Pair</th>
            <th className="numeric">Rate</th>
            <th>As at</th>
            <th aria-label="Actions" />
          </tr>
        </thead>
        <tbody>
          {rates.data.flatMap((row) =>
            row.entries.map((entry, index) => (
              <tr key={`${row.date}-${entry.currency}`}>
                <td className="mono">{index === 0 ? formatDate(row.date) : ''}</td>
                <td className="mono">{entry.pair}</td>
                <td className="numeric">
                  <Rate
                    value={entry.rate}
                    provenance={entry.provenance}
                    stale={entry.stale}
                  />
                </td>
                <td className="secondary">{formatDate(entry.as_at)}</td>
                <td className="numeric">
                  {entry.recorded && (
                    <button
                      type="button"
                      className="link-button"
                      disabled={remove.isPending}
                      onClick={() =>
                        remove.mutate({ currency: entry.currency, rate_date: row.date })
                      }
                    >
                      Delete
                    </button>
                  )}
                </td>
              </tr>
            )),
          )}
        </tbody>
      </table>
    </section>
  )
}

// ---------------------------------------------------------------------------

function TrendChart({
  currencies,
  start,
  end,
}: {
  readonly currencies: readonly CurrencyDefinition[]
  readonly start: string
  readonly end: string
}) {
  const [from, setFrom] = useState('AUD')
  const [to, setTo] = useState('USD')
  const trend = useRateTrend(from, to, start, end)

  const data = useMemo(
    () =>
      (trend.data?.points ?? []).map((point) => ({
        date: point.date,
        rate: Number(point.rate),
        derived: point.derived,
      })),
    [trend.data],
  )

  const first = data[0]
  const last = data[data.length - 1]

  return (
    <section className="panel">
      <h2 className="panel__heading">Trend</h2>

      <div className="fx__trend-controls">
        {(['from', 'to'] as const).map((side) => (
          <label className="fx__trend-select" key={side}>
            <span className="label">{side}</span>
            <select
              className="input"
              value={side === 'from' ? from : to}
              onChange={(event) =>
                side === 'from' ? setFrom(event.target.value) : setTo(event.target.value)
              }
            >
              {currencies.map((currency) => (
                <option key={currency.code} value={currency.code}>
                  {currency.code}
                </option>
              ))}
            </select>
          </label>
        ))}

        {/* A triangulated pair will not exactly match a quoted market rate.
            Immaterial for personal net worth, and surfaced rather than hidden. */}
        {trend.data?.derived && (
          <span className="fx__derived">Derived — triangulated through USD</span>
        )}
      </div>

      {data.length === 0 ? (
        <p className="fx__note">No rates for this pair in the selected range.</p>
      ) : (
        <>
          <div className="fx__trend-legend mono">
            <span>
              {first && `${formatDate(first.date)} · ${first.rate}`}
            </span>
            <span>
              {last && `${formatDate(last.date)} · ${last.rate}`}
            </span>
          </div>
          <div className="fx__chart">
            <ResponsiveContainer width="100%" height={220}>
              <LineChart data={data} margin={{ top: 8, right: 8, bottom: 8, left: 8 }}>
                <CartesianGrid stroke="rgba(233,233,237,.08)" vertical={false} />
                <XAxis
                  dataKey="date"
                  tick={{ fill: 'rgba(233,233,237,.45)', fontSize: 11 }}
                  tickLine={false}
                  axisLine={{ stroke: 'rgba(233,233,237,.10)' }}
                />
                <YAxis
                  domain={['auto', 'auto']}
                  tick={{ fill: 'rgba(233,233,237,.45)', fontSize: 11 }}
                  tickLine={false}
                  axisLine={false}
                  width={72}
                />
                <Tooltip
                  contentStyle={{
                    background: '#232532',
                    border: '1px solid rgba(233,233,237,.16)',
                    borderRadius: 8,
                    fontSize: 12,
                  }}
                  labelStyle={{ color: 'rgba(233,233,237,.55)' }}
                />
                <Line
                  type="linear"
                  dataKey="rate"
                  stroke="#9184d9"
                  strokeWidth={2}
                  dot={{ r: 2, fill: '#9184d9' }}
                  isAnimationActive={false}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </>
      )}
    </section>
  )
}

// ---------------------------------------------------------------------------

export function FxRates() {
  const registry = useCurrencies()
  const { from, to } = useViewState()

  // The date range applies to this screen; the reporting currency does not.
  const start = `${from}-01`
  const end = monthEnd(`${to}-01`)

  if (registry.isPending) return <div className="boot">Loading…</div>
  if (!registry.data) return <ErrorBanner error={registry.error} />

  return (
    <div className="fx">
      <p className="screen__subhead">
        Obeys the date range. The reporting currency does not apply — rates are shown in
        each pair’s own market convention.
      </p>

      <div className="fx__grid">
        <BulkEntry currencies={registry.data.currencies} />
        <StatusSummary asOf={end} />
      </div>

      <DailyTable start={start} end={end} />
      <TrendChart currencies={registry.data.currencies} start={start} end={end} />
    </div>
  )
}
