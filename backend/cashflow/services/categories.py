"""The taxonomy — add, rename, deactivate.

The rule that matters is what *cannot* happen: a category used by any
transaction may be deactivated but never deleted (BR-22). Renaming restates its
label across all history and keeps no record of the former name, which is the
cheap and correct behaviour when the alternative is effective-dated labels on
every report.
"""

from __future__ import annotations

from django.db.models import Count, Q

from core.services.exceptions import BusinessRuleError, ConflictError, NotFoundError
from cashflow.models import Category, Direction


def get_category(pk: int) -> Category:
    category = Category.objects.filter(pk=pk).first()
    if category is None:
        raise NotFoundError("No such category.", code="category_not_found")
    return category


def taxonomy(include_inactive: bool = True) -> list[dict]:
    """The whole tree, in seeded order, with usage counts.

    Usage drives the UI: a child with no transactions offers Delete, and one
    that has been used offers Deactivate instead.
    """
    parents = (
        Category.objects.filter(parent__isnull=True)
        .order_by("direction", "position", "name")
        .prefetch_related("children")
    )

    counts = {
        row["pk"]: row["used"]
        for row in Category.objects.annotate(
            used=Count("transactions", filter=Q(transactions__deleted_at__isnull=True))
        ).values("pk", "used")
    }

    tree = []
    for parent in parents:
        children = [
            child
            for child in sorted(
                parent.children.all(), key=lambda c: (c.position, c.name)
            )
            if child.deleted_at is None and (include_inactive or child.is_active)
        ]
        tree.append(
            {
                "id": parent.pk,
                "name": parent.name,
                "direction": parent.direction,
                "is_active": parent.is_active,
                "children": [
                    {
                        "id": child.pk,
                        "name": child.name,
                        "direction": child.direction,
                        "is_active": child.is_active,
                        "used": counts.get(child.pk, 0),
                        "path": f"{parent.name} → {child.name}",
                    }
                    for child in children
                ],
            }
        )
    return tree


def add_child(parent_id: int, name: str) -> Category:
    parent = get_category(parent_id)
    if not parent.is_parent:
        raise BusinessRuleError(
            f"{parent.name} is itself a child category. The taxonomy is two "
            f"levels deep and no deeper.",
            code="category_depth",
            field="parent",
        )

    name = name.strip()
    if not name:
        raise BusinessRuleError("A category needs a name.", code="name_required", field="name")

    if parent.children.filter(name__iexact=name).exists():
        raise ConflictError(
            f"{parent.name} already has a category called {name}.",
            code="category_exists",
            field="name",
        )

    position = (parent.children.count() or 0) + 1
    return Category.objects.create(
        name=name, parent=parent, direction=parent.direction, position=position
    )


def add_parent(name: str, direction: str) -> Category:
    name = name.strip()
    if not name:
        raise BusinessRuleError("A category needs a name.", code="name_required", field="name")
    if direction not in Direction.values:
        raise BusinessRuleError(
            "A parent category is either Income or Expense.",
            code="invalid_direction",
            field="direction",
        )
    if Category.objects.filter(
        parent__isnull=True, direction=direction, name__iexact=name
    ).exists():
        raise ConflictError(
            f"A {direction} category called {name} already exists.",
            code="category_exists",
            field="name",
        )

    position = Category.objects.filter(parent__isnull=True, direction=direction).count() + 1
    return Category.objects.create(
        name=name, parent=None, direction=direction, position=position
    )


def rename(category: Category, name: str) -> Category:
    """Restates the label across all history. No record of the former name."""
    name = name.strip()
    if not name:
        raise BusinessRuleError("A category needs a name.", code="name_required", field="name")

    siblings = (
        Category.objects.filter(parent=category.parent)
        if category.parent_id
        else Category.objects.filter(parent__isnull=True, direction=category.direction)
    )
    if siblings.exclude(pk=category.pk).filter(name__iexact=name).exists():
        raise ConflictError(
            f"Another category is already called {name}.",
            code="category_exists",
            field="name",
        )

    category.name = name
    category.save(update_fields=["name", "updated_at"])
    return category


def set_active(category: Category, is_active: bool) -> Category:
    """Deactivating removes a category from entry and leaves history intact."""
    category.is_active = is_active
    category.save(update_fields=["is_active", "updated_at"])

    # Deactivating a parent takes its children with it: a child whose parent is
    # gone from the taxonomy is unreachable in the entry form anyway, and
    # leaving it selectable would be a rollup into nothing.
    if category.is_parent:
        category.children.update(is_active=is_active)

    return category


def delete(category: Category) -> None:
    """Permitted only while unused. The database refuses it too.

    Deactivation is the intended path, and the error says so — a user who is
    told "no" without being told what to do instead will try something worse.
    """
    if category.transactions.exists():
        raise BusinessRuleError(
            f"{category.name} has been used by "
            f"{category.transactions.count()} transaction"
            f"{'s' if category.transactions.count() != 1 else ''} and cannot be "
            f"deleted. Deactivate it instead: it leaves the entry form and its "
            f"history stays intact.",
            code="category_in_use",
        )
    if category.is_parent and category.children.exists():
        raise BusinessRuleError(
            f"{category.name} still has child categories.",
            code="category_has_children",
        )
    category.delete()
