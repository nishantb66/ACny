from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from bson import ObjectId
from django.contrib.auth.hashers import check_password, make_password
from django.core.exceptions import ValidationError
from django.core.validators import EmailValidator
from pymongo.errors import DuplicateKeyError, PyMongoError

from .mongo_client import MongoStore, utc_now

USERNAME_RE = re.compile(r"^[a-zA-Z0-9_]{3,24}$")


@dataclass(slots=True)
class UserResult:
    ok: bool
    code: str
    data: dict[str, Any] | None = None


class UserStore:
    _email_validator = EmailValidator()

    @classmethod
    def _validate_email(cls, email: str) -> str:
        normalized = (email or "").strip().lower()
        cls._email_validator(normalized)
        return normalized

    @classmethod
    def _validate_username(cls, username: str) -> str:
        cleaned = (username or "").strip()
        if not USERNAME_RE.match(cleaned):
            raise ValueError("invalid_username")
        return cleaned

    @classmethod
    def create_user(cls, email: str, password: str, username: str) -> UserResult:
        try:
            email_lower = cls._validate_email(email)
        except ValidationError:
            return UserResult(ok=False, code="invalid_email")

        try:
            username_clean = cls._validate_username(username)
        except ValueError:
            return UserResult(ok=False, code="invalid_username")

        password_raw = (password or "").strip()
        if len(password_raw) < 8:
            return UserResult(ok=False, code="weak_password")

        users = MongoStore.users()
        now = utc_now()
        payload = {
            "email": email_lower,
            "email_lower": email_lower,
            "username": username_clean,
            "username_lower": username_clean.lower(),
            "password_hash": make_password(password_raw),
            "created_at": now,
            "updated_at": now,
            "last_seen_at": now,
        }

        try:
            inserted = users.insert_one(payload)
        except DuplicateKeyError:
            try:
                if users.find_one({"email_lower": email_lower}, {"_id": 1}):
                    return UserResult(ok=False, code="email_taken")
            except PyMongoError:
                return UserResult(ok=False, code="database_error")
            return UserResult(ok=False, code="username_taken")
        except PyMongoError:
            return UserResult(ok=False, code="database_error")

        payload["_id"] = inserted.inserted_id
        return UserResult(ok=True, code="created", data={"user": cls._serialize_user(payload)})

    @classmethod
    def authenticate(cls, email: str, password: str) -> UserResult:
        try:
            email_lower = cls._validate_email(email)
        except ValidationError:
            return UserResult(ok=False, code="invalid_credentials")

        users = MongoStore.users()
        try:
            user = users.find_one({"email_lower": email_lower})
        except PyMongoError:
            return UserResult(ok=False, code="database_error")
        if not user:
            return UserResult(ok=False, code="invalid_credentials")
        if not check_password((password or "").strip(), user.get("password_hash", "")):
            return UserResult(ok=False, code="invalid_credentials")

        try:
            users.update_one(
                {"_id": user["_id"]},
                {"$set": {"last_seen_at": utc_now(), "updated_at": utc_now()}},
            )
        except PyMongoError:
            return UserResult(ok=False, code="database_error")
        return UserResult(ok=True, code="authenticated", data={"user": cls._serialize_user(user)})

    @classmethod
    def get_user_by_id(cls, user_id: str | None) -> dict[str, Any] | None:
        object_id = cls._safe_object_id(user_id)
        if not object_id:
            return None
        try:
            user = MongoStore.users().find_one({"_id": object_id})
        except PyMongoError:
            return None
        if not user:
            return None
        return cls._serialize_user(user)

    @classmethod
    def get_user_by_username(cls, username: str) -> dict[str, Any] | None:
        try:
            user = MongoStore.users().find_one({"username_lower": (username or "").strip().lower()})
        except PyMongoError:
            return None
        if not user:
            return None
        return cls._serialize_user(user)

    @classmethod
    def update_username(cls, user_id: str, username: str) -> UserResult:
        object_id = cls._safe_object_id(user_id)
        if not object_id:
            return UserResult(ok=False, code="user_not_found")

        try:
            username_clean = cls._validate_username(username)
        except ValueError:
            return UserResult(ok=False, code="invalid_username")

        users = MongoStore.users()
        try:
            update_result = users.update_one(
                {"_id": object_id},
                {
                    "$set": {
                        "username": username_clean,
                        "username_lower": username_clean.lower(),
                        "updated_at": utc_now(),
                    }
                },
            )
        except DuplicateKeyError:
            return UserResult(ok=False, code="username_taken")
        except PyMongoError:
            return UserResult(ok=False, code="database_error")

        if update_result.matched_count == 0:
            return UserResult(ok=False, code="user_not_found")

        try:
            updated = users.find_one({"_id": object_id})
        except PyMongoError:
            return UserResult(ok=False, code="database_error")
        return UserResult(ok=True, code="updated", data={"user": cls._serialize_user(updated)})

    @classmethod
    def search_users_by_prefix(
        cls,
        query: str,
        exclude_user_id: str,
        limit: int = 12,
    ) -> list[dict[str, Any]]:
        normalized = (query or "").strip().lower()
        if len(normalized) < 1:
            return []

        range_end = f"{normalized}\uffff"
        filters: dict[str, Any] = {
            "username_lower": {
                "$gte": normalized,
                "$lt": range_end,
            }
        }

        exclude_oid = cls._safe_object_id(exclude_user_id)
        if exclude_oid:
            filters["_id"] = {"$ne": exclude_oid}

        try:
            docs = (
                MongoStore.users()
                .find(filters, {"username": 1, "created_at": 1})
                .sort("username_lower", 1)
                .limit(max(1, min(limit, 25)))
            )
        except PyMongoError:
            return []
        return [
            {
                "user_id": str(doc["_id"]),
                "username": doc.get("username", ""),
            }
            for doc in docs
        ]

    @staticmethod
    def _serialize_user(user_doc: dict[str, Any]) -> dict[str, Any]:
        return {
            "user_id": str(user_doc["_id"]),
            "email": user_doc.get("email", ""),
            "username": user_doc.get("username", ""),
            "created_at": user_doc.get("created_at").isoformat() if user_doc.get("created_at") else None,
            "updated_at": user_doc.get("updated_at").isoformat() if user_doc.get("updated_at") else None,
        }

    @staticmethod
    def _safe_object_id(raw: str | None) -> ObjectId | None:
        if not raw:
            return None
        if not ObjectId.is_valid(raw):
            return None
        return ObjectId(raw)
