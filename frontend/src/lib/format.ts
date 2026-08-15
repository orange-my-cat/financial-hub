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
 * Round a decimal string half-up to `places`, and group the integer part.
 *
 * The sign is removed first, so incrementing rounds away from zero — which is
 * what half-up means for a negative figure.
 */
export function formatDecimal(value: string, places = 2): string {
  const negative = value.startsWith('-')
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
  const body = places === 0 ? group(integer) : `${group(integer)}.${fraction}`

  // Do not render "−0.00". A figure that rounds to nothing is nothing.
  if (negative && /^[0,]*(\.0*)?$/.test(body)) return body
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

// `13 Aug 2026`, unambiguously. The user operates across two date conventions,
// so day/month ordering is sidestepped entirely rather than chosen between.
const DAY_MONTH_YEAR = new Intl.DateTimeFormat('en-GB', {
  day: 'numeric',
  month: 'short',
  year: 'numeric',
  timeZone: 'UTC',
})

const MONTH_YEAR = new Intl.DateTimeFormat('en-GB', {
  month: 'short',
  year: 'numeric',
  timeZone: 'UTC',
})

/**
 * Format an ISO calendar date (`2026-08-13`) as `13 Aug 2026`.
 *
 * Parsed as UTC. Financial dates carry no time component and no offset
 * (BR-24), so there is no local midnight for a timezone to shift them across.
 */
export function formatDate(iso: string): string {
  return DAY_MONTH_YEAR.format(new Date(`${iso}T00:00:00Z`))
}

/** Format `2026-08` or `2026-08-31` as `Aug 2026`. */
export function formatMonth(iso: string): string {
  const [year, month] = iso.split('-')
  return MONTH_YEAR.format(new Date(`${year}-${month}-01T00:00:00Z`))
}

/** `2026-08` — the reporting month a date falls in. */
export function monthOf(iso: string): string {
  return iso.slice(0, 7)
}
