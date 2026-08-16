/**
 * The header — reporting currency, mirrored to the URL.
 *
 * This is persistent view state, not a filter. Where the control does not apply
 * to the current screen it renders at 40% opacity and is disabled, rather than
 * disappearing: a control that vanishes raises the question of where it went,
 * and a control that silently does nothing is worse than either.
 *
 * The date range is still view state and still mirrored to the URL — each
 * screen that obeys it reads it from there — it is simply no longer displayed
 * here. It still reaches CSV export, which now lives on Settings.
 */

import { useLocation } from 'react-router-dom'

import { REPORTING_CURRENCIES } from '@/lib/money'
import { useLogout } from '@/lib/session'
import { useViewState } from '@/lib/viewState'

import { icons } from './icons'
import { destinationFor } from './navigation'

export function Header() {
  const { pathname } = useLocation()
  const destination = destinationFor(pathname)
  const { currency, setCurrency } = useViewState()
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
          {/* Reporting currencies, not every currency held: a balance may be
              denominated in gold, but net worth is never stated in ounces. */}
          {REPORTING_CURRENCIES.map((code) => (
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

        {/* Icon only and smaller than its neighbour by intent — the cost of a
            misclick here is a lost session. */}
        <button
          type="button"
          className="btn btn--icon"
          onClick={() => logout.mutate()}
          disabled={logout.isPending}
          aria-label="Sign out"
          title="Sign out"
        >
          {icons.signOut}
        </button>
      </div>
    </header>
  )
}
