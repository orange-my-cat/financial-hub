/**
 * Settings.
 *
 * Four things, and the copy on three of them exists to prevent a
 * misunderstanding rather than to decorate:
 *
 *   reporting currency  a display choice; stored balances are always USD and
 *                       are never rewritten (BR-10)
 *   timezone            one, fixed, used only to decide what "today" means when
 *                       defaulting a date field (§9.4)
 *   staleness           7 days by default, changeable without a deploy (OI-13)
 *   variance            10% by default; advises, never blocks
 *
 * Backup status is a **readout only**. Backups are taken by the container
 * entrypoint, outside the application — there is nothing to run and nothing to
 * restore from here, and an in-application restore button was rejected as a
 * privileged destructive operation behind a single local password (ADR-11).
 */

import { useEffect, useState } from 'react'

import { ErrorBanner } from '@/components/Advisories'
import { useCurrencies, useSettings, useUpdateSettings } from '@/lib/fx'

export function Settings() {
  const settings = useSettings()
  const registry = useCurrencies()
  const update = useUpdateSettings()

  const [staleness, setStaleness] = useState('')
  const [variance, setVariance] = useState('')

  useEffect(() => {
    if (settings.data) {
      setStaleness(String(settings.data.rate_staleness_days))
      setVariance(settings.data.rate_variance_percent)
    }
  }, [settings.data])

  if (settings.isPending || registry.isPending) return <div className="boot">Loading…</div>
  if (!settings.data || !registry.data) return <ErrorBanner error={settings.error} />

  const current = settings.data

  return (
    <div className="settings">
      <p className="screen__subhead">
        Neither view control applies to this screen.
      </p>

      <ErrorBanner error={update.error} />

      <section className="panel">
        <h2 className="panel__heading">Reporting currency</h2>
        <p className="fx__note">
          A display choice only. The base and stored currency is always USD, and changing
          this rewrites nothing — it is reversible at any time.
        </p>
        <div className="seg">
          {registry.data.currencies.map((currency) => (
            <button
              key={currency.code}
              type="button"
              className={`seg__option mono${
                currency.code === current.reporting_currency ? ' seg__option--on' : ''
              }`}
              aria-pressed={currency.code === current.reporting_currency}
              onClick={() => update.mutate({ reporting_currency: currency.code })}
            >
              {currency.code}
            </button>
          ))}
        </div>
      </section>

      <section className="panel">
        <h2 className="panel__heading">Rate thresholds</h2>

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

      <section className="panel">
        <h2 className="panel__heading">Timezone</h2>
        <p className="fx__note">
          <span className="mono">{current.timezone}</span> — fixed. Used for exactly one
          thing: deciding what “today” means when a date field defaults. It never adjusts a
          stored date, and changing it would restate nothing. All financial dates are plain
          calendar dates with no time component.
        </p>
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
