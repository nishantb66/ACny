from __future__ import annotations

from collections.abc import Callable
from functools import wraps
from typing import Any
from urllib.parse import urlencode

from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.urls import reverse

from .constants import SESSION_USER_EMAIL, SESSION_USER_ID, SESSION_USER_NAME


def get_session_user(request: HttpRequest) -> dict[str, str] | None:
    user_id = request.session.get(SESSION_USER_ID)
    username = request.session.get(SESSION_USER_NAME)
    email = request.session.get(SESSION_USER_EMAIL)
    if not user_id or not username or not email:
        return None
    return {
        "user_id": str(user_id),
        "username": str(username),
        "email": str(email),
    }


def set_session_user(request: HttpRequest, user: dict[str, Any]) -> None:
    request.session[SESSION_USER_ID] = str(user["user_id"])
    request.session[SESSION_USER_NAME] = str(user["username"])
    request.session[SESSION_USER_EMAIL] = str(user["email"])


def clear_session_user(request: HttpRequest) -> None:
    request.session.pop(SESSION_USER_ID, None)
    request.session.pop(SESSION_USER_NAME, None)
    request.session.pop(SESSION_USER_EMAIL, None)


def login_required(view_fn: Callable[..., HttpResponse]) -> Callable[..., HttpResponse]:
    @wraps(view_fn)
    def wrapped(request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        if not get_session_user(request):
            query = urlencode({"next": request.get_full_path()})
            return redirect(f"{reverse('login')}?{query}")
        return view_fn(request, *args, **kwargs)

    return wrapped


def guest_only(view_fn: Callable[..., HttpResponse]) -> Callable[..., HttpResponse]:
    @wraps(view_fn)
    def wrapped(request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        if get_session_user(request):
            return redirect("chat_home")
        return view_fn(request, *args, **kwargs)

    return wrapped
