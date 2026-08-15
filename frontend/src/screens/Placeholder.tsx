/**
 * Every route other than Login, until its stage arrives.
 *
 * The placeholder names the stage rather than saying "coming soon", because the
 * build order is the plan and each stage exists so the next one can be tested.
 * Building a screen ahead of its stage is not enthusiasm; it is building on
 * arithmetic that has not been proven yet.
 */

interface PlaceholderProps {
  readonly title: string
  readonly stage: string
  readonly note: string
}

export function Placeholder({ title, stage, note }: PlaceholderProps) {
  return (
    <section className="placeholder">
      <h2 className="placeholder__title">{title}</h2>
      <span className="label">{stage}</span>
      <p className="placeholder__note">{note}</p>
    </section>
  )
}

export const SCREENS: Record<string, { title: string; stage: string; note: string }> = {
  dashboard: {
    title: 'Dashboard',
    stage: 'Stage 5',
    note:
      'Built last, deliberately: it is the most expensive screen and the most likely to be ' +
      'rebuilt once real use reveals what is actually looked at. Net worth summary and ' +
      '24-month trend, outstanding tasks, cash flow and investment summaries by currency, ' +
      'and the backup status strip.',
  },
  netWorth: {
    title: 'Net worth',
    stage: 'Stage 2',
    note:
      'The landing report. Total, month-on-month change, a 24-month trend, and slice toggles ' +
      'by account type, liquidity tier, currency and account. Toggling is the whole interaction ' +
      'model — there is no drill-down.',
  },
  accounts: {
    title: 'Accounts',
    stage: 'Stage 2',
    note:
      'Create, edit, close and set dormant. Currency locks once balances exist. Delete is ' +
      'offered only for accounts with no history; every other row offers Close.',
  },
  monthClose: {
    title: 'Month Close',
    stage: 'Stage 2',
    note:
      'The screen this system lives or dies on. Rates first so the whole pass runs in one tab ' +
      'order, then twenty balance rows with the prior month immediately left of each input. ' +
      'Autosaves on blur. There is deliberately no save button.',
  },
  cashFlow: {
    title: 'Cash flow',
    stage: 'Stage 3',
    note:
      'Three tabs: Entry, Category report, Categories. Moving money between your own accounts ' +
      'is not a transaction and has no record here — it shows only as two balance changes at ' +
      'the next close.',
  },
  investments: {
    title: 'Investments',
    stage: 'Stage 4',
    note:
      'Holdings, the open-lot FIFO queue, buy and sell entry, and realised gains grouped by ' +
      'currency. Unrealised gain does not exist in this system, and estimated tax is a ' +
      'user-typed percentage rather than a calculation.',
  },
  fxRates: {
    title: 'FX rates',
    stage: 'Stage 1',
    note:
      'The first screen built, because net worth cannot be tested without translation. Bulk ' +
      'entry for a date, the daily rate table with provenance per rate, the missing-and-stale ' +
      'summary, and a trend chart per pair.',
  },
  settings: {
    title: 'Settings',
    stage: 'Stage 1',
    note:
      'Default reporting currency, timezone, rate staleness threshold, password change, and a ' +
      'backup status readout. Backups are taken outside the application; there is nothing to ' +
      'run or restore from here.',
  },
}
