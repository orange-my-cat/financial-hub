"""Business-rule failures, raised by services and rendered by the API layer.

These deliberately do not inherit from anything in DRF. Services must be
callable without HTTP (§5.2.2), which means they cannot know what a status code
is. The API layer translates; the service states what went wrong.

Every error carries a stable machine-readable code, because the front end
special-cases a handful of them where the explanation benefits from context —
a sale exceeding units held, a currency change on an account with balances, the
deletion of a referenced category (§8.3).
"""

from __future__ import annotations


class BusinessRuleError(Exception):
    """A rule was violated. The request is refused and nothing was saved.

    Errors block. Advisories never do — if the thing being reported should
    leave the data saved, it is an :class:`core.services.advisories.Advisory`
    and not this.
    """

    code = "business_rule_violated"

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        field: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code or type(self).code
        # When set, the API layer renders the error inline against this input
        # rather than as a banner (§8.3).
        self.field = field


class ConflictError(BusinessRuleError):
    """The request contradicts state that already exists.

    Distinguished from :class:`BusinessRuleError` only so the API layer can
    answer 409 rather than 400 — a duplicate balance for an account and month,
    a second rate for a pair and date.
    """

    code = "conflict"


class NotFoundError(BusinessRuleError):
    """The addressed thing does not exist, or has been soft-deleted."""

    code = "not_found"
