from __future__ import annotations

import json
import secrets
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from django.conf import settings
from django.http import HttpRequest
from django.urls import reverse


@dataclass(slots=True)
class GoogleOAuthResult:
    ok: bool
    code: str
    data: dict[str, Any] | None = None


class GoogleOAuthService:
    SESSION_STATE_KEY = "google_oauth_state"
    SESSION_NEXT_KEY = "google_oauth_next"
    SESSION_REDIRECT_URI_KEY = "google_oauth_redirect_uri"

    @classmethod
    def is_enabled(cls) -> bool:
        return bool(settings.GOOGLE_OAUTH_CLIENT_ID and settings.GOOGLE_OAUTH_CLIENT_SECRET)

    @classmethod
    def build_login_redirect(cls, request: HttpRequest, next_url: str = "") -> GoogleOAuthResult:
        if not cls.is_enabled():
            return GoogleOAuthResult(ok=False, code="oauth_not_configured")

        state = secrets.token_urlsafe(32)
        redirect_uri = request.build_absolute_uri(reverse("google_callback"))
        safe_next = next_url if (next_url or "").startswith("/") else ""
        request.session[cls.SESSION_STATE_KEY] = state
        request.session[cls.SESSION_NEXT_KEY] = safe_next
        request.session[cls.SESSION_REDIRECT_URI_KEY] = redirect_uri

        query = {
            "client_id": settings.GOOGLE_OAUTH_CLIENT_ID,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(settings.GOOGLE_OAUTH_SCOPES),
            "state": state,
            "access_type": "online",
            "include_granted_scopes": "true",
        }
        auth_url = f"{settings.GOOGLE_OAUTH_AUTH_URI}?{urlencode(query)}"
        return GoogleOAuthResult(ok=True, code="redirect_ready", data={"auth_url": auth_url})

    @classmethod
    def complete_login(cls, request: HttpRequest) -> GoogleOAuthResult:
        if not cls.is_enabled():
            return GoogleOAuthResult(ok=False, code="oauth_not_configured")

        returned_state = (request.GET.get("state") or "").strip()
        expected_state = request.session.pop(cls.SESSION_STATE_KEY, None)
        next_url = request.session.pop(cls.SESSION_NEXT_KEY, "")
        redirect_uri = request.session.pop(
            cls.SESSION_REDIRECT_URI_KEY,
            request.build_absolute_uri(reverse("google_callback")),
        )

        if not returned_state or not expected_state or returned_state != expected_state:
            return GoogleOAuthResult(ok=False, code="invalid_oauth_state")

        if request.GET.get("error"):
            return GoogleOAuthResult(ok=False, code="oauth_denied")

        code = (request.GET.get("code") or "").strip()
        if not code:
            return GoogleOAuthResult(ok=False, code="oauth_invalid_code")

        token_result = cls._exchange_code_for_token(code, redirect_uri)
        if not token_result.ok:
            return token_result

        access_token = token_result.data["access_token"]
        user_result = cls._fetch_userinfo(access_token)
        if not user_result.ok:
            return user_result

        email = (user_result.data.get("email") or "").strip().lower()
        if not email:
            return GoogleOAuthResult(ok=False, code="oauth_missing_email")

        return GoogleOAuthResult(
            ok=True,
            code="oauth_authenticated",
            data={
                "email": email,
                "next_url": next_url if (next_url or "").startswith("/") else "",
            },
        )

    @classmethod
    def _exchange_code_for_token(cls, code: str, redirect_uri: str) -> GoogleOAuthResult:
        payload = {
            "code": code,
            "client_id": settings.GOOGLE_OAUTH_CLIENT_ID,
            "client_secret": settings.GOOGLE_OAUTH_CLIENT_SECRET,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        }
        encoded = urlencode(payload).encode("utf-8")
        request = Request(
            settings.GOOGLE_OAUTH_TOKEN_URI,
            data=encoded,
            method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        try:
            with urlopen(request, timeout=8) as response:
                body = response.read().decode("utf-8")
        except (HTTPError, URLError, TimeoutError):
            return GoogleOAuthResult(ok=False, code="oauth_token_exchange_failed")

        try:
            parsed = json.loads(body)
        except json.JSONDecodeError:
            return GoogleOAuthResult(ok=False, code="oauth_invalid_response")

        access_token = (parsed.get("access_token") or "").strip()
        if not access_token:
            return GoogleOAuthResult(ok=False, code="oauth_missing_access_token")
        return GoogleOAuthResult(ok=True, code="token_ok", data={"access_token": access_token})

    @classmethod
    def _fetch_userinfo(cls, access_token: str) -> GoogleOAuthResult:
        request = Request(
            settings.GOOGLE_OAUTH_USERINFO_URI,
            headers={"Authorization": f"Bearer {access_token}"},
            method="GET",
        )
        try:
            with urlopen(request, timeout=8) as response:
                body = response.read().decode("utf-8")
        except (HTTPError, URLError, TimeoutError):
            return GoogleOAuthResult(ok=False, code="oauth_userinfo_failed")

        try:
            parsed = json.loads(body)
        except json.JSONDecodeError:
            return GoogleOAuthResult(ok=False, code="oauth_invalid_response")

        if parsed.get("email_verified") is False:
            return GoogleOAuthResult(ok=False, code="oauth_unverified_email")

        return GoogleOAuthResult(ok=True, code="userinfo_ok", data=parsed)
