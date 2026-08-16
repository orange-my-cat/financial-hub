# Renames the settings field only. The value is untouched, and nothing derived
# from it was ever stored, so there is no data to restate (BR-10, ADR-05).

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0001_initial'),
    ]

    operations = [
        migrations.RenameField(
            model_name='settings',
            old_name='reporting_currency',
            new_name='default_currency',
        ),
    ]
