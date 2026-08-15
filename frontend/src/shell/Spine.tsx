/**
 * The ledger spine — the signature element.
 *
 * A persistent month rail down the right edge of every screen, 100px wide,
 * latest month at the top. Each row is a month label plus its completeness
 * glyph. The spine is the same on every screen: it ties every view to one
 * timeline and makes the shape of the user's history legible at a glance.
 *
 * At tablet width it becomes a horizontal strip below the header, running
 * ascending left to right, with the current month keyed at the right end —
 * handled in CSS by reversing the flex direction, so the DOM order stays
 * chronologically honest in both layouts.
 *
 * Stage 0 shows every month as Outside Range, which is not a placeholder: it is
 * state S1, the first run, where no account has been opened yet. Outside Range
 * means "before the first account existed" and is not a fault.
 */

import { formatMonth } from '@/lib/format'

export type Completeness = 'Complete' | 'Incomplete' | 'Missing' | 'Outside Range'

const GLYPH_CLASS: Record<Completeness, string> = {
  Complete: 'glyph glyph--complete',
  Incomplete: 'glyph glyph--incomplete',
  Missing: 'glyph glyph--missing',
  'Outside Range': 'glyph glyph--outside',
}

export interface SpineMonth {
  /** `2026-08` */
  readonly month: string
  readonly state: Completeness
}

function recentMonths(count: number): string[] {
  const now = new Date()
  return Array.from({ length: count }, (_, index) => {
    const date = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth() - index, 1))
    return `${date.getUTCFullYear()}-${String(date.getUTCMonth() + 1).padStart(2, '0')}`
  })
}

interface SpineProps {
  readonly months?: readonly SpineMonth[]
  /** The month being reported on or closed. */
  readonly current?: string
}

export function Spine({ months, current }: SpineProps) {
  const rows: readonly SpineMonth[] =
    months ?? recentMonths(24).map((month) => ({ month, state: 'Outside Range' as const }))

  const currentMonth = current ?? rows[0]?.month

  return (
    <aside className="spine" aria-label="Months">
      {rows.map(({ month, state }) => (
        <div
          key={month}
          className={`spine__row${month === currentMonth ? ' spine__row--current' : ''}`}
        >
          <span className="spine__month mono">{formatMonth(month)}</span>
          {/* The glyph carries the state, so it reads without colour. The word
              is the accessible name, so it reads without the glyph. */}
          <span className={GLYPH_CLASS[state]} role="img" aria-label={state} />
        </div>
      ))}
    </aside>
  )
}
