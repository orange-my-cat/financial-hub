/**
 * FX rates — the first screen built, because net worth cannot be tested without
 * translation (HLD §11.7).
 *
 * The screen is about **one pair at a time**. The pair is chosen at the top left,
 * the chart to its right plots it, and the table at the bottom lists every date
 * it was observed. Under the pair controls sit the states that are the reason to
 * press the provider button — what each currency last read, and how old it is.
 *
 * It is now a **reading** screen. Bulk entry, the subhead, the sentence stating
 * which way round a pair reads, and the note on what the provider button does
 * were all removed at the Product Owner's instruction — see the comments where
 * each stood. Nothing here writes a rate except the provider button, and nothing
 * here states a pair's direction: the two selects and the arrow between them are
 * all that is left of it.
 *
 * That matters more here than the removals elsewhere, because the direction is
 * the single easiest thing in this system to get backwards — AUD is quoted USD
 * per 1 AUD and MYR is quoted MYR per 1 USD, and a figure read the wrong way
 * misvalues every balance in that currency. The live inverse beside each entry
 * field was what caught it at the moment of typing; there is no entry field on
 * this screen to catch it on now.
 *
 * One of the rules they described has since changed rather than merely gone
 * unsaid: the provider button now **replaces** the year it loads, hand-typed
 * rates included, so nothing on this screen warns before it is pressed. The
 * summary it returns says how many stored rates it cleared.
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
import { Rate, StateGlyph, type GlyphState } from '@/components/Provenance'
import {
  ACCENT,
  AXIS_LINE,
  AXIS_TICK,
  AXIS_WIDTH,
  CHART_HEIGHT,
  CHART_MARGIN,
  compactTick,
  CURSOR,
  FIT_DOMAIN,
  GRID,
  MIN_TICK_GAP,
} from '@/lib/charts'
import {
  formatDate,
  formatDayShort,
  monthEnd,
  monthOf,
  movementClass,
} from '@/lib/format'
import {
  useCurrencies,
  useDefaultCurrency,
  useDeleteRate,
  useLoadRates,
  useRateStatus,
  useRateTrend,
  type CurrencyDefinition,
  type CurrencyRegistry,
  type RateLoadResult,
  type RateTrend,
  type TrendPoint,
} from '@/lib/fx'
import { monthSpan, shiftMonths, useViewState } from '@/lib/viewState'
import { icons } from '@/shell/icons'

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
 * The spans the range control offers, in months.
 *
 * Ending at the current month in every case, because a rate range is read
 * backwards from now — "the last two years", never an arbitrary window. A
 * bookmarked URL can still name any `from` and `to` it likes; the presets are
 * shortcuts, not the only reachable ranges, and none of them lights up when the
 * URL names something else.
 *
 * Five, and no wider than five years: the provider button fills one year, and
 * anything beyond that is history typed by hand or seeded.
 */
const RANGE_PRESETS = [
  { label: '1m', months: 1 },
  { label: '6m', months: 6 },
  { label: '1y', months: 12 },
  { label: '2y', months: 24 },
  { label: '5y', months: 60 },
] as const

/**
 * How long ago a rate was observed.
 *
 * Every row states its age, one day included: a reader checking whether the
 * rates are current wants an answer on every line, and a blank leaves them to
 * decide whether it means "fresh" or "not loaded yet". Only a pair with no rate
 * at all has nothing to say here, and it says that in words instead.
 *
 * Days, not the date. The date answers "which close is this"; the plot and the
 * table below both answer that already. What this list is for is whether the
 * figure is still current, and that is a distance rather than a day.
 */
function agedLabel(days: number | null): string | null {
  if (days === null) return null
  // The day itself is not a distance, and "0 days ago" is nobody's way of
  // saying it.
  if (days === 0) return 'today'
  return `${days} day${days === 1 ? '' : 's'} ago`
}

function statusGlyph(row: { missing: boolean; stale: boolean }): GlyphState {
  if (row.missing) return 'Missing'
  if (row.stale) return 'Incomplete'
  return 'Complete'
}

/**
 * What the last load did, in one sentence.
 *
 * Counts rather than rates: the daily table is where the figures are, and
 * repeating them here would be a second place for them to be read from. The
 * cleared count is the exception and is always stated, because the load replaces
 * its window rather than topping it up, and this is the only place a person sees
 * how many stored rates it removed to do that — including any they had typed.
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
      {result.removed > 0 && (
        <>
          {' '}
          {result.removed} rate{result.removed === 1 ? '' : 's'} already on record for
          those dates {result.removed === 1 ? 'was' : 'were'} cleared first, and
          {result.removed === 1 ? ' is' : ' are'} recoverable in the admin.
        </>
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
      {/* The resting note that stood here — every trading day's closing rate for
          the last 365 days, typed rates never overwritten, safe to run again —
          was removed at the Product Owner's instruction, and one of those three
          facts has since stopped being true. The window is still fixed in the
          service and the load is still safe to repeat, but it now truncates:
          `load_recent` clears every rate stored in the year before loading the
          provider's series over it, typed rates included (BRD §4.3 departure).
          Nothing says so before the button is pressed. The summary afterwards
          reports what was written and how many stored rates were cleared, and
          the clearing is a soft delete, so they are recoverable in the admin. */}
      {load.isPending && (
        <p className="fx__note">
          Fetching the last 365 days. This takes a few seconds.
        </p>
      )}
      {load.data && <LoadSummary result={load.data.data} />}
    </div>
  )
}

// ---------------------------------------------------------------------------

/**
 * The date range, as spans ending this month.
 *
 * It writes to the view state rather than to a local hook, so the range stays
 * what it is elsewhere in the application: mirrored to the URL, bookmarkable,
 * and honoured by every screen that obeys it. The header stopped displaying the
 * range, so on this screen this is the only control over it — a second, local
 * range would have made the URL disagree with what is plotted.
 */
function RangePicker() {
  const { from, to, setRange } = useViewState()
  const thisMonth = monthOf(todayIso())
  // A preset is "on" only when it is exactly the window being shown. A range
  // ending in an earlier month came from somewhere else and is left unclaimed
  // rather than rounded to the nearest button.
  const span = to === thisMonth ? monthSpan(from, to) : 0

  return (
    // The "Range" legend that stood here was removed at the Product Owner's
    // instruction. The group keeps its accessible name, so what these five
    // buttons are is still stated to anything that is not looking at them.
    <div className="seg fx__range" role="group" aria-label="Date range">
      {RANGE_PRESETS.map((preset) => (
        <button
          key={preset.label}
          type="button"
          className={`seg__option mono${span === preset.months ? ' seg__option--on' : ''}`}
          aria-pressed={span === preset.months}
          onClick={() => setRange(shiftMonths(thisMonth, -(preset.months - 1)), thisMonth)}
        >
          {preset.label}
        </button>
      ))}
    </div>
  )
}

/**
 * The pair picker, the range, the states, and the button that fills them.
 *
 * One pair chosen here drives both the chart beside it and the table below, so
 * the two cannot disagree about which direction is being read. The load button
 * sits with them because it is what turns an empty chart into a full one.
 */
function PairPicker({
  currencies,
  from,
  to,
  onFrom,
  onTo,
  statusAsOf,
}: {
  readonly currencies: readonly CurrencyDefinition[]
  readonly from: string
  readonly to: string
  readonly onFrom: (code: string) => void
  readonly onTo: (code: string) => void
  readonly statusAsOf: string
}) {
  const options = currencies.map((currency) => (
    <option key={currency.code} value={currency.code}>
      {currency.code}
    </option>
  ))

  return (
    <div className="fx__pair">
      {/* The note that stood here stated which way round the pair reads — one
          unit of the first currency, expressed in the second — and that
          reversing the two gives the reciprocal rather than a different rate.
          Removed at the Product Owner's instruction. The direction is unchanged
          and every figure below still depends on it; the two selects are now the
          only thing that says which way it runs. */}

      {/* First, because the range qualifies every figure under it — the plot
          beside it, the states below it and the table at the foot of the
          screen. */}
      <RangePicker />

      {/* The "from" and "to" captions over these two were removed at the
          Product Owner's instruction. The arrow between them is now the only
          thing that says which side is which, and it is decorative — so each
          select carries the caption as its accessible name instead, because a
          currency picker that announces itself as "AUD" and nothing else leaves
          a screen reader with two identical controls. */}
      <div className="fx__trend-controls">
        <div className="fx__trend-select">
          <select
            className="input"
            aria-label="Convert from"
            value={from}
            onChange={(event) => onFrom(event.target.value)}
          >
            {options}
          </select>
        </div>

        <span className="fx__pair-arrow" aria-hidden="true">
          →
        </span>

        <div className="fx__trend-select">
          <select
            className="input"
            aria-label="Convert to"
            value={to}
            onChange={(event) => onTo(event.target.value)}
          >
            {options}
          </select>
        </div>

        {/* Beside the pair rather than between the two selects: the arrow
            between them is the only thing left on this screen that says which
            way the pair is read, and a two-headed glyph in its place would take
            that with it.

            Reversing a pair gives the reciprocal, not a different rate — so this
            is a change of viewpoint and nothing is refetched that was not
            already a legitimate query. The name says what it does, because a
            bare glyph beside two currency codes could otherwise be read as
            moving something between them. */}
        <button
          type="button"
          className="btn btn--icon fx__swap"
          aria-label={`Read the pair the other way round, ${to} to ${from}`}
          onClick={() => {
            onFrom(to)
            onTo(from)
          }}
        >
          {icons.swap}
        </button>
      </div>

      {/* The line that stood here said "Derived — triangulated through USD"
          whenever the chosen pair was not one this system stores. Removed at the
          Product Owner's instruction. The fact is unchanged and still visible
          where it is per-figure rather than per-pair: every triangulated rate in
          the table below carries the `t` provenance mark, and so does the hover
          box on the plot. */}

      {/* Above the button, because these states are the reason to press it and
          pressing it is what clears them. */}
      <RateStatusList asOf={statusAsOf} />

      <LoadFromProvider />
    </div>
  )
}

// ---------------------------------------------------------------------------

/**
 * The hover box, in the same box every other trend on the site uses.
 *
 * The rate is rendered from the server's string, never from the float the chart
 * plots with: the geometry may be approximate, the figure never is. The date
 * comes from `label`, as the month does on the other plots. Provenance is
 * stated whenever it is not `exact`, because a carried figure was observed on an
 * earlier date than the one at the head of the box.
 */
function RateTooltip({
  active,
  label,
  from,
  to,
  points,
}: {
  readonly active?: boolean
  readonly label?: string | number
  readonly from: string
  readonly to: string
  readonly points: Readonly<Record<string, TrendPoint>>
}) {
  const date = active && typeof label === 'string' ? label : undefined
  const point = date ? points[date] : undefined
  if (!date || !point) return null

  return (
    <div className="charttip">
      <div className="charttip__month mono">{formatDate(date)}</div>
      <dl className="charttip__list">
        <dt>
          {to} per 1 {from}
        </dt>
        <dd className="mono">
          <Rate value={point.rate} provenance={point.provenance} />
        </dd>
        {point.provenance !== 'exact' && (
          <>
            <dt>Provenance</dt>
            <dd>{point.provenance}</dd>
          </>
        )}
      </dl>
    </div>
  )
}

/**
 * The chosen pair, over the date range.
 *
 * The dashboard's geometry, from `@/lib/charts`: the same height, gutter, grid,
 * axis ink, line weight and fitted axis, and the same hover box. A reader moving
 * between screens is comparing shapes, and a plot that restates one of those
 * numbers locally makes the same movement look like a different one.
 *
 * Two things differ, and both only because this axis is days where the others
 * are months. The ticks name a day. And the hover mark is a rule at the hovered
 * date rather than the 22px month band, which on a daily axis would cover a
 * fortnight and read as a range — so this plot needs no hover state either:
 * there is one plot here, not three to keep in step.
 *
 * Points sit on the dates a rate was actually recorded, and a gap is left where
 * one leg has nothing on or before that date — a break in the line is the truth,
 * and interpolating over it would invent an observation.
 */
function TrendChart({
  from,
  to,
  trend,
  pending,
}: {
  readonly from: string
  readonly to: string
  readonly trend: RateTrend | undefined
  readonly pending: boolean
}) {
  const data = useMemo(
    () =>
      (trend?.points ?? []).map((point) => ({
        date: point.date,
        rate: Number(point.rate),
      })),
    [trend],
  )

  /** The exact figures, by date — what the hover box states. */
  const points = useMemo(
    () => Object.fromEntries((trend?.points ?? []).map((point) => [point.date, point])),
    [trend],
  )

  return (
    <div className="fx__trend">
      {from === to ? (
        <p className="fx__note">A currency against itself is not a rate. Choose two.</p>
      ) : pending ? (
        <p className="fx__note">Loading…</p>
      ) : data.length === 0 ? (
        <p className="fx__note">No rates for this pair in the selected range.</p>
      ) : data.length === 1 ? (
        // One point is not a trend, as on an account's history. The line is
        // drawn without dots, so a lone observation would plot as an empty
        // panel; the table below has the figure.
        <p className="fx__note">
          One rate on record for this pair in the selected range — not yet a trend.
        </p>
      ) : (
        // The first and last observation stood above the plot as a strip;
        // removed at the Product Owner's instruction. Both figures are still
        // read from the same series — the axis carries the dates, the hover box
        // the rates, and the table below has every one of them.
        <div className="fx__chart">
          <ResponsiveContainer width="100%" height={CHART_HEIGHT}>
            <LineChart data={data} margin={CHART_MARGIN}>
              <CartesianGrid stroke={GRID} vertical={false} />
              <XAxis
                dataKey="date"
                scale="band"
                tick={AXIS_TICK}
                tickLine={false}
                axisLine={AXIS_LINE}
                tickFormatter={formatDayShort}
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
              <Tooltip
                cursor={CURSOR}
                content={<RateTooltip from={from} to={to} points={points} />}
              />
              <Line
                type="linear"
                dataKey="rate"
                stroke={ACCENT}
                strokeWidth={2}
                dot={false}
                // A gap stays a gap, as on the dashboard.
                connectNulls={false}
                isAnimationActive={false}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------

/**
 * Missing and stale, and the last rate each pair actually has.
 *
 * Every currency the registry knows except the base: USD against itself is
 * always 1 and is never recorded (BR-09), so it has no rate to be stale. Gold is
 * here like any other — a balance may be denominated in it even though net worth
 * is never stated in ounces, so a missing XAU rate excludes an account exactly
 * as a missing AUD rate would.
 *
 * A list rather than the five-column table it replaces: it now sits in the trend
 * panel's left column, and a table that scrolls sideways in 380px is a table
 * nobody reads. Each row is a currency code and the age of its last rate, on
 * every row. The figure itself is not here: this list answers whether a rate is
 * still current, and the rates themselves are the subject of the plot beside it
 * and the table below.
 *
 * The age is measured from the rate's own date, not from the moment it was
 * written: a rate is a fact about a day, and the day is what decides whether
 * reports are carrying it forward.
 *
 * The note that stood over the old table stated the as-at basis and the
 * staleness threshold in words. Removed with the screen's other explanatory
 * copy; the glyph and the age still carry the state, and the threshold behind it
 * is the one on Settings.
 */
function RateStatusList({ asOf }: { readonly asOf: string }) {
  const status = useRateStatus(asOf)

  if (!status.data) return null

  return (
    <div className="fx__status">
      <span className="label">Last rate</span>

      <ul className="fx__status-list">
        {status.data.pairs.map((row) => (
          <li className="fx__status-row" key={row.currency}>
            {/* The code, not the pair label: `AUD`, not `AUD/USD`. Nothing is
                quoted in this row any more, so the direction it would have
                stated has nothing here to qualify — the figures are in the table
                below, each in its own market convention. */}
            <span className="mono">{row.currency}</span>

            {row.missing ? (
              // Never a zero and never a blank: the account this pair values is
              // excluded from a translated total, and the words say so (FR-46).
              <span className="fx__status-none excluded">
                <StateGlyph state={statusGlyph(row)} />
                no rate on record
              </span>
            ) : (
              // The age, and not the figure. Stated on every row, and
              // unmarked until it is stale: the glyph is what carries "stale"
              // without relying on the colour.
              agedLabel(row.age_days) && (
                <span className={`fx__status-date ${row.stale ? 'carry' : 'secondary'}`}>
                  {row.stale && <StateGlyph state={statusGlyph(row)} />}
                  {agedLabel(row.age_days)}
                </span>
              )
            )}
          </li>
        ))}
      </ul>
    </div>
  )
}

// ---------------------------------------------------------------------------

/**
 * Every date the chosen pair was observed, newest first.
 *
 * The same series the chart plots, read as figures rather than as a line — one
 * fetch feeding both, so the two cannot disagree.
 *
 * The provenance column was removed at the Product Owner's instruction, and
 * replaced by the two movement columns. Provenance still travels with the
 * figure as its mark, `c` for carried; the `t` for triangulated was dropped
 * from this column at the Product Owner's instruction. Nothing is hidden by
 * that — triangulation is a property of the pair and not of the day, so the `t`
 * sat on every row of a derived pair at once, and the hover box on the plot
 * still states provenance in words.
 *
 * Delete is offered only where the row shown *is* a stored row: a directly
 * quoted pair, on a date it was recorded. A triangulated figure is not a row
 * and has nothing to delete, and a carried figure belongs to an earlier date
 * than the one on the line.
 */
function PairTable({
  base,
  from,
  to,
  trend,
  pending,
}: {
  readonly base: string
  readonly from: string
  readonly to: string
  readonly trend: RateTrend | undefined
  readonly pending: boolean
}) {
  const remove = useDeleteRate()

  // The pair as stored, so a delete names the currency the row is filed under.
  // Either side may be the base; the other side is the quoted currency, and
  // only USD-based pairs are stored at all (ADR-09).
  const stored = trend !== undefined && !trend.derived && (from === base || to === base)
  const storedCurrency = from === base ? to : from

  const rows = useMemo(() => [...(trend?.points ?? [])].reverse(), [trend])

  return (
    <section className="panel fx__pair-table">
      <h2 className="panel__heading">Daily Rates</h2>

      {from === to ? (
        <p className="fx__note">A currency against itself is not a rate. Choose two.</p>
      ) : pending ? (
        <p className="fx__note">Loading…</p>
      ) : rows.length === 0 ? (
        <p className="fx__note">No rates recorded for this pair in the selected range.</p>
      ) : (
        <>
          {/* The note that stood here said the table reads newest first, that a
              date appears where a rate on one side of the pair was recorded, and
              that a carried figure is marked rather than presented as that day's
              observation. Removed at the Product Owner's instruction. All three
              still hold: the order is set below, the dates still come from the
              series, and the provenance mark is still on every carried
              figure. */}
          <table className="table">
            <thead>
              <tr>
                <th>Date</th>
                <th className="numeric">
                  {to} per 1 {from}
                </th>
                <th className="numeric">Change</th>
                <th className="numeric">Change %</th>
                <th aria-label="Actions" />
              </tr>
            </thead>
            <tbody>
              {rows.map((point) => (
                <tr key={point.date}>
                  <td className="mono">{formatDate(point.date)}</td>
                  <td className="numeric">
                    {/* Carried is marked, triangulated is not: a carried figure
                        varies row to row, where a triangulated one is the whole
                        pair. Passing `exact` is what suppresses the mark. */}
                    <Rate
                      value={point.rate}
                      provenance={point.provenance === 'carried' ? 'carried' : 'exact'}
                    />
                  </td>
                  {/* Both movements come from the server, signed, and are
                      printed as they arrive. An em dash where there is no
                      predecessor in the range — never a zero, which would claim
                      the rate held.

                      Coloured by direction, from the same `movementClass` the
                      balance screens use, and both cells take the class of the
                      change: the proportion is that movement stated a second
                      way, not a qualifier on it. Zero takes neither colour.

                      What the colour means here is narrower than on a balance.
                      Green is the rate rising — the left-hand currency buying
                      more of the right-hand one — and that is only good news to
                      someone holding the left-hand side. This screen does not
                      know which side that is, so read it as direction and not as
                      a verdict. */}
                  <td className={`numeric mono ${movementClass(point.change)}`.trim()}>
                    {point.change ?? '—'}
                  </td>
                  <td className={`numeric mono ${movementClass(point.change)}`.trim()}>
                    {point.change_percent ? `${point.change_percent}%` : '—'}
                  </td>
                  <td className="numeric">
                    {stored && point.provenance === 'exact' && (
                      <button
                        type="button"
                        className="link-button"
                        disabled={remove.isPending}
                        onClick={() =>
                          remove.mutate({ currency: storedCurrency, rate_date: point.date })
                        }
                      >
                        Delete
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </section>
  )
}

// ---------------------------------------------------------------------------

/**
 * The screen, once the registry has arrived.
 *
 * Split out so the chosen pair can be initialised from the served currencies
 * rather than guessed before they load.
 */
function FxBoard({ registry }: { readonly registry: CurrencyRegistry }) {
  // The month range from the header. Named apart from the pair's two sides,
  // which are also a from and a to and mean something entirely different.
  const { from: rangeStart, to: rangeEnd } = useViewState()

  // The date range applies to this screen; the reporting currency does not.
  const start = `${rangeStart}-01`
  const end = monthEnd(`${rangeEnd}-01`)

  // The pair opens quoted in the default currency — the side a reader measures
  // against. The other side is the first currency the registry knows that is
  // not it: a pair of a currency against itself is not a rate, and the default
  // is not always USD.
  const defaultCurrency = useDefaultCurrency()
  const [to, setTo] = useState<string>(defaultCurrency)
  const [from, setFrom] = useState<string>(
    () =>
      registry.currencies.find((currency) => currency.code !== defaultCurrency)?.code ?? 'AUD',
  )

  // Fetched once, here, and handed to both the chart and the table below it.
  const trend = useRateTrend(from, to, start, end)

  return (
    <div className="fx">
      {/* The subhead that stood here said this screen obeys the date range and
          not the reporting currency. Removed at the Product Owner's instruction.
          Both facts are unchanged — the rail still renders the currency toggle
          at 40% opacity here, and nothing now explains why it is inert, which is
          the departure from the design handoff worth knowing about. */}

      {/* One panel and one heading across both columns: the controls on the
          left and the plot on the right are the same subject, and a second
          heading over the controls made the pair read as a thing separate from
          the trend it selects. */}
      <section className="panel fx__trend-panel">
        <h2 className="panel__heading">Trend</h2>

        <div className="fx__grid">
          <PairPicker
            currencies={registry.currencies}
            from={from}
            to={to}
            onFrom={setFrom}
            onTo={setTo}
            // Obeys the range like everything else here, but never past today.
            // Judging a rate's state at a month-end still to come ages it by the
            // days remaining: a rate entered this morning would be reported as a
            // fortnight old and flagged stale on time that has not passed. The
            // range's other consumer is a range of dates that have rates, and no
            // rate can be recorded in the future, so only this one needs
            // capping.
            statusAsOf={notAfterToday(end)}
          />
          <TrendChart from={from} to={to} trend={trend.data} pending={trend.isPending} />
        </div>
      </section>

      {/* The bulk entry form stood here — a date, a field per quoted currency,
          each showing its inverse live as it was typed, and a save that
          committed the date as a unit. Removed at the Product Owner's
          instruction. Nothing on this screen writes a rate any more: the
          provider button is the only source here, and a rate typed by hand now
          reaches the system through Month Close, the admin, or the API that
          serves them both — `/api/fx/rates/bulk/` is untouched and still
          tested. */}

      <PairTable
        base={registry.base}
        from={from}
        to={to}
        trend={trend.data}
        pending={trend.isPending}
      />
    </div>
  )
}

export function FxRates() {
  const registry = useCurrencies()

  if (registry.isPending) return <div className="boot">Loading…</div>
  if (!registry.data) return <ErrorBanner error={registry.error} />

  return <FxBoard registry={registry.data} />
}
