/**
 * Iconography — the rail's destinations, sign out in the header, and the few
 * glyphs that sit inside a screen.
 *
 * Lucide, rendered inline on `currentColor` from a 24px viewBox at 1.5px
 * stroke with round caps and joins — the handoff's geometry, drawn by a
 * maintained set rather than by hand. Lucide's own defaults are 24px and 2px,
 * so size and stroke width are set here and nowhere else; every glyph
 * therefore weighs the same on screen.
 *
 * Two sizes, and only two. Chrome is 20px. A glyph set beside body copy takes
 * `inline` at 14px, because a chrome-sized icon beside 11.5px text reads as the
 * subject and the words as its caption.
 *
 * Elements, not components: a call site renders a glyph by name and never
 * varies its props, so there is nothing for it to get wrong.
 */

import {
  ArrowLeftRight,
  CalendarCheck,
  ChartColumn,
  Check,
  Coins,
  CreditCard,
  Eye,
  EyeOff,
  LayoutGrid,
  LogOut,
  SlidersHorizontal,
  TrendingUp,
} from 'lucide-react'
import type { ReactElement } from 'react'

const base = {
  size: 20,
  // Not `absoluteStrokeWidth`: the stroke scales with the box, as it did when
  // these were drawn by hand, so the weight on screen is unchanged.
  strokeWidth: 1.5,
  'aria-hidden': true,
}

const inline = { ...base, size: 14 }

export type IconName =
  | 'dashboard'
  | 'netWorth'
  | 'accounts'
  | 'monthClose'
  | 'cashFlow'
  | 'investments'
  | 'fxRates'
  | 'settings'
  | 'signOut'
  | 'show'
  | 'hide'
  | 'saved'

export const icons: Record<IconName, ReactElement> = {
  dashboard: <LayoutGrid {...base} />,
  netWorth: <TrendingUp {...base} />,
  accounts: <CreditCard {...base} />,
  monthClose: <CalendarCheck {...base} />,
  // Two opposed arrows: money out, money in. Never a transfer — there is no
  // transfer affordance anywhere in this application.
  cashFlow: <ArrowLeftRight {...base} />,
  investments: <ChartColumn {...base} />,
  fxRates: <Coins {...base} />,
  settings: <SlidersHorizontal {...base} />,
  signOut: <LogOut {...base} />,
  // In-screen, beside the disclosure that reveals closed accounts. The open eye
  // offers the reveal; the struck one offers to put them away again.
  show: <Eye {...inline} />,
  hide: <EyeOff {...inline} />,
  // The bare tick in a Month Close row, in place of the word "saved". Sized
  // inline: it sits in a table of 11.5px figures, not in the chrome.
  saved: <Check {...inline} />,
}
