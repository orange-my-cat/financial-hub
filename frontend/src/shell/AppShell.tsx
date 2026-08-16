/**
 * The application chrome.
 *
 * One chrome — icon rail plus header — with screens swapping inside it, and the
 * ledger spine down the right edge of the screens that work a month at a time.
 * The design board draws each screen as a standalone card with the chrome
 * repeated; that is a board convention, not the application's structure.
 *
 * Header, main and spine are all direct children of the shell grid so the
 * header can span the full width and sit above the spine, rather than the spine
 * running up alongside it. Nesting main and header in a wrapper would make that
 * span impossible.
 *
 * Settings are fetched here and waited for, because the default currency they
 * carry is what every currency selector below starts at. Rendering first and
 * correcting afterwards would show a screen in USD, refetch it in the user's
 * currency, and swap the figures under them — for a request that resolves
 * before the first screen paints.
 */

import { Outlet, useLocation } from 'react-router-dom'

import { useSettings } from '@/lib/fx'

import { Header } from './Header'
import { Rail } from './Rail'
import { Spine } from './Spine'
import { destinationFor } from './navigation'

export function AppShell() {
  const { pathname } = useLocation()
  const settings = useSettings()
  // Where the spine is absent the grid loses its third column outright, so the
  // screen widens into the space rather than leaving a 124px gutter of nothing.
  const showsSpine = destinationFor(pathname).showsSpine

  // Pending only. A failed request falls through to the base currency and lets
  // each screen report its own error — settings are not worth locking the
  // application out over.
  if (settings.isPending) {
    return <div className="boot">Loading…</div>
  }

  return (
    <div className={`shell${showsSpine ? '' : ' shell--flush'}`}>
      <Rail />
      <Header />
      <main className="shell__main">
        <Outlet />
      </main>
      {showsSpine && <Spine />}
    </div>
  )
}
