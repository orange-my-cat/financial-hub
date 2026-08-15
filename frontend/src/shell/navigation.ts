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
 */

import type { IconName } from './icons'

export interface Destination {
  readonly path: string
  readonly label: string
  readonly icon: IconName
  readonly obeysCurrency: boolean
  readonly obeysRange: boolean
}

export const DESTINATIONS: readonly Destination[] = [
  // Fixed to the current month; the date range does not apply.
  { path: '/', label: 'Dashboard', icon: 'dashboard', obeysCurrency: true, obeysRange: false },
  { path: '/net-worth', label: 'Net worth', icon: 'netWorth', obeysCurrency: true, obeysRange: true },
  { path: '/accounts', label: 'Accounts', icon: 'accounts', obeysCurrency: true, obeysRange: false },
  // Neither view control applies; both render inert.
  { path: '/month-close', label: 'Month Close', icon: 'monthClose', obeysCurrency: false, obeysRange: false },
  // Amounts stay in the currency they were entered in and are never translated.
  { path: '/cash-flow', label: 'Cash flow', icon: 'cashFlow', obeysCurrency: false, obeysRange: true },
  // Every figure stays in its holding's own currency.
  { path: '/investments', label: 'Investments', icon: 'investments', obeysCurrency: false, obeysRange: true },
  { path: '/fx-rates', label: 'FX rates', icon: 'fxRates', obeysCurrency: false, obeysRange: true },
]

export const SETTINGS_DESTINATION: Destination = {
  path: '/settings',
  label: 'Settings',
  icon: 'settings',
  obeysCurrency: false,
  obeysRange: false,
}

export function destinationFor(pathname: string): Destination {
  // Account detail keys Accounts; Categories keys Cash flow.
  const match = [...DESTINATIONS, SETTINGS_DESTINATION]
    .filter((destination) => destination.path !== '/')
    .find((destination) => pathname.startsWith(destination.path))

  return match ?? DESTINATIONS[0]!
}
