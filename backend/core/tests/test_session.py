"""Authentication.

The posture is narrow and stated (§10.1): the password protects against another
person at the keyboard, not against anyone holding the machine. What these
tests assert is the part that is easy to get wrong — that a new endpoint is
protected by default rather than by remembering to protect it (§10.2).
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.django_db


def test_health_is_open_deliberately(client):
    """The one opened endpoint. It is what the image's HEALTHCHECK polls."""
    response = client.get("/api/health/")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_everything_else_is_closed_by_default(client):
    response = client.get("/api/me/")
    assert response.status_code == 403


def test_session_get_reports_anonymous_and_sets_the_csrf_cookie(client):
    response = client.get("/api/session/")

    assert response.status_code == 200
    assert response.json() == {"authenticated": False, "username": None}
    assert "csrftoken" in response.cookies


def test_login_opens_a_session(client, user):
    response = client.post(
        "/api/session/",
        data={"username": "owner", "password": "a-long-enough-password"},
        content_type="application/json",
    )

    assert response.status_code == 200
    assert response.json() == {"authenticated": True, "username": "owner"}
    assert client.get("/api/me/").json() == {"username": "owner"}


def test_wrong_password_is_refused_without_saying_which_half_was_wrong(client, user):
    response = client.post(
        "/api/session/",
        data={"username": "owner", "password": "not-the-password"},
        content_type="application/json",
    )

    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == "invalid_credentials"
    assert "username" not in error["message"].lower().replace("username and password", "")


def test_unknown_user_gives_the_same_answer_as_a_wrong_password(client, user):
    response = client.post(
        "/api/session/",
        data={"username": "someone-else", "password": "a-long-enough-password"},
        content_type="application/json",
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_credentials"


def test_logout_closes_the_session(client, user):
    client.force_login(user)

    response = client.delete("/api/session/")

    assert response.status_code == 204
    assert client.get("/api/me/").status_code == 403


def test_logout_when_not_logged_in_is_not_an_error(client):
    assert client.delete("/api/session/").status_code == 204


def test_session_get_reports_the_logged_in_user(client, user):
    client.force_login(user)

    assert client.get("/api/session/").json() == {
        "authenticated": True,
        "username": "owner",
    }


def test_session_lifetime_is_thirty_days_and_does_not_slide(settings):
    """A re-login prompt part-way through a monthly close is friction (ADR-16)."""
    assert settings.SESSION_COOKIE_AGE == 30 * 24 * 60 * 60
    assert settings.SESSION_SAVE_EVERY_REQUEST is False
    assert settings.SESSION_COOKIE_HTTPONLY is True
    assert settings.SESSION_COOKIE_SAMESITE == "Lax"
    # The front end must read this one to echo the token back as a header.
    assert settings.CSRF_COOKIE_HTTPONLY is False


def test_default_permission_class_is_authenticated(settings):
    assert settings.REST_FRAMEWORK["DEFAULT_PERMISSION_CLASSES"] == [
        "rest_framework.permissions.IsAuthenticated"
    ]


def test_decimals_serialise_as_strings(settings):
    """ADR-12. JSON.parse turns a number into a float; a string survives."""
    assert settings.REST_FRAMEWORK["COERCE_DECIMAL_TO_STRING"] is True
