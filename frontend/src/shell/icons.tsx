/**
 * Rail iconography.
 *
 * Inline SVG on `currentColor`, 24px viewBox, 1.5px stroke, round caps and
 * joins — Phosphor-style geometric glyphs, one per destination. No icon
 * library: eight paths are not worth a dependency maintained for a decade.
 */

import type { ReactElement } from 'react'

const base = {
  width: 20,
  height: 20,
  viewBox: '0 0 24 24',
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 1.5,
  strokeLinecap: 'round' as const,
  strokeLinejoin: 'round' as const,
  'aria-hidden': true,
}

export type IconName =
  | 'dashboard'
  | 'netWorth'
  | 'accounts'
  | 'monthClose'
  | 'cashFlow'
  | 'investments'
  | 'fxRates'
  | 'settings'

export const icons: Record<IconName, ReactElement> = {
  dashboard: (
    <svg {...base}>
      <rect x="3" y="3" width="7.5" height="7.5" rx="1.5" />
      <rect x="13.5" y="3" width="7.5" height="7.5" rx="1.5" />
      <rect x="3" y="13.5" width="7.5" height="7.5" rx="1.5" />
      <rect x="13.5" y="13.5" width="7.5" height="7.5" rx="1.5" />
    </svg>
  ),
  netWorth: (
    <svg {...base}>
      <path d="M3 20h18" />
      <path d="M4 16l5-5 3.5 3.5L20 7" />
      <path d="M15.5 7H20v4.5" />
    </svg>
  ),
  accounts: (
    <svg {...base}>
      <rect x="3" y="6" width="18" height="12" rx="2" />
      <path d="M3 10h18" />
      <path d="M16.5 14.5h1.5" />
    </svg>
  ),
  monthClose: (
    <svg {...base}>
      <rect x="3.5" y="5" width="17" height="16" rx="2" />
      <path d="M3.5 10h17" />
      <path d="M8 3v4M16 3v4" />
      <path d="M9 15.5l2.25 2.25L15.5 13.5" />
    </svg>
  ),
  cashFlow: (
    <svg {...base}>
      <path d="M4 8h13" />
      <path d="M13.5 4.5L17 8l-3.5 3.5" />
      <path d="M20 16H7" />
      <path d="M10.5 12.5L7 16l3.5 3.5" />
    </svg>
  ),
  investments: (
    <svg {...base}>
      <path d="M3 20h18" />
      <rect x="5" y="11" width="3.5" height="6" rx="1" />
      <rect x="10.25" y="7" width="3.5" height="10" rx="1" />
      <rect x="15.5" y="13" width="3.5" height="4" rx="1" />
    </svg>
  ),
  fxRates: (
    <svg {...base}>
      <circle cx="8" cy="8" r="4.5" />
      <circle cx="16" cy="16" r="4.5" />
      <path d="M14.5 6.5h4.5V11" />
      <path d="M9.5 17.5H5V13" />
    </svg>
  ),
  settings: (
    <svg {...base}>
      <path d="M3 7h11M18 7h3" />
      <path d="M3 17h5M12 17h9" />
      <circle cx="16" cy="7" r="2.25" />
      <circle cx="10" cy="17" r="2.25" />
    </svg>
  ),
}
