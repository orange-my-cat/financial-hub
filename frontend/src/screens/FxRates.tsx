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
  useDefaultCurrency,
  useDeleteRate,
  useLoadRates,
  useRateStatus,
  useRateTrend,
  type CurrencyDefinition,
  type RateLoadResult,
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
 * Never a future date. A rate is something that happened, and a day that has
 * not arrived has no rate to record — so the month currently running offers
 * today rather than its month-end.
 */
function notAfterToday(iso: string): string {
  const today = todayIso()
  return iso > today ? today : iso
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
  const [rateDate, setRateDate] = useState(() => notAfterToday(monthEnd(todayIso())))
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
      <h2 className="panel__heading">Enter Rates for a Date</h2>
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
            // The picker stops at today, and the form refuses to submit past
            // it. Typed dates are caught by the same constraint.
            max={todayIso()}
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

/**
 * What the last load did, in one sentence.
 *
 * Counts rather than rates: the daily table below is where the figures are, and
 * repeating them here would be a second place for them to be read from. The
 * kept-by-hand count is the exception and is always stated, because it is the
 * only place a person sees BRD §4.3 decline to overwrite something they typed.
 */
function LoadSummary({ result }: { readonly result: RateLoadResult }) {
  const pairs = result.pairs
    .filter((pair) => pair.fetched > 0)
    .map((pair) => `${pair.pair} ${pair.written}`)
    .join(' · ')

  return (
    <p className="fx__note">
      <strong>{result.written}</strong> daily closes stored from {result.provider},{' '}
      {formatDate(result.start)} to {formatDate(result.end)}
      {pairs && <> — {pairs}</>}.
      {result.kept_manual > 0 && (
        <> {result.kept_manual} left as typed by hand and not overwritten.</>
      )}
    </p>
  )
}

function LoadFromProvider() {
  const load = useLoadRates()

  return (
    <div className="fx__load">
      <ErrorBanner error={load.error} />
      <button
        type="button"
        className="btn btn--primary"
        onClick={() => load.mutate()}
        // The request is a few seconds of real work. Disabling is what stops a
        // second press queueing a second full year behind the first.
        disabled={load.isPending}
      >
        {load.isPending ? 'Loading…' : 'Load Rates From Provider'}
      </button>
      {load.isPending ? (
        <p className="fx__note">
          Fetching the last 365 days. This takes a few seconds.
        </p>
      ) : load.data ? (
        <LoadSummary result={load.data.data} />
      ) : (
        <p className="fx__note">
          Every trading day's closing rate for the last 365 days. Rates you typed
          are never overwritten, and running it again is safe.
        </p>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------

function StatusSummary({ asOf }: { readonly asOf: string }) {
  const status = useRateStatus(asOf)

  if (!status.data) return null

  return (
    <section className="panel">
      <h2 className="panel__heading">Missing and Stale</h2>
      {/* The date is stated because it is not always the end of the range —
          the month still running is judged as at today. A state with no date
          attached is a state the reader has to guess the basis of. */}
      <p className="fx__note">
        State as at {formatDate(status.data.as_of)}. A rate more than{' '}
        {status.data.staleness_days} days old on the date it is used is flagged. Carrying
        forward keeps reports working; it never silently hides its age.
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
                <span className="state-cell">
                  <StateGlyph state={statusGlyph(row)} />
                  {row.state}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {/* Beneath the table it answers: the states above are the reason to press
          it, and pressing it is what clears them. */}
      <LoadFromProvider />
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
        <h2 className="panel__heading">Daily Rates</h2>
        <p className="fx__note">No rates recorded in this range.</p>
      </section>
    )
  }

  return (
    <section className="panel">
      <h2 className="panel__heading">Daily Rates</h2>
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
  // The trend opens quoted in the default currency — the side of the pair a
  // reader is measuring against. The other side is the first currency the
  // registry knows that is not it: a pair of a currency against itself is not
  // a rate, and the default is not always USD.
  const defaultCurrency = useDefaultCurrency()
  const [to, setTo] = useState<string>(defaultCurrency)
  const [from, setFrom] = useState<string>(
    () => currencies.find((currency) => currency.code !== defaultCurrency)?.code ?? 'AUD',
  )
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
        {/* Obeys the range like everything else here, but never past today.
            Judging a rate's state at a month-end still to come ages it by the
            days remaining: a rate entered this morning would be reported as a
            fortnight old and flagged stale on time that has not passed. The
            date range's other two consumers below are ranges of dates that
            have rates, and no rate can be recorded in the future, so only this
            one needs capping. */}
        <StatusSummary asOf={notAfterToday(end)} />
      </div>

      <DailyTable start={start} end={end} />
      <TrendChart currencies={registry.data.currencies} start={start} end={end} />
    </div>
  )
}
