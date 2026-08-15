"""The seeded taxonomy (BR-22), and the rule that a used category is never deleted.

**On the seed.** BR-22's table lists `Dividends` and `Realised Investment Gains`
under `Income → Gains`. They are not seeded here, on OI-06's recommendation,
because BR-15 states that dividends, distributions and realised gains on
holdings are recorded in the Investments module **only** and never appear in
cash flow. Seeding categories that must never be used invites exactly the
double-count BR-15 exists to prevent, and a category is one row to add back if
that judgement is wrong. `Interest` is retained: it attaches to a cash account,
which has no holding to attach a return to.

**On the trigger.** `on_delete=PROTECT` guards a hard delete, but deletes in
this system are soft — an UPDATE setting `deleted_at`. PROTECT never sees it. So
the rule §9.1 puts in the database is a trigger on that UPDATE, because
orphaning years of transactions is not a mistake worth being able to make from
the admin or from psql.
"""

from django.db import migrations

# Parent → children, in the order they should read.
TAXONOMY = {
    "Income": [
        ("Employment", ["Salary", "Bonus"]),
        # Interest alone. See the module docstring.
        ("Gains", ["Interest"]),
        ("Other", ["Gifts", "Refunds", "Miscellaneous"]),
    ],
    "Expense": [
        ("Housing", ["Rent", "Mortgage Payment", "Council Tax", "Maintenance"]),
        ("Utilities", ["Energy", "Water", "Internet", "Mobile"]),
        ("Subscriptions", ["Media", "Software", "Memberships"]),
        ("Food", ["Groceries", "Eating Out"]),
        ("Shopping", ["Clothing", "Household", "Electronics"]),
        ("Travel", ["Transport", "Holidays"]),
        ("Entertainment", ["Events", "Hobbies"]),
        ("Health", ["Medical", "Fitness", "Insurance"]),
        ("Other", ["Miscellaneous"]),
    ],
}


def seed(apps, schema_editor):
    Category = apps.get_model("cashflow", "Category")

    # Idempotent: a re-run after a partial failure must not duplicate.
    if Category.objects.exists():
        return

    for direction, parents in TAXONOMY.items():
        for parent_position, (parent_name, children) in enumerate(parents):
            parent = Category.objects.create(
                name=parent_name,
                parent=None,
                direction=direction,
                position=parent_position,
            )
            for child_position, child_name in enumerate(children):
                Category.objects.create(
                    name=child_name,
                    parent=parent,
                    direction=direction,
                    position=child_position,
                )


def unseed(apps, schema_editor):
    Category = apps.get_model("cashflow", "Category")
    Category.objects.filter(transactions__isnull=True).delete()


FORWARD_TRIGGER = """
CREATE OR REPLACE FUNCTION cashflow_category_not_deletable_once_used()
RETURNS trigger AS $$
BEGIN
    IF OLD.deleted_at IS NULL AND NEW.deleted_at IS NOT NULL THEN
        IF EXISTS (
            SELECT 1 FROM cashflow_transaction
            WHERE category_id = OLD.id AND deleted_at IS NULL
        ) THEN
            RAISE EXCEPTION
                'Category % has been used by transactions and cannot be deleted (BR-22). Deactivate it instead: it leaves entry and its history stays intact.',
                OLD.name
                USING ERRCODE = 'check_violation';
        END IF;
        IF EXISTS (
            SELECT 1 FROM cashflow_category
            WHERE parent_id = OLD.id AND deleted_at IS NULL
        ) THEN
            RAISE EXCEPTION
                'Category % still has child categories and cannot be deleted (BR-22).',
                OLD.name
                USING ERRCODE = 'check_violation';
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER cashflow_category_delete_guard
    BEFORE UPDATE ON cashflow_category
    FOR EACH ROW
    EXECUTE FUNCTION cashflow_category_not_deletable_once_used();
"""

REVERSE_TRIGGER = """
DROP TRIGGER IF EXISTS cashflow_category_delete_guard ON cashflow_category;
DROP FUNCTION IF EXISTS cashflow_category_not_deletable_once_used();
"""


class Migration(migrations.Migration):
    dependencies = [("cashflow", "0001_initial")]

    operations = [
        migrations.RunPython(seed, unseed),
        migrations.RunSQL(sql=FORWARD_TRIGGER, reverse_sql=REVERSE_TRIGGER),
    ]
