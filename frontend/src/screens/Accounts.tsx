/**
 * Accounts — create, edit, close, set dormant.
 *
 * Two rules are visible in the table itself rather than explained in copy:
 *
 *   * **Currency is locked once balances exist** (BR-08), marked with a
 *     superscript L beside the code. Correcting a mistake means a new account.
 *   * **Delete is offered only for accounts with no history** (ADR-14). Every
 *     other row offers Close, which preserves the history and excludes the
 *     account from later months.
 *
 * Reclassification restates history, and the advisory says how many months
 * move. Both actions save — it is an advisory, not a confirmation dialogue,
 * because confirmation dialogues are dismissed reflexively.
 */

import { useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'

import { AdvisoryList, ErrorBanner } from '@/components/Advisories'
import { ApiError, type Advisory } from '@/lib/api'
import {
  ACCOUNT_TYPES,
  LIQUIDITY_TIERS,
  useAccounts,
  useCloseAccount,
  useCreateAccount,
  useDeleteAccount,
  useReopenAccount,
  useSetDormant,
  useUpdateAccount,
  type Account,
} from '@/lib/accounts'
import { CURRENCIES } from '@/lib/money'

function thisMonth(): string {
  return new Date().toISOString().slice(0, 7)
}

// ---------------------------------------------------------------------------

function NewAccountForm() {
  const create = useCreateAccount()
  const [form, setForm] = useState({
    name: '',
    account_type: ACCOUNT_TYPES[0] as string,
    liquidity_tier: LIQUIDITY_TIERS[0] as string,
    currency: 'USD',
    opened_month: thisMonth(),
  })

  const fieldError = (name: string) =>
    create.error instanceof ApiError ? create.error.fieldError(name) : undefined

  function submit(event: FormEvent) {
    event.preventDefault()
    create.mutate(form, { onSuccess: () => setForm({ ...form, name: '' }) })
  }

  return (
    <section className="panel">
      <h2 className="panel__heading">Add an account</h2>
      <ErrorBanner error={create.error} />

      <form className="accounts__form" onSubmit={submit}>
        <div className="field">
          <label className="field__label" htmlFor="acc-name">
            Name
          </label>
          <input
            id="acc-name"
            className={`input${fieldError('name') ? ' input--error' : ''}`}
            value={form.name}
            onChange={(event) => setForm({ ...form, name: event.target.value })}
            required
          />
        </div>

        <div className="field">
          <label className="field__label" htmlFor="acc-type">
            Type
          </label>
          <select
            id="acc-type"
            className="input"
            value={form.account_type}
            onChange={(event) => setForm({ ...form, account_type: event.target.value })}
          >
            {ACCOUNT_TYPES.map((type) => (
              <option key={type} value={type}>
                {type}
              </option>
            ))}
          </select>
        </div>

        <div className="field">
          <label className="field__label" htmlFor="acc-tier">
            Liquidity tier
          </label>
          <select
            id="acc-tier"
            className="input"
            value={form.liquidity_tier}
            onChange={(event) => setForm({ ...form, liquidity_tier: event.target.value })}
          >
            {LIQUIDITY_TIERS.map((tier) => (
              <option key={tier} value={tier}>
                {tier}
              </option>
            ))}
          </select>
        </div>

        <div className="field">
          <label className="field__label" htmlFor="acc-currency">
            Currency
          </label>
          <select
            id="acc-currency"
            className="input mono"
            value={form.currency}
            onChange={(event) => setForm({ ...form, currency: event.target.value })}
          >
            {CURRENCIES.map((code) => (
              <option key={code} value={code}>
                {code}
              </option>
            ))}
          </select>
          <span className="fx__note">Fixed once a balance exists.</span>
        </div>

        <div className="field">
          <label className="field__label" htmlFor="acc-opened">
            Opened
          </label>
          <input
            id="acc-opened"
            type="month"
            className="input mono"
            value={form.opened_month}
            onChange={(event) => setForm({ ...form, opened_month: event.target.value })}
          />
        </div>

        <button type="submit" className="btn btn--primary" disabled={create.isPending}>
          {create.isPending ? 'Adding…' : 'Add account'}
        </button>
      </form>
    </section>
  )
}

// ---------------------------------------------------------------------------

function AccountRow({
  account,
  onAdvisories,
}: {
  readonly account: Account
  readonly onAdvisories: (advisories: readonly Advisory[]) => void
}) {
  const update = useUpdateAccount()
  const closeAccount = useCloseAccount()
  const dormant = useSetDormant()
  const reopen = useReopenAccount()
  const remove = useDeleteAccount()
  const [editing, setEditing] = useState(false)

  function reclassify(field: 'account_type' | 'liquidity_tier', value: string) {
    update.mutate(
      { id: account.id, [field]: value },
      { onSuccess: (response) => onAdvisories(response.advisories) },
    )
  }

  return (
    <tr>
      <td>
        <Link to={`/accounts/${account.id}`}>{account.name}</Link>
      </td>
      <td className="secondary">
        {editing ? (
          <select
            className="input input--grid"
            value={account.account_type}
            onChange={(event) => reclassify('account_type', event.target.value)}
          >
            {ACCOUNT_TYPES.map((type) => (
              <option key={type} value={type}>
                {type}
              </option>
            ))}
          </select>
        ) : (
          account.account_type
        )}
      </td>
      <td className="secondary">
        {editing ? (
          <select
            className="input input--grid"
            value={account.liquidity_tier}
            onChange={(event) => reclassify('liquidity_tier', event.target.value)}
          >
            {LIQUIDITY_TIERS.map((tier) => (
              <option key={tier} value={tier}>
                {tier}
              </option>
            ))}
          </select>
        ) : (
          account.liquidity_tier
        )}
      </td>
      <td className="secondary">{account.status}</td>
      <td className="mono">
        {account.currency}
        {/* Locked once balances exist. */}
        {account.currency_locked && (
          <sup className="mark mark--locked" title="Locked — balances exist">
            L
          </sup>
        )}
      </td>
      <td className="secondary mono">{account.opened_month}</td>
      <td className="secondary mono">{account.closed_month ?? '—'}</td>
      <td className="accounts__actions">
        <button type="button" className="link-button" onClick={() => setEditing(!editing)}>
          {editing ? 'Done' : 'Reclassify'}
        </button>

        {account.status === 'Closed' ? (
          <button type="button" className="link-button" onClick={() => reopen.mutate(account.id)}>
            Reopen
          </button>
        ) : (
          <>
            {account.has_history && account.status !== 'Dormant' && (
              <button
                type="button"
                className="link-button"
                onClick={() => dormant.mutate(account.id)}
              >
                Dormant
              </button>
            )}
            <button
              type="button"
              className="link-button"
              onClick={() => {
                const month = window.prompt('Close in which month? (YYYY-MM)', thisMonth())
                if (month) closeAccount.mutate({ id: account.id, closed_month: month })
              }}
            >
              Close
            </button>
          </>
        )}

        {/* Only for accounts with no history. Everything else is closed. */}
        {!account.has_history && (
          <button
            type="button"
            className="link-button link-button--breach"
            onClick={() => remove.mutate(account.id)}
          >
            Delete
          </button>
        )}
      </td>
    </tr>
  )
}

// ---------------------------------------------------------------------------

export function Accounts() {
  const accounts = useAccounts()
  const [advisories, setAdvisories] = useState<readonly Advisory[]>([])

  if (accounts.isPending) return <div className="boot">Loading…</div>
  if (!accounts.data) return <ErrorBanner error={accounts.error} />

  return (
    <div className="accounts">
      <p className="screen__subhead">
        The date range does not apply. Balances are entered snapshots — this screen
        governs the accounts themselves, not their figures.
      </p>

      {/* Above the table, naming how many months change. Both actions save. */}
      <AdvisoryList advisories={advisories} />

      {accounts.data.length === 0 ? (
        <section className="panel">
          <h2 className="panel__heading">Nothing here yet</h2>
          <p className="fx__note">
            The system starts empty and is never seeded. Add an account below, then close
            a month.
          </p>
        </section>
      ) : (
        <section className="panel">
          <table className="table">
            <thead>
              <tr>
                <th>Account</th>
                <th>Type</th>
                <th>Liquidity tier</th>
                <th>Status</th>
                <th>Currency</th>
                <th>Opened</th>
                <th>Closed</th>
                <th aria-label="Actions" />
              </tr>
            </thead>
            <tbody>
              {accounts.data.map((account) => (
                <AccountRow
                  key={account.id}
                  account={account}
                  onAdvisories={setAdvisories}
                />
              ))}
            </tbody>
          </table>
        </section>
      )}

      <NewAccountForm />
    </div>
  )
}
