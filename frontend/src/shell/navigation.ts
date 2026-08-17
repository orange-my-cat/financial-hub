/**
 * The rail's destinations, in order.
 *
 * Seven tabs plus Settings, pinned to the bottom and separated from the group.
 * Two screens are nested rather than tabs and so do not appear here: Account
 * detail opens from a name in the Accounts table and keys Accounts, and
 * Categories is the third tab on Cash flow and keys Cash flow.
 *
 * `obeysCurrency` and `obeysRange` are not decoration. Where a view control
 * does not apply, the chrome renders it at 40% opacity and the screen's subhead
 * says so — a control that silently does nothing is worse than one that is
 * visibly inert.
 *
 * `showsSpine` is the one exception to that rule, and for a reason: the spine
 * now *selects* the working month rather than only reporting on it. An inert
 * rail of eight month buttons is not a legible way to say "no month applies
 * here", so on screens that do not work a month at a time it is absent and the
 * screen widens into the space.
 */

import type { IconName } from './icons'

export interface Destination {
  readonly path: string
  readonly label: string
  readonly icon: IconName
  readonly obeysCurrency: boolean
  readonly obeysRange: boolean
  /** Whether this screen works one month at a time, and so can be driven by the spine. */
  readonly showsSpine: boolean
}

export const DESTINATIONS: readonly Destination[] = [
  // Fixed to the last closed month, which the screen names in its subhead; the
  // date range does not apply.
  { path: '/', label: 'Dashboard', icon: 'dashboard', obeysCurrency: true, obeysRange: false, showsSpine: false },
  { path: '/net-worth', label: 'Net Worth', icon: 'netWorth', obeysCurrency: true, obeysRange: true, showsSpine: false },
  // The register and the account detail beneath it are in each account's own
  // currency; nothing here is translated, so the toggle renders inert.
  { path: '/accounts', label: 'Accounts', icon: 'accounts', obeysCurrency: false, obeysRange: false, showsSpine: false },
  // Neither view control applies. The currency governed the rate section, and
  // rates are loaded from the provider now rather than typed here; balances
  // were never translated and stay in each account's own currency. The spine
  // drives the month.
  { path: '/month-close', label: 'Month Close', icon: 'monthClose', obeysCurrency: false, obeysRange: false, showsSpine: true },
  // Amounts stay in the currency they were entered in and are never translated.
  { path: '/cash-flow', label: 'Cash Flow', icon: 'cashFlow', obeysCurrency: false, obeysRange: true, showsSpine: true },
  // Every figure stays in its holding's own currency.
  { path: '/investments', label: 'Investments', icon: 'investments', obeysCurrency: false, obeysRange: true, showsSpine: false },
  { path: '/fx-rates', label: 'FX Rates', icon: 'fxRates', obeysCurrency: false, obeysRange: true, showsSpine: false },
]

export const SETTINGS_DESTINATION: Destination = {
  path: '/settings',
  label: 'Settings',
  icon: 'settings',
  obeysCurrency: false,
  obeysRange: false,
  showsSpine: false,
}

export function destinationFor(pathname: string): Destination {
  // Account detail keys Accounts; Categories keys Cash flow.
  const match = [...DESTINATIONS, SETTINGS_DESTINATION]
    .filter((destination) => destination.path !== '/')
    .find((destination) => pathname.startsWith(destination.path))

  return match ?? DESTINATIONS[0]!
}
