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

/** The currencies actually held (OI-01). Stored and base currency is always USD. */
export const CURRENCIES = ['USD', 'AUD', 'MYR'] as const

export type CurrencyCode = (typeof CURRENCIES)[number]

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
