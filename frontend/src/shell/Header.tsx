/**
 * The header — reporting currency and date range, both mirrored to the URL.
 *
 * These are persistent view state, not filters. Where a control does not apply
 * to the current screen it renders at 40% opacity and is disabled, rather than
 * disappearing: a control that vanishes raises the question of where it went,
 * and a control that silently does nothing is worse than either.
 */

import { useLocation } from 'react-router-dom'

import { exportUrl } from '@/lib/dashboard'
import { CURRENCIES } from '@/lib/money'
import { useLogout } from '@/lib/session'
import { useViewState } from '@/lib/viewState'

import { destinationFor } from './navigation'

/** Which report this screen exports. Null where the screen has no data of its own. */
const EXPORT_FOR: Record<string, string> = {
  '/': 'net-worth',
  '/net-worth': 'net-worth-trend',
  '/accounts': 'net-worth',
  '/month-close': 'net-worth',
  '/cash-flow': 'cashflow',
  '/investments': 'investments',
  '/fx-rates': 'fx',
}

export function Header() {
  const { pathname } = useLocation()
  const destination = destinationFor(pathname)
  const { currency, from, to, setCurrency } = useViewState()
  const logout = useLogout()
  const exportReport = EXPORT_FOR[destination.path] ?? null

  return (
    <header className="header">
      <h1 className="header__title">{destination.label}</h1>

      <div className="header__controls">
        <div
          className={`seg${destination.obeysCurrency ? '' : ' seg--inert'}`}
          role="group"
          aria-label="Reporting currency"
        >
          <span className="label seg__legend">Reporting</span>
          {CURRENCIES.map((code) => (
            <button
              key={code}
              type="button"
              className={`seg__option mono${code === currency ? ' seg__option--on' : ''}`}
              aria-pressed={code === currency}
              disabled={!destination.obeysCurrency}
              onClick={() => setCurrency(code)}
            >
              {code}
            </button>
          ))}
        </div>

        <div className={`range${destination.obeysRange ? '' : ' range--inert'}`}>
          <span className="label">Range</span>
          <span className="mono range__value">
            {from} — {to}
          </span>
        </div>

        {/* A persistent secondary button in every screen header, never a
            tucked-away tertiary action: it is the only route data has out of
            the application (ADR-11, departure D1).

            A plain link, not a fetch: the file is generated server-side and
            streamed with a Content-Disposition, so the bytes never pass through
            JavaScript that could reformat them. An export that disagreed with
            the screen it came from would be worse than none. */}
        {exportReport ? (
          <a
            className="btn"
            href={exportUrl(exportReport, { month: to, currency, from_month: from })}
            download
          >
            Export CSV
          </a>
        ) : (
          <button type="button" className="btn" disabled title="Nothing to export here">
            Export CSV
          </button>
        )}

        <button
          type="button"
          className="btn"
          onClick={() => logout.mutate()}
          disabled={logout.isPending}
        >
          Sign out
        </button>
      </div>
    </header>
  )
}
