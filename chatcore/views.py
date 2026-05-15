from __future__ import annotations

from asgiref.sync import async_to_sync
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_http_methods, require_POST, require_safe

from .auth import clear_session_user, get_session_user, guest_only, login_required, set_session_user
from .services.backend import RoomStateService
from .services.chat_store import ChatStore
from .services.user_store import UserStore


@require_safe
def root(request: HttpRequest) -> HttpResponse:
    if get_session_user(request):
        return redirect("chat_home")
    return redirect("login")


@guest_only
@require_http_methods(["GET", "POST"])
def login_view(request: HttpRequest) -> HttpResponse:
    context: dict[str, str] = {}
    if request.method == "POST":
        email = (request.POST.get("email") or "").strip()
        password = request.POST.get("password") or ""
        result = UserStore.authenticate(email, password)
        if result.ok:
            set_session_user(request, result.data["user"])
            next_url = request.POST.get("next") or request.GET.get("next") or ""
            if next_url.startswith("/"):
                return redirect(next_url)
            return redirect("chat_home")
        if result.code == "database_error":
            context["error"] = "Database is temporarily unavailable. Please retry."
        else:
            context["error"] = "Invalid email or password."
        context["email"] = email

    context["next"] = request.GET.get("next", "")
    return render(request, "chatcore/login.html", context)


@guest_only
@require_http_methods(["GET", "POST"])
def signup_view(request: HttpRequest) -> HttpResponse:
    context: dict[str, str] = {}
    if request.method == "POST":
        email = (request.POST.get("email") or "").strip()
        username = (request.POST.get("username") or "").strip()
        password = request.POST.get("password") or ""

        result = UserStore.create_user(email=email, password=password, username=username)
        if result.ok:
            set_session_user(request, result.data["user"])
            return redirect("chat_home")

        context["email"] = email
        context["username"] = username
        error_map = {
            "invalid_email": "Please enter a valid email address.",
            "invalid_username": "Username must be 3-24 chars using letters, numbers, or underscore.",
            "weak_password": "Password must be at least 8 characters.",
            "email_taken": "Email is already registered.",
            "username_taken": "Username is already taken.",
            "database_error": "Database is temporarily unavailable. Please retry.",
        }
        context["error"] = error_map.get(result.code, "Could not create account. Please try again.")

    return render(request, "chatcore/signup.html", context)


@login_required
@require_http_methods(["GET", "POST"])
def logout_view(request: HttpRequest) -> HttpResponse:
    clear_session_user(request)
    return redirect("login")


@login_required
@require_safe
def chat_home(request: HttpRequest) -> HttpResponse:
    session_user = get_session_user(request)
    conversations = ChatStore.list_conversations(session_user["user_id"], limit=40)
    context = {
        "user_id": session_user["user_id"],
        "user_name": session_user["username"],
        "user_email": session_user["email"],
        "conversations": conversations,
    }
    return render(request, "chatcore/chat_home.html", context)


@login_required
@require_safe
def lobby(request: HttpRequest) -> HttpResponse:
    session_user = get_session_user(request)
    context = {
        "user_id": session_user["user_id"],
        "user_name": session_user["username"],
        "user_email": session_user["email"],
    }
    return render(request, "chatcore/lobby.html", context)


@login_required
@require_safe
def room(request: HttpRequest, room_id: str) -> HttpResponse:
    session_user = get_session_user(request)
    context = {
        "room_id": room_id,
        "user_id": session_user["user_id"],
        "user_name": session_user["username"],
        "user_email": session_user["email"],
    }
    return render(request, "chatcore/room.html", context)


@login_required
@require_POST
def update_identity(request: HttpRequest) -> HttpResponse:
    session_user = get_session_user(request)
    username = (request.POST.get("display_name") or "").strip()
    result = UserStore.update_username(session_user["user_id"], username)
    if result.ok:
        set_session_user(request, result.data["user"])
        return redirect("lobby")
    return redirect(f"/rooms/?profile_error={result.code}")


@login_required
@require_POST
def update_profile(request: HttpRequest) -> JsonResponse:
    session_user = get_session_user(request)
    username = (request.POST.get("username") or "").strip()
    result = UserStore.update_username(session_user["user_id"], username)
    if not result.ok:
        code_to_message = {
            "invalid_username": "Username must be 3-24 chars using letters, numbers, or underscore.",
            "username_taken": "Username already exists.",
            "user_not_found": "User session is invalid. Please log in again.",
            "database_error": "Database is temporarily unavailable. Please retry.",
        }
        return JsonResponse(
            {
                "ok": False,
                "code": result.code,
                "message": code_to_message.get(result.code, "Unable to update username"),
            },
            status=400,
        )

    set_session_user(request, result.data["user"])
    return JsonResponse({"ok": True, "user": result.data["user"]})


@login_required
@require_GET
def search_users(request: HttpRequest) -> JsonResponse:
    session_user = get_session_user(request)
    query = (request.GET.get("q") or "").strip()
    if not query:
        return JsonResponse({"ok": True, "items": []})

    items = UserStore.search_users_by_prefix(query, session_user["user_id"], limit=16)
    return JsonResponse({"ok": True, "items": items})


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


@login_required
@require_POST
def create_whatsapp_invite(request: HttpRequest, room_id: str) -> JsonResponse:
    session_user = get_session_user(request)
    normalized_room_id = room_id.upper()

    result = async_to_sync(RoomStateService.create_direct_invite)(normalized_room_id, session_user["user_id"])
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
    session_user = get_session_user(request)
    if not session_user:
        return redirect(f"/login/?next=/invite/{token}/")

    result = async_to_sync(RoomStateService.consume_direct_invite)(token, session_user["user_id"])
    if not result.ok:
        return redirect(f"/rooms/?invite_error={result.code}")

    room_id = result.data["room_id"]
    return redirect(f"/room/{room_id}/")
