import re
from datetime import datetime, timedelta
from unittest.mock import patch

from django.contrib.auth.hashers import make_password
from django.test import SimpleTestCase, override_settings

from .consumers import DMConsumer
from .services.google_oauth import GoogleOAuthResult
from .services.memory_store import RoomStateService
from .services.signup_verification_store import SignupVerificationResult
from .services.signup_verification_store import SignupVerificationStore


class HealthTests(SimpleTestCase):
    def test_health_endpoint(self):
        response = self.client.get("/healthz/")
        self.assertEqual(response.status_code, 200)

    def test_root_redirects_to_login(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/login/")

    def test_lobby_requires_auth(self):
        response = self.client.get("/rooms/")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/login/?next=%2Frooms%2F")

    def test_private_chat_pages_require_auth(self):
        protected_paths = [
            "/chat/",
            "/chat/people/",
            "/chat/profile/",
            "/chat/u/507f1f77bcf86cd799439011/",
        ]
        for path in protected_paths:
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 302)
                self.assertTrue(response.url.startswith("/login/?next="))


class OneTimeImageFlowTests(SimpleTestCase):
    @staticmethod
    def async_run(awaitable):
        import asyncio

        return asyncio.run(awaitable)

    def setUp(self):
        RoomStateService._rooms = {}
        RoomStateService._invite_tokens = {}

    def _join_second_participant(self, room_id: str):
        request = self.async_run(RoomStateService.create_join_request(room_id, "user-2", "User Two"))
        self.assertTrue(request.ok, request.code)
        decision = self.async_run(
            RoomStateService.resolve_join_request(room_id, request.data["request_id"], "owner-1", True)
        )
        self.assertTrue(decision.ok, decision.code)
        connect = self.async_run(RoomStateService.connect_participant(room_id, "user-2", "User Two"))
        self.assertTrue(connect.ok, connect.code)

    def test_one_time_image_can_only_be_consumed_once(self):
        created = self.async_run(RoomStateService.create_room("owner-1", "Owner One"))
        self.assertTrue(created.ok, created.code)
        room_id = created.data["room"]["id"]
        self._join_second_participant(room_id)

        sent = self.async_run(
            RoomStateService.create_one_time_image(
                room_id,
                "owner-1",
                "Owner One",
                "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO2P/qoAAAAASUVORK5CYII=",
                "image/png",
                "one_time_seen",
                None,
            )
        )
        self.assertTrue(sent.ok, sent.code)
        message_id = sent.data["message"]["id"]

        opened = self.async_run(RoomStateService.get_one_time_image_for_view(room_id, message_id, "user-2"))
        self.assertTrue(opened.ok, opened.code)

        consumed = self.async_run(RoomStateService.consume_one_time_image(room_id, message_id, "user-2"))
        self.assertTrue(consumed.ok, consumed.code)
        self.assertEqual(consumed.code, "opened")
        self.assertTrue(consumed.data["message"]["is_opened"])

        second_open = self.async_run(RoomStateService.get_one_time_image_for_view(room_id, message_id, "user-2"))
        self.assertFalse(second_open.ok)
        self.assertEqual(second_open.code, "image_already_opened")


class DirectInviteFlowTests(SimpleTestCase):
    @staticmethod
    def async_run(awaitable):
        import asyncio

        return asyncio.run(awaitable)

    def setUp(self):
        RoomStateService._rooms = {}
        RoomStateService._invite_tokens = {}

    def test_direct_invite_is_single_use(self):
        created = self.async_run(RoomStateService.create_room("owner-1", "Owner One"))
        self.assertTrue(created.ok)
        room_id = created.data["room"]["id"]

        invite = self.async_run(RoomStateService.create_direct_invite(room_id, "owner-1"))
        self.assertTrue(invite.ok)
        token = invite.data["token"]

        first = self.async_run(RoomStateService.consume_direct_invite(token, "guest-1"))
        self.assertTrue(first.ok)
        self.assertEqual(first.data["room_id"], room_id)

        second = self.async_run(RoomStateService.consume_direct_invite(token, "guest-2"))
        self.assertFalse(second.ok)
        self.assertEqual(second.code, "invite_not_found")


class DMGroupNameTests(SimpleTestCase):
    def test_dm_group_name_is_channels_safe(self):
        thread_key = "6a063402154b9a3a209cf43b:6a063438154b9a3a209cf43c"
        group = DMConsumer.dm_thread_group(thread_key)
        self.assertLess(len(group), 100)
        self.assertRegex(group, re.compile(r"^[A-Za-z0-9._-]+$"))


class AuthEnhancementTests(SimpleTestCase):
    @override_settings(
        GOOGLE_OAUTH_CLIENT_ID="test-client-id",
        GOOGLE_OAUTH_CLIENT_SECRET="test-client-secret",
    )
    def test_login_page_shows_google_option_when_configured(self):
        response = self.client.get("/login/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Continue with Google")

    @patch("chatcore.views.SignupVerificationStore.start_signup_verification")
    def test_signup_redirects_to_verify_when_otp_sent(self, mock_start_signup):
        mock_start_signup.return_value = SignupVerificationResult(
            ok=True,
            code="otp_sent",
            data={"email": "user@example.com", "username": "user123"},
        )

        response = self.client.post(
            "/signup/",
            {"email": "user@example.com", "username": "user123", "password": "longpassword"},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/signup/verify/")
        session = self.client.session
        self.assertEqual(session.get("pending_signup_email"), "user@example.com")
        self.assertEqual(session.get("pending_signup_username"), "user123")

    def test_signup_verify_requires_pending_session(self):
        response = self.client.get("/signup/verify/")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/signup/")

    @patch("chatcore.views.SignupVerificationStore.start_signup_verification")
    @patch("chatcore.views.SignupVerificationStore.verify_signup_otp")
    @patch("chatcore.views.SignupVerificationStore.get_pending_signup")
    def test_signup_verify_creates_session_on_success(self, mock_pending, mock_verify, mock_start):
        mock_start.return_value = SignupVerificationResult(
            ok=True,
            code="otp_sent",
            data={"email": "verify@example.com", "username": "verifyuser"},
        )
        self.client.post(
            "/signup/",
            {"email": "verify@example.com", "username": "verifyuser", "password": "longpassword"},
        )
        mock_pending.return_value = {"email": "verify@example.com", "username": "verifyuser"}
        mock_verify.return_value = SignupVerificationResult(
            ok=True,
            code="verified",
            data={
                "user": {
                    "user_id": "507f1f77bcf86cd799439011",
                    "username": "verifyuser",
                    "email": "verify@example.com",
                }
            },
        )

        response = self.client.post("/signup/verify/", {"otp": "123456"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/chat/")

        updated = self.client.session
        self.assertEqual(updated.get("auth_user_email"), "verify@example.com")
        self.assertEqual(updated.get("auth_user_name"), "verifyuser")
        self.assertEqual(updated.get("pending_signup_email"), None)

    @patch("chatcore.views.UserStore.authenticate_external_email")
    @patch("chatcore.views.GoogleOAuthService.complete_login")
    @override_settings(
        GOOGLE_OAUTH_CLIENT_ID="test-client-id",
        GOOGLE_OAUTH_CLIENT_SECRET="test-client-secret",
    )
    def test_google_callback_shows_error_for_non_onboarded_email(self, mock_complete, mock_auth):
        mock_complete.return_value = GoogleOAuthResult(
            ok=True,
            code="oauth_authenticated",
            data={"email": "newuser@example.com", "next_url": ""},
        )
        mock_auth.return_value = type("AuthResult", (), {"ok": False, "code": "account_not_found"})()

        response = self.client.get("/google/callback/?state=stub&code=stub")
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "You do not have an account", status_code=400)

    @patch("chatcore.services.signup_verification_store.UserStore.create_user_from_password_hash")
    @patch("chatcore.services.signup_verification_store.SignupVerificationStore._delete_pending")
    @patch("chatcore.services.signup_verification_store.SignupVerificationStore._load_pending")
    def test_verify_signup_otp_handles_naive_expiry_datetime(self, mock_load, _mock_delete, mock_create):
        otp = "123456"
        mock_load.return_value = {
            "email": "verify@example.com",
            "username": "verifyuser",
            "password_hash": make_password("longpassword"),
            "otp_hash": make_password(otp),
            "expires_at": datetime.utcnow() + timedelta(minutes=5),
            "attempts": 0,
            "max_attempts": 6,
        }
        mock_create.return_value = type(
            "AuthResult",
            (),
            {
                "ok": True,
                "code": "created",
                "data": {
                    "user": {
                        "user_id": "507f1f77bcf86cd799439011",
                        "username": "verifyuser",
                        "email": "verify@example.com",
                    }
                },
            },
        )()

        result = SignupVerificationStore.verify_signup_otp(email="verify@example.com", otp_code=otp)
        self.assertTrue(result.ok)
        self.assertEqual(result.code, "verified")
