from __future__ import annotations

from asgiref.sync import async_to_sync
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_http_methods, require_POST, require_safe

from .auth import clear_session_user, get_session_user, guest_only, login_required, set_session_user
from .services.google_oauth import GoogleOAuthService
from .services.backend import RoomStateService
from .services.chat_store import ChatStore
from .services.signup_verification_store import SignupVerificationStore
from .services.user_store import UserStore

PENDING_SIGNUP_EMAIL_SESSION_KEY = "pending_signup_email"
PENDING_SIGNUP_USERNAME_SESSION_KEY = "pending_signup_username"


@require_safe
def root(request: HttpRequest) -> HttpResponse:
    if get_session_user(request):
        return redirect("chat_home")
    return redirect("login")


@guest_only
@require_http_methods(["GET", "POST"])
def login_view(request: HttpRequest) -> HttpResponse:
    context: dict[str, str | bool] = {"google_login_enabled": GoogleOAuthService.is_enabled()}
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
@require_GET
def google_login_start(request: HttpRequest) -> HttpResponse:
    next_url = request.GET.get("next", "")
    oauth_result = GoogleOAuthService.build_login_redirect(request, next_url=next_url)
    if not oauth_result.ok:
        context = {
            "google_login_enabled": False,
            "error": "Google Sign-In is currently unavailable. Please use email and password.",
            "next": next_url,
        }
        return render(request, "chatcore/login.html", context, status=503)
    return redirect(oauth_result.data["auth_url"])


@guest_only
@require_GET
def google_callback(request: HttpRequest) -> HttpResponse:
    oauth_result = GoogleOAuthService.complete_login(request)
    if not oauth_result.ok:
        error_map = {
            "oauth_not_configured": "Google Sign-In is currently unavailable.",
            "invalid_oauth_state": "Google Sign-In session is invalid. Please try again.",
            "oauth_denied": "Google Sign-In was cancelled.",
            "oauth_invalid_code": "Google Sign-In returned an invalid authorization code.",
            "oauth_token_exchange_failed": "Could not complete Google Sign-In. Please retry.",
            "oauth_invalid_response": "Google Sign-In response was invalid. Please retry.",
            "oauth_missing_access_token": "Google Sign-In response is incomplete.",
            "oauth_userinfo_failed": "Could not verify Google account details. Please retry.",
            "oauth_unverified_email": "Your Google email is not verified.",
            "oauth_missing_email": "Google account email is unavailable.",
        }
        context = {
            "google_login_enabled": GoogleOAuthService.is_enabled(),
            "error": error_map.get(oauth_result.code, "Google Sign-In failed. Please retry."),
            "next": "",
        }
        return render(request, "chatcore/login.html", context, status=400)

    auth_result = UserStore.authenticate_external_email(oauth_result.data["email"])
    if not auth_result.ok:
        if auth_result.code == "account_not_found":
            error = "You do not have an account. Please sign up first using this email."
        elif auth_result.code == "database_error":
            error = "Database is temporarily unavailable. Please retry."
        else:
            error = "Unable to log in with Google. Please retry."
        return render(
            request,
            "chatcore/login.html",
            {
                "google_login_enabled": GoogleOAuthService.is_enabled(),
                "error": error,
                "next": "",
            },
            status=400,
        )

    set_session_user(request, auth_result.data["user"])
    next_url = oauth_result.data.get("next_url") or ""
    if next_url.startswith("/"):
        return redirect(next_url)
    return redirect("chat_home")


@guest_only
@require_http_methods(["GET", "POST"])
def signup_view(request: HttpRequest) -> HttpResponse:
    context: dict[str, str] = {}
    if request.method == "POST":
        email = (request.POST.get("email") or "").strip()
        username = (request.POST.get("username") or "").strip()
        password = request.POST.get("password") or ""

        result = SignupVerificationStore.start_signup_verification(
            email=email,
            password=password,
            username=username,
        )
        if result.ok:
            request.session[PENDING_SIGNUP_EMAIL_SESSION_KEY] = result.data["email"]
            request.session[PENDING_SIGNUP_USERNAME_SESSION_KEY] = result.data["username"]
            return redirect("signup_verify")

        context["email"] = email
        context["username"] = username
        error_map = {
            "invalid_email": "Please enter a valid email address.",
            "invalid_username": "Username must be 3-24 chars using letters, numbers, or underscore.",
            "weak_password": "Password must be at least 8 characters.",
            "email_taken": "Email is already registered.",
            "username_taken": "Username is already taken.",
            "otp_rate_limited": "Please wait before requesting another OTP.",
            "otp_email_not_configured": "OTP email service is not configured. Please contact support.",
            "otp_send_failed": "Unable to send OTP email right now. Please retry.",
            "database_error": "Database is temporarily unavailable. Please retry.",
        }
        context["error"] = error_map.get(result.code, "Could not create account. Please try again.")
        if result.code == "otp_rate_limited" and result.data:
            context["error"] = (
                f"Please wait {result.data.get('retry_after_seconds', 0)}s "
                "before requesting another OTP."
            )

    return render(request, "chatcore/signup.html", context)


@guest_only
@require_http_methods(["GET", "POST"])
def signup_verify_view(request: HttpRequest) -> HttpResponse:
    email = request.session.get(PENDING_SIGNUP_EMAIL_SESSION_KEY, "")
    username = request.session.get(PENDING_SIGNUP_USERNAME_SESSION_KEY, "")
    if not email:
        return redirect("signup")

    pending = SignupVerificationStore.get_pending_signup(email)
    if not pending:
        request.session.pop(PENDING_SIGNUP_EMAIL_SESSION_KEY, None)
        request.session.pop(PENDING_SIGNUP_USERNAME_SESSION_KEY, None)
        return redirect("signup")

    context: dict[str, str] = {
        "email": pending["email"],
        "username": pending["username"] or username or "",
    }

    if request.method == "POST":
        action = (request.POST.get("action") or "").strip()
        if action == "resend":
            resend = SignupVerificationStore.resend_signup_otp(email)
            if resend.ok:
                context["success"] = "A new OTP has been sent to your email."
            else:
                error_map = {
                    "pending_not_found": "Verification session not found. Please sign up again.",
                    "otp_rate_limited": "Please wait before requesting another OTP.",
                    "otp_email_not_configured": "OTP email service is not configured.",
                    "otp_send_failed": "Unable to send OTP email right now.",
                    "database_error": "Database is temporarily unavailable. Please retry.",
                }
                context["error"] = error_map.get(resend.code, "Could not resend OTP. Please retry.")
                if resend.code == "otp_rate_limited" and resend.data:
                    context["error"] = (
                        f"Please wait {resend.data.get('retry_after_seconds', 0)}s "
                        "before requesting another OTP."
                    )
        else:
            otp = (request.POST.get("otp") or "").strip()
            verify = SignupVerificationStore.verify_signup_otp(email=email, otp_code=otp)
            if verify.ok:
                request.session.pop(PENDING_SIGNUP_EMAIL_SESSION_KEY, None)
                request.session.pop(PENDING_SIGNUP_USERNAME_SESSION_KEY, None)
                set_session_user(request, verify.data["user"])
                return redirect("chat_home")

            error_map = {
                "pending_not_found": "Verification session not found. Please sign up again.",
                "otp_expired": "OTP has expired. Please request a new OTP.",
                "invalid_otp": "Invalid OTP. Please try again.",
                "otp_max_attempts": "Too many invalid attempts. Please sign up again.",
                "email_taken": "Email is already registered. Please log in.",
                "username_taken": "Username is already taken. Please sign up again.",
                "invalid_email": "Email address is invalid.",
                "invalid_username": "Username is invalid. Please sign up again.",
                "weak_password": "Password is invalid. Please sign up again.",
                "database_error": "Database is temporarily unavailable. Please retry.",
            }
            context["error"] = error_map.get(verify.code, "Could not verify OTP. Please retry.")
            context["otp"] = otp

            if verify.code in {"pending_not_found", "otp_max_attempts", "email_taken", "username_taken"}:
                request.session.pop(PENDING_SIGNUP_EMAIL_SESSION_KEY, None)
                request.session.pop(PENDING_SIGNUP_USERNAME_SESSION_KEY, None)

    return render(request, "chatcore/signup_verify.html", context)


@login_required
@require_http_methods(["GET", "POST"])
def logout_view(request: HttpRequest) -> HttpResponse:
    clear_session_user(request)
    return redirect("login")


@login_required
@require_safe
def chat_home(request: HttpRequest) -> HttpResponse:
    context = _chat_context(request, page="inbox")
    return render(request, "chatcore/chat_home.html", context)


@login_required
@require_safe
def chat_people(request: HttpRequest) -> HttpResponse:
    context = _chat_context(request, page="people")
    return render(request, "chatcore/chat_home.html", context)


@login_required
@require_safe
def chat_profile(request: HttpRequest) -> HttpResponse:
    context = _chat_context(request, page="profile")
    return render(request, "chatcore/chat_home.html", context)


@login_required
@require_safe
def chat_thread(request: HttpRequest, peer_id: str) -> HttpResponse:
    session_user = get_session_user(request)
    if peer_id == session_user["user_id"]:
        return redirect("chat_profile")

    peer = UserStore.get_user_by_id(peer_id)
    if not peer:
        return redirect("chat_people")

    context = _chat_context(request, page="thread", active_peer=peer)
    return render(request, "chatcore/chat_home.html", context)


def _chat_context(
    request: HttpRequest,
    page: str,
    active_peer: dict[str, str] | None = None,
) -> dict[str, object]:
    session_user = get_session_user(request)
    conversations = ChatStore.list_conversations(session_user["user_id"], limit=40)
    page_titles = {
        "inbox": "Chats",
        "people": "People",
        "profile": "Profile",
        "thread": active_peer["username"] if active_peer else "Chat",
    }
    return {
        "page": page,
        "page_title": page_titles.get(page, "Chats"),
        "user_id": session_user["user_id"],
        "user_name": session_user["username"],
        "user_email": session_user["email"],
        "conversations": conversations,
        "active_peer": active_peer,
    }


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
