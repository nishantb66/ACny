from __future__ import annotations

import secrets

from django.http import HttpRequest, HttpResponse

from .constants import SESSION_USER_ID, SESSION_USER_NAME


class IdentityMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if SESSION_USER_ID not in request.session:
            request.session[SESSION_USER_ID] = secrets.token_urlsafe(10)
        if SESSION_USER_NAME not in request.session:
            suffix = request.session[SESSION_USER_ID][:4].upper()
            request.session[SESSION_USER_NAME] = f"Guest-{suffix}"
        return self.get_response(request)
