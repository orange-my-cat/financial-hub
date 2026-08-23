/**
 * The state treatments, as components.
 *
 * Each is non-negotiable and each has a visible consequence. Colour is semantic
 * only, and every coloured state also carries a glyph or a word — so meaning
 * survives without hue.
 */

import type { Provenance } from '@/lib/fx'

/**
 * Three values, visible on every rate. `exact` is unmarked: the common case
 * earns no ink.
 */
export function ProvenanceMark({ provenance }: { readonly provenance: Provenance }) {
  if (provenance === 'exact') return null

  const symbol = provenance === 'carried' ? 'c' : 't'
  const description = provenance === 'carried' ? 'carried forward' : 'triangulated through USD'

  return (
    <sup className={`mark mark--${provenance}`} title={description} aria-label={description}>
      {symbol}
    </sup>
  )
}

/**
 * What a translated figure left out, and why (FR-46, design handoff §4).
 *
 * Never a zero and never a silence: money withheld for want of a rate is named,
 * counted and explained, and the figures it would have joined are stated
 * without it.
 *
 * The count is not decoration. Cash flow translates one transaction at a time,
 * at the rate on its own date, so "excludes MYR" can mean a single row of a
 * month or every row of it — and those are different enough facts that a reader
 * has to be told which.
 */
export function ExclusionNotice({
  exclusions,
}: {
  readonly exclusions: readonly {
    readonly currency: string
    readonly count: number
    readonly reason: string
  }[]
}) {
  if (exclusions.length === 0) return null

  return (
    <p className="exclusion-notice">
      Excludes{' '}
      {exclusions
        .map((row) => `${row.count} ${row.currency} transaction${row.count === 1 ? '' : 's'}`)
        .join(', ')}{' '}
      — {exclusions.map((row) => row.reason).join('; ')}
    </p>
  )
}

export type GlyphState = 'Complete' | 'Incomplete' | 'Missing' | 'Outside Range'

/**
 * The 11px square that carries a state, so it reads without colour. The word is
 * the accessible name, so it reads without the glyph either.
 */
export function StateGlyph({ state }: { readonly state: GlyphState }) {
  const modifier = {
    Complete: 'complete',
    Incomplete: 'incomplete',
    Missing: 'missing',
    'Outside Range': 'outside',
  }[state]

  return <span className={`glyph glyph--${modifier}`} role="img" aria-label={state} />
}

/**
 * A rate, in its own market convention, with its provenance mark.
 *
 * Never a bare number: the pair travels with it, because `0.66` alone does not
 * say whether it is USD per AUD or the other way round.
 */
export function Rate({
  value,
  provenance = 'exact',
  stale = false,
}: {
  readonly value: string
  readonly provenance?: Provenance
  readonly stale?: boolean
}) {
  return (
    <span className={`money${stale ? ' rate--stale' : ''}`}>
      {value}
      <ProvenanceMark provenance={provenance} />
    </span>
  )
}
