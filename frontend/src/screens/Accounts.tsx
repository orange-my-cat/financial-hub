/**
 * Accounts — create, edit, close, set dormant.
 *
 * One rule is visible in the table itself rather than explained in copy:
 * **Delete is offered only for accounts with no history** (ADR-14). Every
 * other row offers Close, which preserves the history and excludes the
 * account from later months.
 *
 * **Edit opens the whole row**: the name, the classification, the opening month,
 * and the currency while BR-08 still allows it. Free text saves on blur; a
 * select and the month picker save on change, because their value is only ever
 * complete. The name and the opening month restate nothing and carry no
 * advisory; the classification says how many months move. They are one request
 * each and different kinds of act, which is why the advisory belongs to one of
 * them and not the others.
 *
 * The opening month is refused if it would move later than the earliest month
 * the account has a balance in, or later than its closing month — the mirror of
 * the rule that will not record a balance before an account opened. Closed is
 * not editable beside it: it is a consequence of closing, cleared by reopening
 * rather than retyped.
 *
 * Currency is locked once balances exist (BR-08). The control is offered only
 * while the choice is still open and the figure is plain text afterwards — the
 * API refuses the change either way, and a control that is always rejected is
 * worse than no control at all.
 *
 * Every account is listed in the currency it is held in, and nothing on this
 * screen or the account detail beneath it is translated. The reporting-currency
 * toggle therefore does not apply, and the subhead says so.
 *
 * Reclassification restates history, and the advisory says how many months
 * move. Both actions save — it is an advisory, not a confirmation dialogue,
 * because confirmation dialogues are dismissed reflexively. Close acts on the
 * same principle: it closes in the current month without asking, and a
 * refusal from the service appears under the row.
 */

import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";

import { AdvisoryList, ErrorBanner } from "@/components/Advisories";
import { ApiError, type Advisory } from "@/lib/api";
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
  type AccountStatus,
} from "@/lib/accounts";
import { useDefaultCurrency } from "@/lib/fx";
import { CURRENCIES, type CurrencyCode } from "@/lib/money";
import { icons } from "@/shell/icons";

function thisMonth(): string {
  return new Date().toISOString().slice(0, 7);
}

// ---------------------------------------------------------------------------

function NewAccountForm() {
  const create = useCreateAccount();
  // The default currency seeds the field; it never revises it. Once the form is
  // open the value is the user's, and a settings change behind it must not
  // reach in and alter what is about to be submitted.
  const defaultCurrency = useDefaultCurrency();
  const [form, setForm] = useState({
    name: "",
    account_type: ACCOUNT_TYPES[0] as string,
    liquidity_tier: LIQUIDITY_TIERS[0] as string,
    currency: defaultCurrency as string,
    opened_month: thisMonth(),
  });

  const fieldError = (name: string) =>
    create.error instanceof ApiError
      ? create.error.fieldError(name)
      : undefined;

  function submit(event: FormEvent) {
    event.preventDefault();
    create.mutate(form, { onSuccess: () => setForm({ ...form, name: "" }) });
  }

  return (
    <section className="panel">
      <h2 className="panel__heading">Add an Account</h2>
      <ErrorBanner error={create.error} />

      <form className="accounts__form" onSubmit={submit}>
        <div className="field">
          <label className="field__label" htmlFor="acc-name">
            Name
          </label>
          <input
            id="acc-name"
            className={`input${fieldError("name") ? " input--error" : ""}`}
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
            onChange={(event) =>
              setForm({ ...form, account_type: event.target.value })
            }
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
            Liquidity Tier
          </label>
          <select
            id="acc-tier"
            className="input"
            value={form.liquidity_tier}
            onChange={(event) =>
              setForm({ ...form, liquidity_tier: event.target.value })
            }
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
            onChange={(event) =>
              setForm({ ...form, currency: event.target.value })
            }
          >
            {CURRENCIES.map((code) => (
              <option key={code} value={code}>
                {code}
              </option>
            ))}
          </select>
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
            onChange={(event) =>
              setForm({ ...form, opened_month: event.target.value })
            }
          />
        </div>

        <button
          type="submit"
          className="btn btn--primary accounts__submit"
          disabled={create.isPending}
        >
          {create.isPending ? "Adding…" : "Add Account"}
        </button>
      </form>
    </section>
  );
}

// ---------------------------------------------------------------------------

function AccountRow({
  account,
  onAdvisories,
}: {
  readonly account: Account;
  readonly onAdvisories: (advisories: readonly Advisory[]) => void;
}) {
  const update = useUpdateAccount();
  const closeAccount = useCloseAccount();
  const dormant = useSetDormant();
  const reopen = useReopenAccount();
  const remove = useDeleteAccount();
  const [editing, setEditing] = useState(false);

  function reclassify(field: "account_type" | "liquidity_tier", value: string) {
    update.mutate(
      { id: account.id, [field]: value },
      { onSuccess: (response) => onAdvisories(response.advisories) },
    );
  }

  /**
   * Renaming and reclassifying are the same call and not the same act.
   *
   * A reclassification restates history and says how many months move; a rename
   * changes a label and restates nothing, so it carries no advisory and the
   * service keeps the two apart. Saved on blur rather than per keystroke,
   * because every figure in this system is computed on read and a request per
   * character would refetch the screen thirty times to rename an account.
   *
   * A field that was not changed sends nothing: an idle blur is not an edit.
   */
  function rename(value: string) {
    const named = value.trim();
    if (named === "" || named === account.name) return;
    update.mutate({ id: account.id, name: named });
  }

  /**
   * The opening month, saved the moment a whole one is picked.
   *
   * On change rather than on blur, unlike the name: a month input's value is
   * either empty or a complete month, so there is no half-typed state to guard
   * against — and a picker the user closes without leaving the cell would
   * otherwise look as though it had done nothing.
   *
   * The service refuses a month later than the earliest recorded balance, and
   * later than the closing month. Both refusals appear under the row.
   */
  function reopenMonth(value: string) {
    if (value === "" || value === account.opened_month) return;
    update.mutate({ id: account.id, opened_month: value });
  }

  // None of these actions asks first, so a refusal has to be visible: it is the
  // only thing distinguishing a rejected click from one that did nothing.
  const error =
    closeAccount.error ??
    dormant.error ??
    reopen.error ??
    remove.error ??
    update.error;

  return (
    <>
      <tr>
        <td>
          {editing ? (
            <input
              className="input input--grid input--cell"
              defaultValue={account.name}
              aria-label="Account name"
              onBlur={(event) => rename(event.target.value)}
            />
          ) : (
            <Link to={`/accounts/${account.id}`}>{account.name}</Link>
          )}
        </td>
        <td className="secondary">
          {editing ? (
            <select
              className="input input--grid input--cell"
              value={account.account_type}
              aria-label="Account type"
              onChange={(event) =>
                reclassify("account_type", event.target.value)
              }
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
              className="input input--grid input--cell"
              value={account.liquidity_tier}
              aria-label="Liquidity tier"
              onChange={(event) =>
                reclassify("liquidity_tier", event.target.value)
              }
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
        {/* BR-08: fixed once balances exist. Offered while it is still the
            user's to choose and static text after — the API refuses the change
            either way, and an editable control that is always rejected is worse
            than no control. */}
        <td className="mono">
          {editing && !account.currency_locked ? (
            <select
              className="input input--grid input--cell"
              value={account.currency}
              aria-label="Currency"
              onChange={(event) =>
                update.mutate({
                  id: account.id,
                  currency: event.target.value as CurrencyCode,
                })
              }
            >
              {CURRENCIES.map((code) => (
                <option key={code} value={code}>
                  {code}
                </option>
              ))}
            </select>
          ) : (
            account.currency
          )}
        </td>
        {/* Editable, unlike Closed beside it: an opening month can be typed
            wrong, whereas a closing month is a consequence of closing the
            account and is cleared by reopening it rather than retyped. */}
        <td className="secondary mono">
          {editing ? (
            <input
              type="month"
              className="input input--grid input--cell mono"
              value={account.opened_month}
              aria-label="Opened month"
              onChange={(event) => reopenMonth(event.target.value)}
            />
          ) : (
            account.opened_month
          )}
        </td>
        <td className="secondary mono">{account.closed_month ?? "—"}</td>
        <td className="accounts__actions">
          <div className="accounts__actions-set">
            {/* Called Edit rather than Reclassify: it now opens the name, the
              opening month and, where BR-08 still permits it, the currency —
              and reclassifying is only one of the things it does. */}
            <button
              type="button"
              className="link-button"
              onClick={() => setEditing(!editing)}
            >
              {editing ? "Done" : "Edit"}
            </button>

            {account.status === "Closed" ? (
              <button
                type="button"
                className="link-button"
                onClick={() => reopen.mutate(account.id)}
              >
                Reopen
              </button>
            ) : (
              <>
                {/* Dormancy and closure are both undone by reopen — it returns the
                  account to Open, and the closing month it clears is already
                  null here. Called Reactivate because a dormant account was
                  never shut. */}
                {account.status === "Dormant" ? (
                  <button
                    type="button"
                    className="link-button"
                    onClick={() => reopen.mutate(account.id)}
                  >
                    Reactivate
                  </button>
                ) : (
                  account.has_history && (
                    <button
                      type="button"
                      className="link-button"
                      onClick={() => dormant.mutate(account.id)}
                    >
                      Dormant
                    </button>
                  )
                )}
                {/* Closes in the current month. The service refuses if a later
                  balance exists, and that refusal is the row's error. */}
                <button
                  type="button"
                  className="link-button"
                  onClick={() =>
                    closeAccount.mutate({
                      id: account.id,
                      closed_month: thisMonth(),
                    })
                  }
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
          </div>
        </td>
      </tr>

      {error !== null && (
        <tr className="table__message-row">
          <td colSpan={7}>
            <ErrorBanner error={error} />
          </td>
        </tr>
      )}
    </>
  );
}

// ---------------------------------------------------------------------------

/**
 * One panel per status, in lifecycle order, and an empty group renders nothing
 * at all. Closed accounts are the exception to that silence: they are hidden
 * behind a toggle rather than absent, because a closed account still exists
 * and the screen has to admit where it went.
 */
const GROUPS = [
  { status: "Open", heading: "Active Accounts" },
  { status: "Dormant", heading: "Dormant Accounts" },
] as const satisfies readonly { status: AccountStatus; heading: string }[];

/**
 * Three tables stacked down the page only read as one register if their
 * columns line up, and separate tables under auto layout each size to their
 * own content. `.table--fixed` plus this shared colgroup pins the geometry, so
 * the three panels share a single set of column edges.
 */
function AccountColumns() {
  return (
    <colgroup>
      {/* The name takes the width, because it is the only column here with no
          fixed vocabulary and no bound on its length — and it is the one the
          edit row puts a free-text field in. Opened is wider than Closed for
          the same reason: it carries a month picker, and Closed carries a
          month or an em dash. */}
      <col style={{ width: "25%" }} />
      <col style={{ width: "15%" }} />
      <col style={{ width: "12%" }} />
      <col style={{ width: "7%" }} />
      <col style={{ width: "11%" }} />
      <col style={{ width: "7%" }} />
      <col style={{ width: "23%" }} />
    </colgroup>
  );
}

function AccountTable({
  heading,
  accounts,
  onAdvisories,
}: {
  readonly heading: string;
  readonly accounts: readonly Account[];
  readonly onAdvisories: (advisories: readonly Advisory[]) => void;
}) {
  // An empty group is not a fact worth a panel of its own.
  if (accounts.length === 0) return null;

  return (
    <section className="panel">
      <h2 className="panel__heading">{heading}</h2>

      <table className="table table--fixed">
        <AccountColumns />
        <thead>
          <tr>
            <th>Account</th>
            <th>Type</th>
            <th>Liquidity Tier</th>
            <th>Currency</th>
            <th>Opened</th>
            <th>Closed</th>
            <th aria-label="Actions" />
          </tr>
        </thead>
        <tbody>
          {accounts.map((account) => (
            <AccountRow
              key={account.id}
              account={account}
              onAdvisories={onAdvisories}
            />
          ))}
        </tbody>
      </table>
    </section>
  );
}

// ---------------------------------------------------------------------------

export function Accounts() {
  const accounts = useAccounts();
  const [advisories, setAdvisories] = useState<readonly Advisory[]>([]);
  const [showClosed, setShowClosed] = useState(false);

  if (accounts.isPending) return <div className="boot">Loading…</div>;
  if (!accounts.data) return <ErrorBanner error={accounts.error} />;

  const closed = accounts.data.filter((account) => account.status === "Closed");

  return (
    <div className="accounts">
      <NewAccountForm />

      {/* Above the table, naming how many months change. Both actions save. */}
      <AdvisoryList advisories={advisories} />

      {accounts.data.length === 0 ? (
        <section className="panel">
          <h2 className="panel__heading">Nothing Here Yet</h2>
          <p className="fx__note">
            The system starts empty and is never seeded. Add an account above,
            then close a month.
          </p>
        </section>
      ) : (
        GROUPS.map(({ status, heading }) => (
          <AccountTable
            key={status}
            heading={heading}
            accounts={accounts.data.filter(
              (account) => account.status === status,
            )}
            onAdvisories={setAdvisories}
          />
        ))
      )}

      {showClosed && (
        <AccountTable
          heading="Closed Accounts"
          accounts={closed}
          onAdvisories={setAdvisories}
        />
      )}

      {/* Silent when nothing is closed — an empty disclosure invites a click
          that reveals nothing. */}
      {closed.length > 0 && (
        <p className="accounts__disclosure">
          <button
            type="button"
            className="link-button accounts__disclosure-button"
            onClick={() => setShowClosed(!showClosed)}
          >
            {icons[showClosed ? "hide" : "show"]}
            {showClosed ? "Hide Closed Accounts" : "Show Closed Accounts"}
          </button>
        </p>
      )}
    </div>
  );
}
