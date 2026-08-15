"""Views are thin: authenticate, deserialise, call one service, serialise, return.

Stage 0 has no services to call yet, so these views are as thin as they will
ever be. The rule they establish is the one that matters later — no view in
this system computes anything (§5.2.2).
"""

from __future__ import annotations

import logging
from pathlib import Path

from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.http import Http404, HttpResponse
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from rest_framework import status as http
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.api.serializers import LoginSerializer
from core.services.exceptions import BusinessRuleError

logger = logging.getLogger("financial_hub")


class HealthView(APIView):
    """Liveness. The one endpoint deliberately opened (§10.2).

    It reports that the process is answering and nothing else. It does not
    touch the database on purpose: this is what compose's healthcheck polls,
    and a database blip should not restart an application that is otherwise
    perfectly able to explain the problem. Depth belongs to the smoke test,
    which is run by a person who wants an answer.
    """

    permission_classes = [AllowAny]
    authentication_classes: list = []

    def get(self, request):  # noqa: ARG002
        return Response({"status": "ok"})


@method_decorator(csrf_protect, name="dispatch")
class SessionView(APIView):
    """The session, as one resource.

    ``GET``     who is logged in, and set the CSRF cookie
    ``POST``    log in
    ``DELETE``  log out

    ``csrf_protect`` is applied explicitly. DRF's ``APIView`` is exempt from
    Django's CSRF middleware and ``SessionAuthentication`` only re-enforces the
    check once a session exists — which would leave the login POST itself, the
    one unauthenticated write in the system, unprotected.
    """

    permission_classes = [AllowAny]

    @method_decorator(ensure_csrf_cookie)
    def get(self, request):
        user = request.user
        return Response(
            {
                "authenticated": user.is_authenticated,
                "username": user.get_username() if user.is_authenticated else None,
            }
        )

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = authenticate(
            request,
            username=serializer.validated_data["username"],
            password=serializer.validated_data["password"],
        )
        if user is None:
            # One message for a bad username and a bad password alike. There is
            # one account; naming which half was wrong tells an attacker at the
            # keyboard something and tells the user nothing.
            raise BusinessRuleError(
                "That username and password do not match.",
                code="invalid_credentials",
            )

        login(request, user)
        logger.info("session opened for %s", user.get_username())
        return Response({"authenticated": True, "username": user.get_username()})

    def delete(self, request):
        if not request.user.is_authenticated:
            return Response(status=http.HTTP_204_NO_CONTENT)
        username = request.user.get_username()
        logout(request)
        logger.info("session closed for %s", username)
        return Response(status=http.HTTP_204_NO_CONTENT)


class WhoAmIView(APIView):
    """The canonical "am I still logged in" probe for a 30-day session."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response({"username": request.user.get_username()})


# ---------------------------------------------------------------------------
# The SPA entry point
# ---------------------------------------------------------------------------

_index_cache: bytes | None = None


def _index_html() -> bytes | None:
    """The built bundle's index.html, or None if there is no bundle.

    Cached outside DEBUG. In production the file cannot change without a new
    image, so re-reading it on every request would buy nothing.
    """
    global _index_cache
    if _index_cache is not None and not settings.DEBUG:
        return _index_cache

    for candidate in (
        Path(settings.STATIC_ROOT) / "index.html",
        Path(settings.FRONTEND_DIST) / "index.html",
    ):
        if candidate.is_file():
            content = candidate.read_bytes()
            _index_cache = content
            return content
    return None


def spa_index(request):  # noqa: ARG001
    """Serve the React application shell for every client-side route.

    In development this is not the path taken: the Vite dev server serves the
    application and proxies /api here, so the browser sees one origin and the
    session cookie behaves exactly as it will in production (BUILD_PLAN §2.3).
    """
    content = _index_html()
    if content is None:
        if settings.DEBUG:
            return HttpResponse(
                "<h1>No front end bundle</h1>"
                "<p>This is the Django development server on port 8001. The "
                "application is served by Vite &mdash; run <code>npm run dev</code> "
                "in <code>frontend/</code> and open that instead. Vite proxies "
                "<code>/api</code> back here.</p>",
                content_type="text/html",
                status=http.HTTP_501_NOT_IMPLEMENTED,
            )
        raise Http404("No front end bundle was built into this image.")
    return HttpResponse(content, content_type="text/html")
