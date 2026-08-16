/**
 * The ledger spine — the signature element.
 *
 * A month rail down the right edge, latest month at the top. Each row is a
 * month label plus its completeness glyph, and each row selects that month: it
 * ties the view to one timeline and makes the shape of the user's history
 * legible at a glance, then lets the user act on what they see.
 *
 * Selection writes to the URL like every other piece of view state, so the
 * spine and a screen's own month field are two faces of one value and cannot
 * disagree. It sets the working month only, never the reporting range — Month
 * Close and Cash flow both state that the range does not apply to them, and
 * picking a month to close must not silently restate the reports.
 *
 * It is shown only where a month is the thing being worked on (see
 * `showsSpine` in navigation). On a screen with no month to select, a rail of
 * month buttons would be a control that does nothing.
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
 *
 * Earlier months can be asked for a year at a time. They come back Outside
 * Range and stay that way — the button widens the window onto history, it does
 * not invent history — and the extra months are computed by the same service as
 * every other month rather than assumed to be empty by the browser.
 */

import { useState } from 'react'

import { formatMonth } from '@/lib/format'
import { useSpine } from '@/lib/dashboard'
import { useViewState } from '@/lib/viewState'

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

/** One press of Earlier. A year at a time, because the rail is read by year. */
const EXTEND_STEP = 12

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
}

export function Spine({ months }: SpineProps) {
  // The selected month is view state, held in the URL — not local to the
  // spine. A screen's own month field reads and writes the same value.
  const { month: currentMonth, setMonth } = useViewState()

  // The rail always runs through the present month, never through the selected
  // one. `through` truncates the list server-side, so asking for the selection
  // would delete every month after it — and selecting a month in the past would
  // be a one-way trip, with no row left to click to come back.
  const through = currentMonth > thisMonth() ? currentMonth : thisMonth()

  // How many months before the first recorded one to show. Deliberately not in
  // the URL: it is how far the user has scrolled back through the rail, not
  // what they are looking at, and it should not travel in a bookmark.
  const [extend, setExtend] = useState(0)

  // Derived server-side from the balances that exist (ADR-04). The `months`
  // prop overrides it, so a screen that already knows its range need not
  // re-fetch.
  const derived = useSpine(through, extend)

  const supplied = months && months.length > 0 ? months : derived.data?.data

  const rows: readonly SpineMonth[] =
    supplied && supplied.length > 0
      ? supplied
      : // Outside Range means "before the first account opened", which is
        // exactly what is true when no account exists yet — and not a fault.
        [{ month: currentMonth, state: 'Outside Range' }]

  return (
    <aside className="spine" aria-label="Months">
      {rows.map(({ month, state }) => (
        <button
          key={month}
          type="button"
          className={`spine__row${month === currentMonth ? ' spine__row--current' : ''}`}
          // Not aria-pressed: this is a set of options of which one is chosen,
          // not eight independent toggles.
          aria-current={month === currentMonth ? 'true' : undefined}
          onClick={() => setMonth(month)}
        >
          <span className="spine__month mono">{formatMonth(month)}</span>
          {/* The glyph carries the state, so it reads without colour. The word
              is the accessible name, so it reads without the glyph. */}
          <span className={GLYPH_CLASS[state]} role="img" aria-label={state} />
        </button>
      ))}

      {/* Last in the DOM, so it sits at the bottom of the rail — and at the
          left end of the tablet strip, which reverses direction. Either way it
          is at the old end of the timeline, which is the direction it extends.

          Hidden rather than disabled once the server says there is nothing
          further back: an inert control implies there is more to be had. */}
      {(months === undefined || months.length === 0) &&
        derived.data?.extendable !== false && (
          <button
            type="button"
            className="spine__extend"
            onClick={() => setExtend(extend + EXTEND_STEP)}
            disabled={derived.isFetching}
          >
            Earlier
          </button>
        )}
    </aside>
  )
}
