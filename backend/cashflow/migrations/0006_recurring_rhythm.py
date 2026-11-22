"""Closed rhythms, so a recurring item's anchor can move forward only.

Additive: every existing template has run on one rhythm, its own, so there is
nothing to backfill. The table fills only as anchors are moved and ended items
restarted.
"""

import django.db.models.deletion
import django.db.models.manager
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('cashflow', '0005_recurring_anchor_date'),
    ]

    operations = [
        migrations.CreateModel(
            name='RecurringRhythm',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('deleted_at', models.DateTimeField(blank=True, db_index=True, default=None, null=True)),
                ('anchor_date', models.DateField()),
                ('frequency', models.CharField(choices=[('Weekly', 'Weekly'), ('Fortnightly', 'Fortnightly'), ('Monthly', 'Monthly')], max_length=12)),
                ('end_date', models.DateField()),
                ('template', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='rhythms', to='cashflow.recurringtemplate')),
            ],
            options={
                'ordering': ['anchor_date'],
                'constraints': [models.CheckConstraint(condition=models.Q(('end_date__gte', models.F('anchor_date'))), name='cashflow_rhythm_ends_after_it_starts')],
            },
            managers=[
                ('objects', django.db.models.manager.Manager()),
                ('all_objects', django.db.models.manager.Manager()),
            ],
        ),
    ]
