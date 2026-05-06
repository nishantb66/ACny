from __future__ import annotations

from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_POST

from .constants import SESSION_USER_ID, SESSION_USER_NAME


@require_GET
def lobby(request: HttpRequest) -> HttpResponse:
    context = {
        "user_id": request.session.get(SESSION_USER_ID),
        "user_name": request.session.get(SESSION_USER_NAME),
    }
    return render(request, "chatcore/lobby.html", context)


@require_GET
def room(request: HttpRequest, room_id: str) -> HttpResponse:
    context = {
        "room_id": room_id,
        "user_id": request.session.get(SESSION_USER_ID),
        "user_name": request.session.get(SESSION_USER_NAME),
    }
    return render(request, "chatcore/room.html", context)


@require_POST
def update_identity(request: HttpRequest) -> HttpResponse:
    name = (request.POST.get("display_name") or "").strip()
    if not (3 <= len(name) <= 24):
        return redirect("lobby")
    request.session[SESSION_USER_NAME] = name
    return redirect("lobby")


@require_GET
def healthz(_: HttpRequest) -> JsonResponse:
    return JsonResponse({"ok": True})
