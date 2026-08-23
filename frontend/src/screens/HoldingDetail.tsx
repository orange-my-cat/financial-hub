/**
 * Holding detail — the transaction breakdown, and what the engine made of it.
 *
 * Account detail answers "is this balance rising"; this screen answers a
 * different question, because a holding's history is not a series of snapshots:
 *
 *     What do I hold, what did it cost, and where did that figure come from?
 *
 * Both are answered together. Beside the headline figure is a plot of cost basis
 * at each month end — the same geometry as the account trend, at the Product
 * Owner's instruction. It is a line through what was bought and kept, never
 * through what it became worth: no market price is stored, so the plot cannot
 * carry a paper gain or a return, and a month where it falls is a month
 * something was sold rather than a month the holding lost. Under the row is
 * entry, and under that the *workings* — the open lot queue, then each sale with
 * the lots it actually consumed, then every transaction with the figure replay
 * derived from it.
 *
 * Nothing here is computed in the browser. Every figure below arrived as a
 * string from the replay engine, including a purchase's cost and a sale's FIFO
 * basis, because money carries no arithmetic on this side of the wire (ADR-12).
 *
 * Everything is in **the holding's own currency**. The reporting-currency
 * control does not apply: translating performance would fold rate movement into
 * a figure that answers neither question (BR-18). The currency tag carries this.
 */

import { Fragment, useMemo, useState } from 'react'
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
import { LotQueue, RecordTransaction } from '@/components/Holding'
import { MonthBand } from '@/components/MonthBand'
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
  formatDate,
  formatDecimal,
  formatMonth,
  formatMonthShort,
  movementClass,
} from '@/lib/format'
import {
  useDeleteTransaction,
  useHolding,
  useUpdateHolding,
  type HoldingMonth,
  type HoldingTransaction,
  type InvestmentAction,
  type Sale,
} from '@/lib/investments'
import { DEFAULT_RANGE_MONTHS, shiftMonths } from '@/lib/viewState'

/**
 * The account trend's hover box, on this plot.
 *
 * Same box, same two-column list, because a reader moving between the two
 * screens is reading the same kind of line. Two figures rather than one: the
 * cost basis the line plots, and the units it was the cost of — the second is
 * why the first moved, and it is the only pair of facts a month end has.
 *
 * Formatted from the server's strings, never from the floats the chart plots
 * with. The geometry may be approximate; the figures never are.
 */
function CostBasisTooltip({
  active,
  label,
  currency,
  months,
}: {
  readonly active?: boolean
  readonly label?: string | number
  readonly currency: string
  readonly months: Readonly<Record<string, HoldingMonth>>
}) {
  const month = active && typeof label === 'string' ? label : undefined
  const row = month ? months[month] : undefined
  if (!month || !row) return null

  return (
    <div className="charttip">
      <div className="charttip__month mono">{formatMonth(month)}</div>
      <dl className="charttip__list">
        <dt>Cost basis</dt>
        <dd className="mono">
          {formatDecimal(row.cost_basis)} {currency}
        </dd>
        <dt>Units held</dt>
        <dd className="mono">{formatDecimal(row.quantity, 4)}</dd>
      </dl>
    </div>
  )
}

/**
 * The money a transaction moved, in the register's one figure column.
 *
 * A purchase adds to cost basis, a sale returns proceeds, a reinvestment
 * receives cash and spends it. A split moves no money at all: it restates the
 * units a lot is expressed in and leaves its cost alone, so the column is an em
 * dash rather than a zero.
 *
 * Which of the three it is, the figure no longer says — the labels that followed
 * it (`to basis`, `proceeds`, `cash`) were removed at the Product Owner's
 * instruction. The Action column two along names the action, and the three
 * actions that move money each move exactly one kind of it, so the label was
 * derivable from the row it sat on.
 *
 * Cash is tested first, which decides the one row that has two effects. For a
 * reinvestment the figure worth reading is the distribution — what the holding
 * paid out — and the cost it became is that cash plus the fees in the column
 * beside it, so nothing is hidden by preferring it.
 */
/**
 * The action's colour, at the Product Owner's instruction — one per action, not
 * one per kind of movement.
 *
 * Each takes an existing role from tokens.css rather than a new hue, and each
 * has a reading that fits: rise where units come in, breach where they go out,
 * carry on the one action funded by something the holding paid out rather than by
 * money the user put in. A split takes the cell's own colour because it moves
 * nothing at all — it restates the units a lot is expressed in and leaves both
 * the cost and the holding alone.
 *
 * The coloured thing is the word itself, so every one of them still reads
 * correctly with no colour at all.
 */
const ACTION_TONE: Readonly<Record<InvestmentAction, string>> = {
  Buy: 'action--buy',
  Sell: 'action--sell',
  Reinvestment: 'action--reinvestment',
  Split: '',
}

function amountOf(row: HoldingTransaction): string | null {
  if (row.distributed) return row.distributed
  if (row.acquired) return row.acquired.cost
  if (row.realised) return row.realised.proceeds
  return null
}

// ---------------------------------------------------------------------------

/**
 * Every transaction, newest first, with what replay made of it.
 *
 * Remove is offered on every row and asks nothing first, because an edit here
 * costs nothing to undo: no lot state, no cost basis and no gain was stored, so
 * removing a transaction restates everything after it for free and the row stays
 * recoverable in the admin (ADR-06, ADR-03).
 */
function Register({
  transactions,
}: {
  readonly transactions: readonly HoldingTransaction[]
}) {
  const remove = useDeleteTransaction()

  if (transactions.length === 0) {
    return <p className="fx__note">Nothing recorded against this holding yet.</p>
  }

  return (
    <table className="table">
      <thead>
        <tr>
          <th>Date</th>
          <th>Action</th>
          <th className="numeric">Units</th>
          <th className="numeric">Unit Price</th>
          <th className="numeric">Fees</th>
          <th className="numeric">Amount</th>
          <th className="numeric">Units Held</th>
          <th aria-label="Actions" />
        </tr>
      </thead>
      <tbody>
        {transactions.map((row) => {
          const amount = amountOf(row)
          const priced = row.acquired !== null || row.realised !== null

          return (
            <tr key={row.id}>
              <td className="mono">{formatDate(row.date)}</td>
              <td>
                <span className={`action ${ACTION_TONE[row.action]}`.trim()}>
                  {row.action}
                </span>
                {/* No `r` mark beside it: the mark existed to say a lot came from
                    a reinvestment rather than a purchase, and this column now
                    says `Reinvestment` in full. It stays on the open lot queue,
                    where the rows are lots and the action is not named. */}
                {/* ADR-07 on the row: a sale a later edit invalidated is named
                    here, and the holding's advisory above says what is wrong. */}
                {row.flagged && (
                  <sup className="mark mark--breach" title="Invalidated by a later edit">
                    !
                  </sup>
                )}
              </td>
              {/* A split's figure is its ratio, and it belongs in the units
                  column because that is the only thing it changes. */}
              <td className="numeric">
                {row.action === 'Split'
                  ? `× ${formatDecimal(row.split_ratio, 4)}`
                  : priced
                    ? formatDecimal(row.quantity, 4)
                    : '—'}
              </td>
              <td className="numeric secondary">
                {priced ? formatDecimal(row.unit_price, 4) : '—'}
              </td>
              <td className="numeric secondary">
                {priced ? formatDecimal(row.fees) : '—'}
              </td>
              <td className="numeric">{amount ? formatDecimal(amount) : '—'}</td>
              {/* A running total, not a per-lot remainder: what the holding
                  came to once this row had replayed. Every action moves it or
                  explicitly does not — a buy and a reinvestment add, a sale
                  takes from the oldest lots first, and a split restates all of
                  them, doubling this on a 2:1 without a unit being bought.

                  Derived by the engine, never accumulated here. What each lot
                  has left of itself is the Open Lots table above; this column
                  answers the other question, which is what was held at the time.
                  */}
              <td className="numeric secondary">
                {formatDecimal(row.units_held, 4)}
              </td>
              {/* The Note column was removed from this table at the Product
                  Owner's instruction. Entry still takes a note and the API
                  still returns it — nothing was dropped, only the column. */}
              {/* Not the breach colour Accounts gives Delete, and for a
                  reason: that colour marks the rare destructive action, and a
                  fortnightly buyer's register is thirty rows long. Thirty red
                  words down the edge read as thirty warnings. */}
              <td className="accounts__actions">
                <div className="accounts__actions-set">
                  <button
                    type="button"
                    className="link-button"
                    onClick={() => remove.mutate(row.id)}
                  >
                    Remove
                  </button>
                </div>
              </td>
            </tr>
          )
        })}
        <tr className="table__message-row">
          <td colSpan={8}>
            <ErrorBanner error={remove.error} />
          </td>
        </tr>
      </tbody>
    </table>
  )
}

// ---------------------------------------------------------------------------

/**
 * Each sale, and the lots it took its units from.
 *
 * This is the other half of the FIFO queue and the reason the queue is legible
 * at all: the open lots say what remains, and these rows say where a sale's cost
 * basis came from, oldest lot first. Between them the two account for every unit
 * ever bought.
 */
function Disposals({ sales }: { readonly sales: readonly Sale[] }) {
  /**
   * Closed to begin with, one sale at a time — the category report's rollup,
   * on the same kind of question.
   *
   * The workings were always open, which put two kinds of row in one table and
   * made a holding with a dozen sales unreadable: every second line was an
   * indented lot, and the sales themselves stopped reading as a list. What a
   * sale realised is the figure being scanned; which lots paid for it is the
   * follow-up, asked one sale at a time.
   */
  const [open, setOpen] = useState<readonly number[]>([])

  if (sales.length === 0) {
    return <p className="fx__note">No sales recorded.</p>
  }

  return (
    <table className="table">
      <thead>
        <tr>
          <th>Sale Date</th>
          <th className="numeric">Units</th>
          <th className="numeric">Proceeds</th>
          <th className="numeric">Fees</th>
          <th className="numeric">Cost Basis</th>
          <th className="numeric">Gross Gain</th>
          <th className="numeric">Est. Tax</th>
          {/* `Est.` in the header, not `indicative` on every cell: the estimate is
              a property of the column — a typed percentage, applied to whatever
              gain the row realised — so it is stated once at the top rather than
              suffixed to each figure. It still travels with the figure, which is
              what the rule asks. */}
          <th className="numeric">Est. Net Gain</th>
        </tr>
      </thead>
      <tbody>
        {sales.map((sale) => {
          const expanded = open.includes(sale.transaction_id)
          // An oversale a later edit invalidated can have consumed nothing.
          // Nothing to open, so no arrow and no pointer — an empty disclosure
          // invites a click that reveals nothing.
          const openable = sale.consumed.length > 0

          return (
            <Fragment key={sale.transaction_id}>
              {/* The row is the target, as it is on the category report: the arrow
                  says what will happen, but a 9px glyph is not what a pointer
                  should have to hit, and neither is a date when the figures beside
                  it are part of the same thought. */}
              <tr
                className={openable ? 'disclosure-row' : undefined}
                onClick={
                  openable
                    ? () =>
                        setOpen((current) =>
                          current.includes(sale.transaction_id)
                            ? current.filter((entry) => entry !== sale.transaction_id)
                            : [...current, sale.transaction_id],
                        )
                    : undefined
                }
              >
                <td className="mono">
                  {openable ? (
                    /* Carries the state and takes the focus, but not a handler of
                       its own: a click here — including the one Enter and Space
                       raise on a focused button — reaches the row above. */
                    <button type="button" className="disclosure" aria-expanded={expanded}>
                      <span className="disclosure__arrow" aria-hidden="true">
                        ▸
                      </span>
                      {formatDate(sale.date)}
                    </button>
                  ) : (
                    formatDate(sale.date)
                  )}
                </td>
                <td className="numeric">{formatDecimal(sale.quantity, 4)}</td>
                <td className="numeric">{formatDecimal(sale.proceeds)}</td>
                <td className="numeric secondary">{formatDecimal(sale.fees)}</td>
                <td className="numeric">{formatDecimal(sale.cost_basis)}</td>
                <td className="numeric">
                  <span className={sale.is_loss ? 'money money--breach' : 'money money--rise'}>
                    {formatDecimal(sale.realised_gain)}
                  </span>
                </td>
                {/* Losses are shown gross; no percentage is applied to them. */}
                <td className="numeric secondary">
                  {sale.tax_applied ? `${sale.estimated_tax_percent}%` : '—'}
                </td>
                <td className="numeric">{formatDecimal(sale.net_realised_gain)}</td>
              </tr>

              {expanded &&
                sale.consumed.map((taken) => (
                  <tr
                    className="invest__consumed"
                    key={`${sale.transaction_id}-${taken.lot_transaction_id}`}
                  >
                    {/* Indented to start where the sale's date does, so a lot reads
                        as belonging to the row above rather than as another sale —
                        the category report's child indent, on this table. */}
                    <td className="secondary disclosure__child">
                      From the lot of {formatDate(taken.acquired)}
                    </td>
                    <td className="numeric secondary">{formatDecimal(taken.quantity, 4)}</td>
                    <td colSpan={2} />
                    <td className="numeric secondary">{formatDecimal(taken.cost_basis)}</td>
                    <td colSpan={3} />
                  </tr>
                ))}
            </Fragment>
          )
        })}
      </tbody>
    </table>
  )
}

// ---------------------------------------------------------------------------

export function HoldingDetail() {
  const { holdingId } = useParams()
  const query = useHolding(Number(holdingId))
  const update = useUpdateHolding()
  /** Which month the pointer is over — the plot draws its own band, as the
      account trend and the dashboard's three do. */
  const [hover, setHover] = useState<string | null>(null)

  /**
   * Contiguous months ending at the latest the server sent, which is the month
   * in progress: a holding has a cost basis every month from its first
   * transaction onwards, including the zero months after it was sold out.
   *
   * Months before the holding's first transaction are null rather than zero, and
   * Recharts breaks the line on a null — the honest rendering of a month in
   * which there was nothing to hold. The window is the reports' own default
   * length, so this plot spans the same months the account trend does.
   */
  const chart = useMemo(() => {
    const history = query.data?.history ?? []
    const latest = history[0]?.month
    if (!latest) return []

    const recorded = new Map(history.map((row) => [row.month, Number(row.cost_basis)]))
    return Array.from({ length: DEFAULT_RANGE_MONTHS }, (_, offset) => {
      const month = shiftMonths(latest, offset - (DEFAULT_RANGE_MONTHS - 1))
      return { month, cost: recorded.get(month) ?? null }
    })
  }, [query.data])

  /** How many months the line actually has. One point is not a trend. */
  const plotted = chart.filter((point) => point.cost !== null).length

  /** The exact figures, by month — what the tooltip states, never the floats
      the chart plots with. */
  const months = useMemo(
    () => Object.fromEntries((query.data?.history ?? []).map((row) => [row.month, row])),
    [query.data],
  )

  /** `activeLabel` is the month, the same handler shape the other plots use. */
  const track = (state: MouseHandlerDataParam) => {
    const hovered = state?.activeLabel
    if (typeof hovered === 'string') setHover(hovered)
  }

  if (query.isPending) return <div className="boot">Loading…</div>
  if (!query.data) return <ErrorBanner error={query.error} />

  const holding = query.data

  return (
    <div className="detail">
      <nav className="detail__crumb">
        <Link to="/investments">Investments</Link>
        <span className="secondary"> / {holding.name}</span>
      </nav>

      <h2 className="detail__name">
        {holding.name}
        {/* The register's chip, on the page the register links to: the same
            short fixed label confirming which instrument the name means, so it
            reads as the same fact on both screens rather than as a second
            phrase to read on from the title into. */}
        {holding.symbol && (
          <span className="tag tag--symbol mono">{holding.symbol}</span>
        )}
      </h2>

      <div className="detail__tags">
        <span className="tag">{holding.instrument_type}</span>
        <span className="tag">{holding.account}</span>
        <span className="tag mono">{holding.currency}</span>
        <span className="tag">
          {holding.lot_count} open lot{holding.lot_count === 1 ? '' : 's'}
        </span>

        {/* Edited here rather than on the register, because changing it restates
            the net figure on every historic sale below — including sales already
            reported. Free, because nothing was stored (BR-21). */}
        <label className="invest__tax">
          <span className="label">Est. tax %</span>
          <input
            className="input mono"
            inputMode="decimal"
            defaultValue={holding.estimated_tax_percent ?? ''}
            onBlur={(event) =>
              update.mutate({
                id: holding.id,
                estimated_tax_percent: event.target.value || null,
              })
            }
          />
        </label>
      </div>

      {/* The two prohibition paragraphs that stood here — no unrealised gain
          exists in this system, and estimated tax is a percentage you typed
          rather than a calculation — were removed at the Product Owner's
          instruction, as they were from the Investments register before it.

          A departure worth naming: the BRD and the design handoff both require
          them as copy on the screen, not merely as an implemented rule. The
          rules are unchanged and still enforced — no endpoint returns a market
          price, a paper gain or a return, and no jurisdiction's rules are ever
          applied — and `/api/investments/holdings/<id>/` still returns both
          sentences under `prohibitions`, so any screen can state them again. The
          one surviving trace on this page is the Est. Net Gain column, whose
          header says the figure under it is an estimate. */}

      {/* Flagged, never blocked. Everything below still computes and entry
          still works. */}
      {!holding.consistent &&
        holding.inconsistencies.map((problem) => (
          <div className="advisory" key={problem.transaction_id} role="status">
            <span className="advisory__label">Advisory · Retroactively invalid</span>
            <span className="advisory__body">{problem.message}</span>
          </div>
        ))}

      {/* The figure column beside the plot, as on account detail — the same
          330px column, the same three stacked figures, so a reader moving
          between the two screens finds the headline in the same place.

          The tables below stay full width and stack under the row, because an
          open lot queue has no fixed height: buying fortnightly makes a
          thirty-lot queue ordinary, and beside one of those a narrow figure
          column would be mostly empty. */}
      <div className="detail__body">
        <section className="panel detail__figure">
          <span className="label">Cost Basis · Held</span>
          <div className="networth__total mono">
            {formatDecimal(holding.total_cost_basis)}
            <span className="money__code">{holding.currency}</span>
          </div>

          <dl className="detail__stats">
            <div>
              <dt className="label">Units held</dt>
              <dd className="mono">{formatDecimal(holding.total_quantity, 4)}</dd>
            </div>
            <div>
              <dt className="label">Realised gain, gross</dt>
              <dd className={`mono ${movementClass(holding.realised.gross)}`.trim()}>
                {formatDecimal(holding.realised.gross)}
              </dd>
            </div>
            <div>
              <dt className="label">Distributions</dt>
              <dd className="mono">{formatDecimal(holding.distributions)}</dd>
            </div>
          </dl>
        </section>

        {/* The account trend's plot, on this holding's cost basis: the same
            geometry from @/lib/charts, the same drawn month band and the same
            hover box, because a reader comparing shapes across two screens is
            misled by a shorter plot or a narrower gutter.

            Uncaptioned, as the account plot is, at the Product Owner's
            instruction. What it plots is what the units still held cost, so it
            steps up when something was bought and down when something was sold,
            and it is flat through every month in between however the market
            moved — there being no market price here to move it. The headline
            figure it sits beside names the figure, and the hover box states
            cost basis and units held on every month. */}
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
                {/* No cursor rule: the band under the line is the highlight. */}
                <Tooltip
                  cursor={false}
                  content={
                    <CostBasisTooltip currency={holding.currency} months={months} />
                  }
                />
                <Line
                  type="linear"
                  dataKey="cost"
                  stroke={ACCENT}
                  strokeWidth={2}
                  dot={false}
                  // A month before the holding existed stays a gap.
                  connectNulls={false}
                  isAnimationActive={false}
                />
              </LineChart>
            </ResponsiveContainer>
          </section>
        )}
      </div>

      {/*
        Entry first, then what it produced, at the Product Owner's instruction:
        the thing that makes a row exist comes before the rows, as the create
        form does on Accounts and on the Investments register.

        Locked to this holding — no picker, because there is no choice left to
        make on a page that is already about one holding.
      */}
      <RecordTransaction holding={holding} key={holding.id} />

      {/* The queue the handoff gave a full column on the register, moved to the
          page it explains: it accounts for the cost basis in the figure column
          above, lot by lot. */}
      <section className="panel">
        <h2 className="panel__heading">Open Lots</h2>
        <LotQueue position={holding} />
      </section>

      {/* Before the full register, because it is the narrower question — the
          lots each sale consumed is the one piece of FIFO arithmetic a reader
          comes here to check. The register is the whole history, and it reads as
          the reference underneath rather than the thing being looked up. */}
      <section className="panel">
        <h2 className="panel__heading">Sales</h2>
        {/* The note that stood here — oldest lot first, which is the only order
            FIFO has, and net figures are indicative estimates carrying no
            percentage on a loss — was removed at the Product Owner's
            instruction. All three rules still hold and two still show: the lots
            a sale consumed are listed in FIFO order when its row is opened, and
            the Est. Net Gain column says in its header that the figure under it
            is an estimate. A loss simply shows an em dash in the tax column. */}
        <Disposals sales={holding.realised.sales} />
      </section>

      <section className="panel">
        <h2 className="panel__heading">Transactions</h2>
        <Register transactions={holding.transactions} />
      </section>
    </div>
  )
}
