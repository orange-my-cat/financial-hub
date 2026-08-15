"""Fixtures for the core suite.

The soft-delete base is abstract and there are no concrete models in this
system yet — Stage 1 brings the first. Rather than build a model ahead of its
stage merely to have something to test, the suite defines its own specimen and
creates its table directly in the test database.

The specimen is `managed = False`, so no migration is ever written for it and it
cannot reach a real database. It exists for the duration of a test run and
nowhere else.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.db import connection, models

from core.models import SoftDeleteModel


class SoftDeleteSpecimen(SoftDeleteModel):
    """A concrete `SoftDeleteModel`, for testing the base itself."""

    name = models.CharField(max_length=64)

    class Meta:
        app_label = "core"
        managed = False
        db_table = "core_softdeletespecimen"


@pytest.fixture(scope="session")
def specimen_table(django_db_setup, django_db_blocker):
    """Create the specimen's table once, for the whole session."""
    with django_db_blocker.unblock(), connection.schema_editor() as editor:
        editor.create_model(SoftDeleteSpecimen)
    yield SoftDeleteSpecimen


@pytest.fixture
def specimen(specimen_table, db):
    """The specimen model, with an empty table and the database available."""
    return specimen_table


@pytest.fixture
def user(db):
    """The single user. There is one account and no roles (§10.2)."""
    return get_user_model().objects.create_user(
        username="owner", password="a-long-enough-password"
    )
