/**
 * The header — reporting currency and date range, both mirrored to the URL.
 *
 * These are persistent view state, not filters. Where a control does not apply
 * to the current screen it renders at 40% opacity and is disabled, rather than
 * disappearing: a control that vanishes raises the question of where it went,
 * and a control that silently does nothing is worse than either.
 */

import { useLocation } from 'react-router-dom'

import { CURRENCIES } from '@/lib/money'
import { useLogout } from '@/lib/session'
import { useViewState } from '@/lib/viewState'

import { destinationFor } from './navigation'

export function Header() {
  const { pathname } = useLocation()
  const destination = destinationFor(pathname)
  const { currency, from, to, setCurrency } = useViewState()
  const logout = useLogout()

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

        {/* CSV export is a persistent secondary button in every screen header,
            never a tucked-away tertiary action: it is the only route data has
            out of the application. Wired at Stage 5. */}
        <button type="button" className="btn" disabled title="Available from Stage 5">
          Export CSV
        </button>

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
