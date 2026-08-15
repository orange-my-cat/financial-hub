"""Deletes are soft, everywhere (ADR-03).

There is no audit trail and no change history in this system, so soft delete is
the entire safety net under an accidental deletion. These tests assert the two
halves that matter: a deleted row is gone from every ordinary query, and it is
still there for the admin to bring back.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.django_db


def test_delete_marks_rather_than_removes(specimen):
    row = specimen.objects.create(name="a savings account")

    row.delete()

    assert specimen.objects.count() == 0, "deleted rows must vanish from the default manager"
    assert specimen.all_objects.count() == 1, "the row itself must still exist"
    assert specimen.all_objects.get(pk=row.pk).deleted_at is not None


def test_queryset_delete_is_also_soft(specimen):
    specimen.objects.create(name="one")
    specimen.objects.create(name="two")

    specimen.objects.all().delete()

    assert specimen.objects.count() == 0
    assert specimen.all_objects.count() == 2


def test_restore_returns_the_row_to_the_application(specimen):
    row = specimen.objects.create(name="deleted by accident")
    row.delete()

    specimen.all_objects.get(pk=row.pk).restore()

    assert specimen.objects.count() == 1
    assert specimen.objects.get(pk=row.pk).deleted_at is None


def test_queryset_restore(specimen):
    row = specimen.objects.create(name="x")
    row.delete()

    specimen.all_objects.dead().restore()

    assert specimen.objects.count() == 1


def test_hard_delete_genuinely_removes(specimen):
    """The one route to permanent removal — an account with no history (ADR-14)."""
    row = specimen.objects.create(name="created in error")

    row.hard_delete()

    assert specimen.all_objects.count() == 0


def test_queryset_hard_delete(specimen):
    specimen.objects.create(name="one")
    specimen.objects.create(name="two")

    specimen.all_objects.all().hard_delete()

    assert specimen.all_objects.count() == 0


def test_alive_and_dead_partition_the_table(specimen):
    kept = specimen.objects.create(name="kept")
    dropped = specimen.objects.create(name="dropped")
    dropped.delete()

    assert list(specimen.all_objects.alive()) == [kept]
    assert [row.pk for row in specimen.all_objects.dead()] == [dropped.pk]


def test_is_deleted_reflects_the_mark(specimen):
    row = specimen.objects.create(name="x")
    assert row.is_deleted is False

    row.delete()
    assert row.is_deleted is True


def test_timestamps_are_set(specimen):
    row = specimen.objects.create(name="x")

    assert row.created_at is not None
    assert row.updated_at is not None
    assert row.deleted_at is None


def test_base_manager_is_unfiltered(specimen):
    """Related-object traversal must not explode on a soft-deleted row.

    Django uses the base manager for that traversal, and a filtered base
    manager turns a deleted parent into a DoesNotExist raised from somewhere
    unrelated — which is why `base_manager_name` points at `all_objects`.
    """
    assert specimen._meta.base_manager.name == "all_objects"
    assert specimen._meta.default_manager_name in (None, "objects")

    row = specimen.objects.create(name="x")
    row.delete()
    assert specimen._meta.base_manager.filter(pk=row.pk).exists()
