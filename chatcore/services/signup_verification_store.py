from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.core.validators import EmailValidator
from pymongo.errors import DuplicateKeyError, PyMongoError

from .mongo_client import MongoStore, utc_now
from .user_store import USERNAME_RE, UserStore


@dataclass(slots=True)
class SignupVerificationResult:
    ok: bool
    code: str
    data: dict[str, Any] | None = None


class SignupVerificationStore:
    _email_validator = EmailValidator()

    @classmethod
    def start_signup_verification(cls, email: str, username: str, password: str) -> SignupVerificationResult:
        normalized = cls._normalize_input(email, username, password)
        if not normalized.ok:
            return normalized

        email_lower = normalized.data["email_lower"]
        username_clean = normalized.data["username"]
        password_hash = normalized.data["password_hash"]
        username_lower = username_clean.lower()
        now = utc_now()
        expires_at = now + timedelta(seconds=max(120, int(settings.SIGNUP_OTP_TTL_SECONDS)))
        resend_available_at = now + timedelta(seconds=max(15, int(settings.SIGNUP_OTP_RESEND_COOLDOWN_SECONDS)))

        users = MongoStore.users()
        pending = MongoStore.pending_signups()
        try:
            if users.find_one({"email_lower": email_lower}, {"_id": 1}):
                return SignupVerificationResult(ok=False, code="email_taken")
            if users.find_one({"username_lower": username_lower}, {"_id": 1}):
                return SignupVerificationResult(ok=False, code="username_taken")
        except PyMongoError:
            return SignupVerificationResult(ok=False, code="database_error")

        stale_cleared = cls._clear_expired_pending_for_email(email_lower)
        if stale_cleared == "database_error":
            return SignupVerificationResult(ok=False, code="database_error")

        existing = cls._load_pending(email_lower)
        if existing is None:
            return SignupVerificationResult(ok=False, code="database_error")
        resend_at_existing = cls._as_aware_utc(existing.get("resend_available_at")) if existing else None
        if existing and resend_at_existing and now < resend_at_existing:
            retry_after = int((resend_at_existing - now).total_seconds())
            return SignupVerificationResult(
                ok=False,
                code="otp_rate_limited",
                data={"retry_after_seconds": max(1, retry_after)},
            )

        if cls._pending_username_conflict(email_lower, username_lower):
            return SignupVerificationResult(ok=False, code="username_taken")

        otp_code = cls._generate_otp()
        payload = {
            "email": email_lower,
            "email_lower": email_lower,
            "username": username_clean,
            "username_lower": username_lower,
            "password_hash": password_hash,
            "otp_hash": make_password(otp_code),
            "attempts": 0,
            "max_attempts": max(3, int(settings.SIGNUP_OTP_MAX_ATTEMPTS)),
            "last_sent_at": now,
            "resend_available_at": resend_available_at,
            "expires_at": expires_at,
            "updated_at": now,
        }

        try:
            pending.update_one(
                {"email_lower": email_lower},
                {"$set": payload, "$setOnInsert": {"created_at": now}},
                upsert=True,
            )
        except DuplicateKeyError:
            return SignupVerificationResult(ok=False, code="username_taken")
        except PyMongoError:
            return SignupVerificationResult(ok=False, code="database_error")

        email_result = cls._send_signup_otp_email(email_lower, username_clean, otp_code)
        if not email_result.ok:
            try:
                pending.update_one(
                    {"email_lower": email_lower},
                    {"$set": {"resend_available_at": now, "updated_at": now}},
                )
            except PyMongoError:
                return SignupVerificationResult(ok=False, code="database_error")
            return email_result

        return SignupVerificationResult(
            ok=True,
            code="otp_sent",
            data={"email": email_lower, "username": username_clean},
        )

    @classmethod
    def resend_signup_otp(cls, email: str) -> SignupVerificationResult:
        email_lower = cls._normalize_email(email)
        if not email_lower:
            return SignupVerificationResult(ok=False, code="pending_not_found")

        stale_cleared = cls._clear_expired_pending_for_email(email_lower)
        if stale_cleared == "database_error":
            return SignupVerificationResult(ok=False, code="database_error")

        pending_doc = cls._load_pending(email_lower)
        if pending_doc is None:
            return SignupVerificationResult(ok=False, code="database_error")
        if not pending_doc:
            return SignupVerificationResult(ok=False, code="pending_not_found")

        now = utc_now()
        resend_available_at = cls._as_aware_utc(pending_doc.get("resend_available_at"))
        if resend_available_at and now < resend_available_at:
            retry_after = int((resend_available_at - now).total_seconds())
            return SignupVerificationResult(
                ok=False,
                code="otp_rate_limited",
                data={"retry_after_seconds": max(1, retry_after)},
            )

        otp_code = cls._generate_otp()
        expires_at = now + timedelta(seconds=max(120, int(settings.SIGNUP_OTP_TTL_SECONDS)))
        next_resend_at = now + timedelta(seconds=max(15, int(settings.SIGNUP_OTP_RESEND_COOLDOWN_SECONDS)))
        try:
            MongoStore.pending_signups().update_one(
                {"email_lower": email_lower},
                {
                    "$set": {
                        "otp_hash": make_password(otp_code),
                        "attempts": 0,
                        "last_sent_at": now,
                        "resend_available_at": next_resend_at,
                        "expires_at": expires_at,
                        "updated_at": now,
                    }
                },
            )
        except PyMongoError:
            return SignupVerificationResult(ok=False, code="database_error")

        email_result = cls._send_signup_otp_email(email_lower, pending_doc.get("username", ""), otp_code)
        if not email_result.ok:
            try:
                MongoStore.pending_signups().update_one(
                    {"email_lower": email_lower},
                    {"$set": {"resend_available_at": now, "updated_at": now}},
                )
            except PyMongoError:
                return SignupVerificationResult(ok=False, code="database_error")
            return email_result

        return SignupVerificationResult(ok=True, code="otp_sent")

    @classmethod
    def verify_signup_otp(cls, email: str, otp_code: str) -> SignupVerificationResult:
        email_lower = cls._normalize_email(email)
        if not email_lower:
            return SignupVerificationResult(ok=False, code="pending_not_found")

        pending_doc = cls._load_pending(email_lower)
        if pending_doc is None:
            return SignupVerificationResult(ok=False, code="database_error")
        if not pending_doc:
            return SignupVerificationResult(ok=False, code="pending_not_found")

        now = utc_now()
        expires_at = cls._as_aware_utc(pending_doc.get("expires_at"))
        if not expires_at or expires_at <= now:
            cls._delete_pending(email_lower)
            return SignupVerificationResult(ok=False, code="otp_expired")

        if not cls._is_valid_otp_format(otp_code):
            cls._increment_failed_attempt(email_lower, pending_doc)
            return SignupVerificationResult(ok=False, code="invalid_otp")

        if not check_password(otp_code, pending_doc.get("otp_hash", "")):
            increment_result = cls._increment_failed_attempt(email_lower, pending_doc)
            if increment_result == "max_attempts":
                return SignupVerificationResult(ok=False, code="otp_max_attempts")
            if increment_result == "database_error":
                return SignupVerificationResult(ok=False, code="database_error")
            return SignupVerificationResult(ok=False, code="invalid_otp")

        create_result = UserStore.create_user_from_password_hash(
            email=pending_doc.get("email", ""),
            username=pending_doc.get("username", ""),
            password_hash=pending_doc.get("password_hash", ""),
        )
        if not create_result.ok:
            if create_result.code in {"email_taken", "username_taken"}:
                cls._delete_pending(email_lower)
            return SignupVerificationResult(ok=False, code=create_result.code)

        cls._delete_pending(email_lower)
        return SignupVerificationResult(ok=True, code="verified", data={"user": create_result.data["user"]})

    @classmethod
    def get_pending_signup(cls, email: str) -> dict[str, Any] | None:
        email_lower = cls._normalize_email(email)
        if not email_lower:
            return None
        pending_doc = cls._load_pending(email_lower)
        if not pending_doc:
            return None
        return {
            "email": pending_doc.get("email", ""),
            "username": pending_doc.get("username", ""),
        }

    @classmethod
    def _normalize_input(cls, email: str, username: str, password: str) -> SignupVerificationResult:
        email_lower = cls._normalize_email(email)
        if not email_lower:
            return SignupVerificationResult(ok=False, code="invalid_email")

        username_clean = (username or "").strip()
        if not USERNAME_RE.match(username_clean):
            return SignupVerificationResult(ok=False, code="invalid_username")

        password_raw = (password or "").strip()
        if len(password_raw) < 8:
            return SignupVerificationResult(ok=False, code="weak_password")

        return SignupVerificationResult(
            ok=True,
            code="ok",
            data={
                "email_lower": email_lower,
                "username": username_clean,
                "password_hash": make_password(password_raw),
            },
        )

    @classmethod
    def _normalize_email(cls, email: str) -> str | None:
        normalized = (email or "").strip().lower()
        if not normalized:
            return None
        try:
            cls._email_validator(normalized)
        except ValidationError:
            return None
        return normalized

    @staticmethod
    def _generate_otp() -> str:
        return f"{secrets.randbelow(1_000_000):06d}"

    @staticmethod
    def _is_valid_otp_format(otp_code: str) -> bool:
        return len(otp_code or "") == 6 and str(otp_code).isdigit()

    @classmethod
    def _send_signup_otp_email(cls, email: str, username: str, otp_code: str) -> SignupVerificationResult:
        if not settings.EMAIL_HOST_USER or not settings.EMAIL_HOST_PASSWORD:
            return SignupVerificationResult(ok=False, code="otp_email_not_configured")

        subject = "PulsePair account verification OTP"
        message = (
            f"Hello {username or 'there'},\n\n"
            f"Your PulsePair verification code is: {otp_code}\n\n"
            f"This code expires in {max(2, int(settings.SIGNUP_OTP_TTL_SECONDS // 60))} minutes.\n"
            "If you did not request this, you can ignore this email.\n\n"
            "PulsePair Security"
        )
        try:
            sent = send_mail(
                subject=subject,
                message=message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[email],
                fail_silently=False,
            )
        except Exception:
            return SignupVerificationResult(ok=False, code="otp_send_failed")
        if sent < 1:
            return SignupVerificationResult(ok=False, code="otp_send_failed")
        return SignupVerificationResult(ok=True, code="sent")

    @classmethod
    def _clear_expired_pending_for_email(cls, email_lower: str) -> str:
        now = utc_now()
        pending = MongoStore.pending_signups()
        try:
            pending.delete_many({"email_lower": email_lower, "expires_at": {"$lte": now}})
        except PyMongoError:
            return "database_error"
        return "ok"

    @classmethod
    def _pending_username_conflict(cls, email_lower: str, username_lower: str) -> bool:
        now = utc_now()
        pending = MongoStore.pending_signups()
        try:
            conflicting = pending.find_one(
                {"username_lower": username_lower, "email_lower": {"$ne": email_lower}},
                {"email_lower": 1, "expires_at": 1},
            )
        except PyMongoError:
            return False

        if not conflicting:
            return False

        expires_at = cls._as_aware_utc(conflicting.get("expires_at"))
        if expires_at and expires_at > now:
            return True

        try:
            pending.delete_one({"_id": conflicting["_id"]})
        except PyMongoError:
            return True
        return False

    @classmethod
    def _increment_failed_attempt(cls, email_lower: str, pending_doc: dict[str, Any]) -> str:
        current_attempts = int(pending_doc.get("attempts", 0))
        max_attempts = int(pending_doc.get("max_attempts", max(3, int(settings.SIGNUP_OTP_MAX_ATTEMPTS))))
        next_attempts = current_attempts + 1
        now = utc_now()
        pending = MongoStore.pending_signups()
        try:
            if next_attempts >= max_attempts:
                pending.delete_one({"email_lower": email_lower})
                return "max_attempts"
            pending.update_one(
                {"email_lower": email_lower},
                {"$set": {"attempts": next_attempts, "updated_at": now}},
            )
        except PyMongoError:
            return "database_error"
        return "updated"

    @staticmethod
    def _delete_pending(email_lower: str) -> None:
        try:
            MongoStore.pending_signups().delete_one({"email_lower": email_lower})
        except PyMongoError:
            return

    @staticmethod
    def _load_pending(email_lower: str) -> dict[str, Any] | None:
        try:
            doc = MongoStore.pending_signups().find_one({"email_lower": email_lower})
        except PyMongoError:
            return None
        if not doc:
            return {}
        return doc

    @staticmethod
    def _as_aware_utc(value: Any) -> datetime | None:
        if not isinstance(value, datetime):
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
