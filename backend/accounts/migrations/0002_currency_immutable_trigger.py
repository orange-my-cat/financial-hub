"""BR-08, enforced by the database.

An account's currency cannot change once balances exist. A check constraint
cannot express this — it depends on rows in another table — so it is a trigger.

The application also refuses the change, with a better message. This exists for
every other path into the data: the Django admin that ADR-03 requires be
available for recovering soft-deleted rows, a `psql` session, a future import.
A rule enforced only in application code is a rule that holds until the day
something writes around it (§9.1).

Deleted balances do not count. A soft-deleted balance is one the application
treats as never having existed, so it must not permanently freeze the currency
of an account whose entire history was removed.
"""

from django.db import migrations

FORWARD = """
CREATE OR REPLACE FUNCTION accounts_currency_is_immutable()
RETURNS trigger AS $$
BEGIN
    IF NEW.currency IS DISTINCT FROM OLD.currency THEN
        IF EXISTS (
            SELECT 1 FROM accounts_balance
            WHERE account_id = OLD.id AND deleted_at IS NULL
        ) THEN
            RAISE EXCEPTION
                'Account % holds balances; its currency cannot change from % to % (BR-08). Correcting a mistake requires a new account.',
                OLD.id, OLD.currency, NEW.currency
                USING ERRCODE = 'check_violation';
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER accounts_currency_immutable
    BEFORE UPDATE ON accounts_account
    FOR EACH ROW
    EXECUTE FUNCTION accounts_currency_is_immutable();
"""

REVERSE = """
DROP TRIGGER IF EXISTS accounts_currency_immutable ON accounts_account;
DROP FUNCTION IF EXISTS accounts_currency_is_immutable();
"""


class Migration(migrations.Migration):
    dependencies = [("accounts", "0001_initial")]

    operations = [migrations.RunSQL(sql=FORWARD, reverse_sql=REVERSE)]
