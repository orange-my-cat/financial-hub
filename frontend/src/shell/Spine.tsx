/**
 * The ledger spine — the signature element.
 *
 * A persistent month rail down the right edge of every screen, latest month at
 * the top. Each row is a month label plus its completeness glyph. The spine is
 * the same on every screen: it ties every view to one timeline and makes the
 * shape of the user's history legible at a glance.
 *
 * At tablet width it becomes a horizontal strip below the header, running
 * ascending left to right, with the current month keyed at the right end —
 * handled in CSS by reversing the flex direction, so the DOM order stays
 * chronologically honest in both layouts.
 *
 * **The range runs from the first month that has data to the current month.**
 * There is no month table and there never will be: months are derived from the
 * balances that exist (ADR-04). An account is required only from the later of
 * its opening date and the first month a balance was actually recorded for it,
 * so a fixed window of trailing months would be inventing history the user has
 * not entered.
 *
 * Until the first balance exists there is nothing to derive, so the spine shows
 * the current month alone. That is the degenerate case of the same rule, not a
 * special one — the moment a balance is saved, the range grows from it.
 */

import { formatMonth } from '@/lib/format'
import { useSpine } from '@/lib/dashboard'

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

function thisMonth(): string {
  const now = new Date()
  return `${now.getUTCFullYear()}-${String(now.getUTCMonth() + 1).padStart(2, '0')}`
}

interface SpineProps {
  /**
   * Latest first, starting at the first month with recorded data. Supplied by
   * the completeness service from Stage 1; absent until then.
   */
  readonly months?: readonly SpineMonth[]
  /** The month being reported on or closed. */
  readonly current?: string
}

export function Spine({ months, current }: SpineProps) {
  const currentMonth = current ?? thisMonth()
  // Derived server-side from the balances that exist (ADR-04). The `months`
  // prop overrides it, so a screen that already knows its range need not
  // re-fetch.
  const derived = useSpine(currentMonth)

  const supplied = months && months.length > 0 ? months : derived.data

  const rows: readonly SpineMonth[] =
    supplied && supplied.length > 0
      ? supplied
      : // Outside Range means "before the first account opened", which is
        // exactly what is true when no account exists yet — and not a fault.
        [{ month: currentMonth, state: 'Outside Range' }]

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
