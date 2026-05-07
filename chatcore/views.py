from __future__ import annotations

from asgiref.sync import async_to_sync
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST, require_safe

from .constants import SESSION_USER_ID, SESSION_USER_NAME
from .services.backend import RoomStateService


@require_safe
def lobby(request: HttpRequest) -> HttpResponse:
    context = {
        "user_id": request.session.get(SESSION_USER_ID),
        "user_name": request.session.get(SESSION_USER_NAME),
    }
    return render(request, "chatcore/lobby.html", context)


@require_safe
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


@require_safe
def healthz(_: HttpRequest) -> JsonResponse:
    return JsonResponse({"ok": True})


def _error_status(code: str) -> int:
    if code in {"forbidden"}:
        return 403
    if code in {"room_not_found", "invite_not_found", "invite_expired"}:
        return 404
    if code in {"room_full"}:
        return 409
    return 400


@require_POST
def create_whatsapp_invite(request: HttpRequest, room_id: str) -> JsonResponse:
    user_id = request.session.get(SESSION_USER_ID)
    normalized_room_id = room_id.upper()

    result = async_to_sync(RoomStateService.create_direct_invite)(normalized_room_id, user_id)
    if not result.ok:
        return JsonResponse(
            {"ok": False, "code": result.code},
            status=_error_status(result.code),
        )

    token = result.data["token"]
    invite_url = request.build_absolute_uri(f"/invite/{token}/")
    return JsonResponse(
        {
            "ok": True,
            "room_id": normalized_room_id,
            "invite_url": invite_url,
            "token": token,
            "expires_at": result.data["expires_at"],
        }
    )


@require_safe
def accept_direct_invite(request: HttpRequest, token: str) -> HttpResponse:
    user_id = request.session.get(SESSION_USER_ID)
    result = async_to_sync(RoomStateService.consume_direct_invite)(token, user_id)
    if not result.ok:
        return redirect(f"/?invite_error={result.code}")

    room_id = result.data["room_id"]
    return redirect(f"/room/{room_id}/")
