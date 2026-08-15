/**
 * Advisories and errors — structurally different, not differently worded.
 *
 * An advisory sits beside the thing it concerns, keeps every action live, and
 * never blocks. Its data was saved, and the copy says so. An error blocks and
 * states that nothing was saved.
 */

import type { Advisory } from '@/lib/api'
import { ApiError } from '@/lib/api'

const ADVISORY_LABEL: Record<Advisory['kind'], string> = {
  probable_duplicate: 'Probable duplicate',
  rate_variance: 'Rate variance',
  historic_restatement: 'Historic restatement',
}

export function AdvisoryList({ advisories }: { readonly advisories: readonly Advisory[] }) {
  if (advisories.length === 0) return null

  return (
    <div className="advisories">
      {advisories.map((advisory, index) => (
        <div className="advisory" key={`${advisory.kind}-${index}`} role="status">
          <span className="advisory__label">
            Advisory · {ADVISORY_LABEL[advisory.kind] ?? advisory.kind}
          </span>
          <span className="advisory__body">{advisory.message}</span>
        </div>
      ))}
    </div>
  )
}

export function ErrorBanner({ error }: { readonly error: unknown }) {
  if (!(error instanceof ApiError)) return null

  const messages =
    error.nonFieldMessages.length > 0 ? error.nonFieldMessages : [error.message]

  return (
    <div className="error-banner" role="alert">
      <span className="error-banner__label">Error</span>
      {messages.map((message) => (
        <span key={message} className="error-banner__body">
          {message}
        </span>
      ))}
      <span className="error-banner__body">Nothing was saved.</span>
    </div>
  )
}
