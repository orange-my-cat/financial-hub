/**
 * The one formatting module (ADR-15).
 *
 * `date-fns` and `dinero.js` were rejected: the browser already does this well,
 * and quality attribute 4 argues against carrying dependencies for a decade
 * that the platform supplies.
 *
 * One exception to "let the platform do it": amounts are rounded here, on the
 * decimal string, rather than handed to `Intl.NumberFormat`. Intl takes a
 * `number`, and a `number` is a float — which would reintroduce at the last
 * step the precision the entire back end exists to preserve. The rounding is
 * half-up, applied once, at display, exactly as ADR-02 specifies.
 */

import type { Money } from './money'

// ---------------------------------------------------------------------------
// Amounts
// ---------------------------------------------------------------------------

/** U+2212. Negatives take a minus sign, never parentheses. */
const MINUS = '−'

function incrementDigits(digits: string): string {
  const chars = digits.split('')
  for (let i = chars.length - 1; i >= 0; i -= 1) {
    if (chars[i] === '9') {
      chars[i] = '0'
    } else {
      chars[i] = String(Number(chars[i]) + 1)
      return chars.join('')
    }
  }
  return `1${chars.join('')}`
}

function group(integer: string): string {
  return integer.replace(/\B(?=(\d{3})+(?!\d))/g, ',')
}

/**
 * Round a decimal string half-up to `places`, ungrouped, with an ASCII minus.
 *
 * The sign is removed first, so incrementing rounds away from zero — which is
 * what half-up means for a negative figure.
 *
 * Separate from `formatDecimal` because an editable field needs the rounding
 * without the presentation: storage keeps NUMERIC(19,4) and a balance reads
 * back as `10000.0000`, which is four places of noise in a box someone is about
 * to retype. Grouping and a typographic minus belong in text, not in a value
 * that has to survive being parsed again.
 */
export function roundDecimal(value: string, places = 2): string {
  const negative = value.startsWith('-') || value.startsWith(MINUS)
  const magnitude = negative ? value.slice(1) : value

  const [rawInteger = '0', rawFraction = ''] = magnitude.split('.')
  let integer = rawInteger
  let fraction = rawFraction

  if (fraction.length > places) {
    const roundingDigit = fraction[places] ?? '0'
    let kept = fraction.slice(0, places)

    if (roundingDigit >= '5') {
      const combined = incrementDigits(`${integer}${kept}`)
      // A carry out of the integer part lengthens the string by one.
      const splitAt = combined.length - places
      integer = places === 0 ? combined : combined.slice(0, splitAt)
      kept = places === 0 ? '' : combined.slice(splitAt)
    }
    fraction = kept
  } else {
    fraction = fraction.padEnd(places, '0')
  }

  integer = integer.replace(/^0+(?=\d)/, '')
  const body = places === 0 ? integer : `${integer}.${fraction}`

  // Do not render "-0.00". A figure that rounds to nothing is nothing.
  if (negative && /^0*(\.0*)?$/.test(body)) return body
  return negative ? `-${body}` : body
}

/** As `roundDecimal`, grouped for reading — `−122,000.00`. */
export function formatDecimal(value: string, places = 2): string {
  const rounded = roundDecimal(value, places)
  const negative = rounded.startsWith('-')
  const magnitude = negative ? rounded.slice(1) : rounded

  const [integer = '0', fraction] = magnitude.split('.')
  const body = fraction === undefined ? group(integer) : `${group(integer)}.${fraction}`

  return negative ? `${MINUS}${body}` : body
}

/**
 * The figure alone, always two decimals, thousands separated.
 *
 * The currency code is not included, because it is set one size down at 50%
 * ink and rendered as a separate element — see the `Amount` component. Money
 * never appears as a bare number, but the two halves are styled differently.
 */
export function formatAmount(value: Money, places = 2): string {
  return formatDecimal(value.amount, places)
}

/** A signed percentage, for month-on-month change columns. */
export function formatPercent(value: string, places = 1): string {
  const formatted = formatDecimal(value, places)
  const positive = !formatted.startsWith(MINUS) && Number(value) > 0
  return `${positive ? '+' : ''}${formatted}%`
}

/**
 * Rise or Breach, by sign and by whether the balance is owed — in one place.
 *
 * A liability moving up is more debt, which is not a rise, so the colour
 * inverts on it: green means the month moved in your favour here exactly as it
 * does everywhere else. A movement of zero takes neither colour — nothing
 * moved, and painting that green reports a rise that did not happen.
 *
 * The test is on the string rather than on `Number(value)`: money carries no
 * arithmetic in the browser, and asking whether a figure is signed is not
 * arithmetic.
 *
 * An explicit `+` is accepted, because the FX trend serves its movements signed
 * both ways — and `+0.000000` has to reach the same answer as `0.000000` here,
 * or a rate that held would be painted as a rise.
 *
 * Shared because Month Close, Net Worth, Account detail and the FX trend all
 * colour the same kind of movement, and a screen that decided locally whether
 * zero is green made the same figure a different colour on the next page.
 */
export function movementClass(value: string | null, isLiability = false): string {
  if (!value || /^[+-]?0(\.0*)?$/.test(value)) return ''
  return value.startsWith('-') === isLiability ? 'money--rise' : 'money--breach'
}

// ---------------------------------------------------------------------------
// Input
// ---------------------------------------------------------------------------

/**
 * Parse what a person typed or pasted into an exact decimal string.
 *
 * Accepts `1,234.56`, `1234.56`, ` 1 234.56 `, a leading `+`, and either kind
 * of minus sign. Returns null for anything else — the caller renders a
 * field-level error rather than guessing.
 *
 * The result is a string all the way to the server. It is never a number.
 */
export function parseAmountInput(raw: string): string | null {
  const cleaned = raw.trim().replace(/[\s,]/g, '').replace(MINUS, '-').replace(/^\+/, '')
  if (cleaned === '') return null
  if (!/^-?\d*(\.\d*)?$/.test(cleaned)) return null
  if (!/\d/.test(cleaned)) return null

  const negative = cleaned.startsWith('-')
  const magnitude = negative ? cleaned.slice(1) : cleaned
  const [integer = '', fraction = ''] = magnitude.split('.')

  const normalised = `${integer === '' ? '0' : integer}.${fraction === '' ? '0' : fraction}`
  return negative ? `-${normalised}` : normalised
}

// ---------------------------------------------------------------------------
// Dates
// ---------------------------------------------------------------------------

// An abbreviated month is three letters, always. The platform's own idea of a
// short month is not: current CLDR data abbreviates September as `Sept` under
// `en-GB`, and leaves June and July unabbreviated altogether under `en-AU`, so
// a column sized for three characters is at the mercy of whichever ICU build
// the browser shipped with. The table is fixed here instead.
const MONTHS_SHORT = [
  'Jan',
  'Feb',
  'Mar',
  'Apr',
  'May',
  'Jun',
  'Jul',
  'Aug',
  'Sep',
  'Oct',
  'Nov',
  'Dec',
] as const

const MONTHS_LONG = [
  'January',
  'February',
  'March',
  'April',
  'May',
  'June',
  'July',
  'August',
  'September',
  'October',
  'November',
  'December',
] as const

/** `2026-08` or `2026-08-31` → `[2026, 8]`. */
function yearAndMonth(iso: string): [string, number] {
  const [year = '', month = ''] = iso.split('-')
  return [year, Number(month)]
}

/**
 * Format an ISO calendar date (`2026-08-13`) as `13 Aug 2026` — unambiguously.
 * The user operates across two date conventions, so day/month ordering is
 * sidestepped entirely rather than chosen between.
 *
 * Read off the string rather than through a `Date`. Financial dates carry no
 * time component and no offset (BR-24), so there is no midnight for a timezone
 * to shift them across, and none is invented here.
 */
export function formatDate(iso: string): string {
  const [year, month] = yearAndMonth(iso)
  const day = Number(iso.slice(8, 10))
  return `${day} ${MONTHS_SHORT[month - 1]} ${year}`
}

/** Format `2026-08` or `2026-08-31` as `Aug 2026`. */
export function formatMonth(iso: string): string {
  const [year, month] = yearAndMonth(iso)
  return `${MONTHS_SHORT[month - 1]} ${year}`
}

/** Format `2026-08` or `2026-08-31` as `August 2026`. */
export function formatMonthLong(iso: string): string {
  const [year, month] = yearAndMonth(iso)
  return `${MONTHS_LONG[month - 1]} ${year}`
}

/**
 * Format `2026-08` as `Aug 26` — for chart axis ticks, where two dozen of them
 * share one line and the century is never the thing in doubt.
 */
export function formatMonthShort(iso: string): string {
  const [year, month] = yearAndMonth(iso)
  return `${MONTHS_SHORT[month - 1]} ${year.slice(2)}`
}

/**
 * Format `2026-08-13` as `13 Aug` — for chart axis ticks on a daily series,
 * where two dozen of them share one line. The day is what such a series is
 * indexed by, and the range it sits in is stated in the header above the plot;
 * the hover box gives the full date.
 */
export function formatDayShort(iso: string): string {
  const [, month] = yearAndMonth(iso)
  return `${Number(iso.slice(8, 10))} ${MONTHS_SHORT[month - 1]}`
}

/** `2026-08` — the reporting month a date falls in. */
export function monthOf(iso: string): string {
  return iso.slice(0, 7)
}

/**
 * `2026-08-31` — the last calendar day of a month, whether that is the 28th,
 * 29th, 30th or 31st. Day 0 of the next month, in UTC for the same reason
 * `formatDate` parses in UTC: a financial date carries no time and no offset
 * (BR-24), so there is no local midnight to slip across.
 *
 * Takes `2026-08` or any ISO date inside the month, so a caller holding a full
 * date need not trim it first. Here rather than on a screen because three
 * screens ask the same question — the month-end boundary has one definition.
 */
export function monthEnd(iso: string): string {
  const [year, month] = iso.split('-').map(Number)
  return new Date(Date.UTC(year ?? 1970, month ?? 1, 0)).toISOString().slice(0, 10)
}
