/**
 * Money — an amount inseparable from its currency code, with no arithmetic.
 *
 * JavaScript has no decimal type. Any arithmetic on money in the browser is a
 * precision bug waiting for a large enough number, so this module defines the
 * shape and refuses to define the operations (ADR-02).
 *
 * `Money` is an object rather than a branded string on purpose. A branded
 * string still permits `a + b` — TypeScript reads it as concatenation and says
 * nothing. An object does not:
 *
 *     const total = balanceA + balanceB
 *     //            ~~~~~~~~~~~~~~~~~~~
 *     //  Operator '+' cannot be applied to types 'Money' and 'Money'.
 *
 * That compile error is the front-end half of ADR-02. There is deliberately no
 * `add`, no `subtract`, no `sum` and no `convert` in this file, and adding one
 * would be a defect regardless of how carefully it was written: every figure
 * this application displays was computed by the server, which is what makes it
 * impossible for a screen and an export to disagree (ADR-12).
 */

/**
 * The currencies a balance may be *denominated* in (OI-01), mirroring
 * `core.currencies.CURRENCY_CODES`. Stored and base currency is always USD.
 *
 * XAU is here because gold is a currency in this system rather than a price: a
 * Physical Asset account holds a balance of troy ounces, entered like any
 * other, and translated by the one translation service. A code missing from
 * this list makes `money()` throw on a perfectly valid API response, so this
 * list is not a menu — it is the set of codes the server can send.
 */
export const CURRENCIES = ['USD', 'AUD', 'MYR', 'XAU'] as const

export type CurrencyCode = (typeof CURRENCIES)[number]

/**
 * The currencies net worth may be *stated* in — a strict subset, since gold.
 *
 * A unit of account is not the same thing as a currency: "net worth, in
 * ounces" has a denominator that moves for reasons unrelated to the finances
 * being measured. The server is the authority (`can_report` on the currency
 * registry, which Settings reads); this list exists because the header toggle
 * renders before any query resolves.
 */
export const REPORTING_CURRENCIES = ['USD', 'AUD', 'MYR'] as const

export type ReportingCurrencyCode = (typeof REPORTING_CURRENCIES)[number]

/**
 * The stored and base currency, mirroring `core.currencies.BASE_CURRENCY`.
 *
 * Not the same thing as the user's default currency, which is a stored
 * preference and may be any reporting currency. This is the fallback beneath
 * that preference: the one currency that is stated without a rate.
 */
export const BASE_CURRENCY: ReportingCurrencyCode = 'USD'

export interface Money {
  /** The exact decimal, as the server computed it. Never parsed to a number. */
  readonly amount: string
  readonly currency: CurrencyCode
}

export function isCurrencyCode(value: unknown): value is CurrencyCode {
  return typeof value === 'string' && (CURRENCIES as readonly string[]).includes(value)
}

const DECIMAL = /^-?\d+(\.\d+)?$/

export function isMoney(value: unknown): value is Money {
  if (typeof value !== 'object' || value === null) return false
  const candidate = value as Record<string, unknown>
  return (
    typeof candidate.amount === 'string' &&
    DECIMAL.test(candidate.amount) &&
    isCurrencyCode(candidate.currency)
  )
}

/**
 * Read a money value off an API response.
 *
 * Throws rather than coercing. A malformed amount reaching a screen would be
 * rendered as something, and something is worse than nothing here.
 */
export function money(value: unknown): Money {
  if (!isMoney(value)) {
    throw new TypeError(
      `Expected { amount: string, currency: CurrencyCode }, received ${JSON.stringify(value)}. ` +
        'Money crosses the API as a string paired with a currency code, never as a JSON number.',
    )
  }
  return value
}

/** Whether the figure is below zero — read from the sign, not by comparison. */
export function isNegative(value: Money): boolean {
  return value.amount.startsWith('-')
}

export function isZero(value: Money): boolean {
  return /^-?0(\.0+)?$/.test(value.amount)
}

/**
 * Order two exact decimal strings — money, percentages, anything the server
 * sent as a decimal.
 *
 * Ordering is not arithmetic, and this file's refusal of the second does not
 * extend to the first: a comparison produces no new figure, only a position,
 * so there is nothing here for a float to round wrong. What would round it
 * wrong is the obvious alternative — `Number(a) - Number(b)` — which parses
 * both figures to floats to decide which is larger, and stops being reliable
 * at exactly the magnitudes this application is built to survive.
 *
 * Compared as digits instead: sign first, then the integer part by length and
 * then lexically, then the fraction padded to a common width. Every step is
 * exact at any size, and `-0.00` and `0` are the same figure.
 */
export function compareDecimals(a: string, b: string): number {
  const ZERO = /^-?0*(\.0*)?$/
  if (ZERO.test(a) && ZERO.test(b)) return 0

  const negativeA = a.startsWith('-')
  const negativeB = b.startsWith('-')
  if (negativeA !== negativeB) return negativeA ? -1 : 1

  const magnitude = compareMagnitudes(
    negativeA ? a.slice(1) : a,
    negativeB ? b.slice(1) : b,
  )
  // Below zero the order inverts: −900 is the larger magnitude and the smaller
  // figure.
  return negativeA ? -magnitude : magnitude
}

function compareMagnitudes(a: string, b: string): number {
  const [integerA = '0', fractionA = ''] = a.split('.')
  const [integerB = '0', fractionB = ''] = b.split('.')

  // Leading zeros stripped so length stands for magnitude, which is what makes
  // the lexical comparison below sound.
  const wholeA = integerA.replace(/^0+(?=\d)/, '')
  const wholeB = integerB.replace(/^0+(?=\d)/, '')
  if (wholeA.length !== wholeB.length) return wholeA.length < wholeB.length ? -1 : 1
  if (wholeA !== wholeB) return wholeA < wholeB ? -1 : 1

  const width = Math.max(fractionA.length, fractionB.length)
  const paddedA = fractionA.padEnd(width, '0')
  const paddedB = fractionB.padEnd(width, '0')
  if (paddedA === paddedB) return 0
  return paddedA < paddedB ? -1 : 1
}
