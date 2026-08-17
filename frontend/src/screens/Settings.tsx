/**
 * Settings.
 *
 * Also the home of CSV export. It was a persistent button in every screen
 * header (ADR-11, departure D1); it is now one panel here, where the report is
 * chosen explicitly rather than implied by whichever screen the user happens to
 * be standing on. The export itself is unchanged — same endpoint, same
 * server-computed figures.
 *
 * Three settings, and the copy on each exists to prevent a misunderstanding
 * rather than to decorate:
 *
 *   default currency    what every currency selector starts at — the header's
 *                       reporting control and each entry form. A display choice
 *                       and a starting point only: an explicit choice wins,
 *                       stored balances are always USD, and nothing is
 *                       rewritten (BR-10)
 *   staleness           7 days by default, changeable without a deploy (OI-13)
 *   variance            10% by default; advises, never blocks
 *
 * The timezone is deliberately absent. It is one fixed value that decides what
 * "today" means when a date field defaults (§9.4) and nothing about it is
 * settable, so a panel stating it only invited the question of how to change it.
 * It is still served on the settings payload for anything that needs it.
 *
 * Backup status is a **readout only**. Backups are taken by the container
 * entrypoint, outside the application — there is nothing to run and nothing to
 * restore from here, and an in-application restore button was rejected as a
 * privileged destructive operation behind a single local password (ADR-11).
 */

import { useEffect, useState } from 'react'

import { ErrorBanner } from '@/components/Advisories'
import { exportUrl } from '@/lib/dashboard'
import { useCurrencies, useSettings, useUpdateSettings } from '@/lib/fx'
import { useViewState } from '@/lib/viewState'

/** The five reports the export endpoint serves, and what each one takes.
 *
 * Only two obey the reporting currency, and cash flow obeys none of it — it
 * stays in the currency each amount was entered in, exactly as its screen does.
 * Each report states its own parameters below rather than the panel implying a
 * single set that applies to all of them.
 */
interface ExportReport {
  readonly id: string
  readonly label: string
  /** Query parameters for this report, from the view state in the URL. */
  readonly params: (view: { currency: string; from: string; to: string }) => Record<string, string>
  /** What the file will contain, in the user's terms, with the actual values. */
  readonly describe: (view: { currency: string; from: string; to: string }) => string
}

/** The last calendar day of a `YYYY-MM` month. Day 0 of the next month. */
function lastDayOf(month: string): string {
  const [year, index] = month.split('-').map(Number)
  const end = new Date(Date.UTC(year ?? 1970, index ?? 1, 0))
  return end.toISOString().slice(0, 10)
}

const REPORTS: readonly ExportReport[] = [
  {
    id: 'net-worth',
    label: 'Net Worth — One Month',
    params: (v) => ({ month: v.to, currency: v.currency }),
    describe: (v) => `Every open account at ${v.to}, translated to ${v.currency}.`,
  },
  {
    id: 'net-worth-trend',
    label: 'Net Worth — Trend',
    params: (v) => ({ from_month: v.from, month: v.to, currency: v.currency }),
    describe: (v) => `One row per month from ${v.from} to ${v.to}, translated to ${v.currency}.`,
  },
  {
    id: 'cashflow',
    label: 'Cash Flow',
    params: (v) => ({ month: v.to }),
    describe: (v) =>
      `Transactions for ${v.to}. The reporting currency does not apply — amounts stay in the currency they were entered in.`,
  },
  {
    id: 'investments',
    label: 'Investments — Realised Gains',
    params: () => ({}),
    describe: () =>
      'Every realised disposal, all years, with its FIFO cost basis. Gains are indicative — estimated tax is a typed percentage, not a calculation.',
  },
  {
    id: 'fx',
    label: 'Exchange Rates',
    params: (v) => ({ start: `${v.from}-01`, end: lastDayOf(v.to) }),
    describe: (v) => `Every stored rate from ${v.from}-01 to ${lastDayOf(v.to)}.`,
  },
]

export function Settings() {
  const settings = useSettings()
  const registry = useCurrencies()
  const update = useUpdateSettings()
  const view = useViewState()

  const [staleness, setStaleness] = useState('')
  const [variance, setVariance] = useState('')
  const [report, setReport] = useState(REPORTS[0]!.id)

  useEffect(() => {
    if (settings.data) {
      setStaleness(String(settings.data.rate_staleness_days))
      setVariance(settings.data.rate_variance_percent)
    }
  }, [settings.data])

  if (settings.isPending || registry.isPending) return <div className="boot">Loading…</div>
  if (!settings.data || !registry.data) return <ErrorBanner error={settings.error} />

  const current = settings.data
  const chosen = REPORTS.find((candidate) => candidate.id === report) ?? REPORTS[0]!

  return (
    <div className="settings">
      <ErrorBanner error={update.error} />

      <section className="panel">
        <h2 className="panel__heading">Default Currency</h2>
        <p className="fx__note">
          What every currency selector starts at — the reporting currency in the header,
          and the currency field on each entry form. A starting point, never an override:
          a report that names its own currency keeps it, and a currency already chosen on
          a form is left alone.
        </p>
        <p className="fx__note">
          A display choice only. The base and stored currency is always USD, and changing
          this rewrites nothing — it is reversible at any time.
        </p>
        <div className="seg">
          {/* Filtered on `can_report`, which the API serves. Gold denominates a
              balance but does not state a net worth, and mapping the whole
              registry here would offer it. */}
          {registry.data.currencies.filter((currency) => currency.can_report).map((currency) => (
            <button
              key={currency.code}
              type="button"
              className={`seg__option mono${
                currency.code === current.default_currency ? ' seg__option--on' : ''
              }`}
              aria-pressed={currency.code === current.default_currency}
              onClick={() => update.mutate({ default_currency: currency.code })}
            >
              {currency.code}
            </button>
          ))}
        </div>
      </section>

      <section className="panel">
        <h2 className="panel__heading">Rate Thresholds</h2>

        <div className="field">
          <label className="field__label" htmlFor="staleness">
            Staleness, in days
          </label>
          <input
            id="staleness"
            className="input mono settings__number"
            inputMode="numeric"
            value={staleness}
            onChange={(event) => setStaleness(event.target.value)}
            onBlur={() => {
              const parsed = Number(staleness)
              if (Number.isInteger(parsed) && parsed >= 1) {
                update.mutate({ rate_staleness_days: parsed })
              }
            }}
          />
          <span className="fx__note">
            A rate older than this on the date it is used is flagged and raises an
            outstanding task. Carrying forward is never refused — that would make net
            worth uncomputable because of a lapse in typing.
          </span>
        </div>

        <div className="field">
          <label className="field__label" htmlFor="variance">
            Rate variance advisory, in percent
          </label>
          <input
            id="variance"
            className="input mono settings__number"
            inputMode="decimal"
            value={variance}
            onChange={(event) => setVariance(event.target.value)}
            onBlur={() => {
              if (variance.trim() && Number(variance) > 0) {
                update.mutate({ rate_variance_percent: variance })
              }
            }}
          />
          <span className="fx__note">
            A new rate differing from its predecessor by more than this raises an advisory.
            It never blocks the save — a genuine move of this size is not an error, but a
            misplaced decimal looks identical and nothing else would catch it.
          </span>
        </div>
      </section>

      {/* Export and backup sit together because they answer the same question
          from two directions — one is the route data takes out of the
          application, the other is the route it comes back from (ADR-11). */}
      <section className="panel">
        <h2 className="panel__heading">Export</h2>
        <p className="fx__note">
          The only route data has out of this application. Files are generated server-side
          from the same services the screens use, so an export can never disagree with the
          screen it came from.
        </p>

        <div className="field">
          <label className="field__label" htmlFor="export-report">
            Report
          </label>
          <select
            id="export-report"
            className="input settings__report"
            value={report}
            onChange={(event) => setReport(event.target.value)}
          >
            {REPORTS.map((candidate) => (
              <option key={candidate.id} value={candidate.id}>
                {candidate.label}
              </option>
            ))}
          </select>
          <span className="fx__note">{chosen.describe(view)}</span>
        </div>

        {/* A plain link, not a fetch: the file is streamed with a
            Content-Disposition, so the bytes never pass through JavaScript that
            could reformat them. */}
        <a className="btn" href={exportUrl(chosen.id, chosen.params(view))} download>
          Export CSV
        </a>
      </section>

      <section className="panel">
        <h2 className="panel__heading">Backup</h2>
        <p className="fx__note">
          A status readout arrives at Stage 5. Backups are taken by the container on every
          start, outside the application — there is nothing to run or restore from here.
        </p>
      </section>
    </div>
  )
}
