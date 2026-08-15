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
