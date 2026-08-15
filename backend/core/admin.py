"""The break-glass admin.

This is a recovery tool, not an alternative interface (§10.3). Its single
justification is that ADR-03's soft delete needs a route back — a row deleted
by accident has to be reachable without writing SQL, and there is no audit
trail or change history in this system to reach it by any other means.

Any routine use of the admin indicates a missing feature.

:class:`SoftDeleteAdmin` is the base every model admin in this system uses. It
shows deleted rows — which the application itself never does — and offers
restore.
"""

from __future__ import annotations

from django.contrib import admin, messages
from django.utils.translation import ngettext

admin.site.site_header = "Financial Hub — recovery"
admin.site.site_title = "Financial Hub — recovery"
admin.site.index_title = (
    "Break-glass access to soft-deleted rows. Routine editing belongs in the "
    "application, where the business rules are."
)


# No models are registered yet — there are none. From Stage 1 onward each model
# registers with `@admin.register(Model)` and `SoftDeleteAdmin` as its base.


class SoftDeleteAdmin(admin.ModelAdmin):
    """Sees everything, including what the application has hidden."""

    readonly_fields = ("created_at", "updated_at", "deleted_at")
    actions = ("restore_selected",)

    def get_queryset(self, request):
        # `all_objects`, deliberately. The whole reason to be here is the rows
        # the application refuses to show.
        return self.model.all_objects.get_queryset()

    @admin.display(boolean=True, description="Deleted")
    def is_deleted(self, obj) -> bool:
        return obj.is_deleted

    @admin.action(description="Restore the selected rows")
    def restore_selected(self, request, queryset):
        restored = queryset.dead().restore()
        self.message_user(
            request,
            ngettext(
                "%d row restored and is visible in the application again.",
                "%d rows restored and are visible in the application again.",
                restored,
            )
            % restored,
            messages.SUCCESS,
        )
