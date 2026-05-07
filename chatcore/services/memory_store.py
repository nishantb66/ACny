from __future__ import annotations

import asyncio
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from chatcore.constants import (
    DEFAULT_SINGLE_USER_DISCOVERABLE,
    DIRECT_INVITE_TTL_SECONDS,
    MAX_ROOM_PARTICIPANTS,
    TIMED_ONE_TIME_IMAGE_MODE,
)


@dataclass(slots=True)
class ServiceResult:
    ok: bool
    code: str
    data: dict[str, Any] | None = None


class RoomStateService:
    _lock = asyncio.Lock()
    _rooms: dict[str, dict[str, Any]] = {}
    _invite_tokens: dict[str, dict[str, Any]] = {}

    @classmethod
    def room_group(cls, room_id: str) -> str:
        return f"room.{room_id}"

    @classmethod
    def user_group(cls, user_id: str) -> str:
        return f"user.{user_id}"

    @staticmethod
    def utc_now() -> str:
        return datetime.now(UTC).isoformat()

    @staticmethod
    def generate_room_id() -> str:
        return secrets.token_urlsafe(8).replace("-", "").replace("_", "")[:10].upper()

    @classmethod
    async def create_room(cls, owner_id: str, owner_name: str) -> ServiceResult:
        async with cls._lock:
            for _ in range(6):
                room_id = cls.generate_room_id()
                if room_id in cls._rooms:
                    continue
                joined_at = cls.utc_now()
                cls._rooms[room_id] = {
                    "id": room_id,
                    "owner_id": owner_id,
                    "owner_name": owner_name,
                    "created_at": joined_at,
                    "discoverable_when_single": DEFAULT_SINGLE_USER_DISCOVERABLE,
                    "participants": {
                        owner_id: {
                            "user_id": owner_id,
                            "display_name": owner_name,
                            "joined_at": joined_at,
                            "is_online": True,
                            "connections": 1,
                        }
                    },
                    "pending_requests": {},
                    "permits": set(),
                    "ephemeral_images": {},
                }
                return ServiceResult(ok=True, code="created", data={"room": cls._snapshot(room_id)})
        return ServiceResult(ok=False, code="room_generation_failed")

    @classmethod
    async def list_discoverable_rooms(cls) -> list[dict[str, Any]]:
        async with cls._lock:
            rooms = [cls._snapshot(room_id) for room_id in cls._rooms]
            return [room for room in rooms if room and room["is_visible"]]

    @classmethod
    async def get_owner_id(cls, room_id: str) -> str | None:
        async with cls._lock:
            room = cls._rooms.get(room_id)
            if not room:
                return None
            return room["owner_id"]

    @classmethod
    async def get_room_snapshot(cls, room_id: str) -> dict[str, Any] | None:
        async with cls._lock:
            return cls._snapshot(room_id)

    @classmethod
    async def sync_visibility(cls, room_id: str) -> dict[str, Any] | None:
        async with cls._lock:
            return cls._snapshot(room_id)

    @classmethod
    async def connect_participant(cls, room_id: str, user_id: str, display_name: str) -> ServiceResult:
        async with cls._lock:
            room = cls._rooms.get(room_id)
            if not room:
                return ServiceResult(ok=False, code="room_not_found")

            participants = room["participants"]
            is_member = user_id in participants
            is_owner = room["owner_id"] == user_id

            if not is_member:
                if not is_owner and user_id not in room["permits"]:
                    return ServiceResult(ok=False, code="join_not_permitted")
                if len(participants) >= MAX_ROOM_PARTICIPANTS:
                    return ServiceResult(ok=False, code="room_full")
                participants[user_id] = {
                    "user_id": user_id,
                    "display_name": display_name,
                    "joined_at": cls.utc_now(),
                    "is_online": True,
                    "connections": 1,
                }
                room["permits"].discard(user_id)
            else:
                participants[user_id]["display_name"] = display_name
                participants[user_id]["connections"] += 1
                participants[user_id]["is_online"] = True

            return ServiceResult(ok=True, code="connected", data={"room": cls._snapshot(room_id)})

    @classmethod
    async def disconnect_participant(cls, room_id: str, user_id: str) -> ServiceResult:
        async with cls._lock:
            room = cls._rooms.get(room_id)
            if not room:
                return ServiceResult(ok=True, code="room_missing")

            participant = room["participants"].get(user_id)
            if participant:
                participant["connections"] = max(0, participant["connections"] - 1)
                participant["is_online"] = participant["connections"] > 0
                if participant["connections"] == 0:
                    room["participants"].pop(user_id, None)

            if not room["participants"]:
                cls._rooms.pop(room_id, None)
                return ServiceResult(ok=True, code="room_deleted", data={"room_id": room_id})

            if room["owner_id"] == user_id:
                new_owner = next(iter(room["participants"].values()))
                room["owner_id"] = new_owner["user_id"]
                room["owner_name"] = new_owner["display_name"]

            snapshot = cls._snapshot(room_id)
            if not snapshot or snapshot["online_count"] == 0:
                cls._rooms.pop(room_id, None)
                return ServiceResult(ok=True, code="room_deleted", data={"room_id": room_id})

            return ServiceResult(ok=True, code="updated", data={"room": snapshot})

    @classmethod
    async def delete_room(cls, room_id: str) -> None:
        async with cls._lock:
            cls._rooms.pop(room_id, None)
            stale_tokens = [
                token
                for token, payload in cls._invite_tokens.items()
                if payload.get("room_id") == room_id
            ]
            for token in stale_tokens:
                cls._invite_tokens.pop(token, None)

    @classmethod
    async def online_user_ids(cls, room_id: str) -> list[str]:
        async with cls._lock:
            room = cls._rooms.get(room_id)
            if not room:
                return []
            return [uid for uid, user in room["participants"].items() if user["is_online"]]

    @classmethod
    async def create_join_request(
        cls,
        room_id: str,
        requester_id: str,
        requester_name: str,
    ) -> ServiceResult:
        async with cls._lock:
            room = cls._rooms.get(room_id)
            if not room:
                return ServiceResult(ok=False, code="room_not_found")

            snapshot = cls._snapshot(room_id)
            if snapshot["owner_id"] == requester_id:
                return ServiceResult(ok=False, code="owner_cannot_join")
            if snapshot["is_full"]:
                return ServiceResult(ok=False, code="room_full")
            if not snapshot["is_visible"]:
                return ServiceResult(ok=False, code="room_not_visible")

            request_id = secrets.token_urlsafe(8)
            payload = {
                "request_id": request_id,
                "room_id": room_id,
                "requester_id": requester_id,
                "requester_name": requester_name,
                "created_at": cls.utc_now(),
            }
            room["pending_requests"][request_id] = payload
            return ServiceResult(ok=True, code="request_created", data=payload)

    @classmethod
    async def resolve_join_request(
        cls,
        room_id: str,
        request_id: str,
        approver_id: str,
        approved: bool,
    ) -> ServiceResult:
        async with cls._lock:
            room = cls._rooms.get(room_id)
            if not room:
                return ServiceResult(ok=False, code="room_not_found")

            participant = room["participants"].get(approver_id)
            if not participant or not participant["is_online"]:
                return ServiceResult(ok=False, code="forbidden")

            payload = room["pending_requests"].pop(request_id, None)
            if not payload:
                return ServiceResult(ok=False, code="request_not_found")

            if not approved:
                payload["status"] = "rejected"
                return ServiceResult(ok=True, code="request_rejected", data=payload)

            requester_id = payload["requester_id"]
            if len(room["participants"]) >= MAX_ROOM_PARTICIPANTS and requester_id not in room["participants"]:
                return ServiceResult(ok=False, code="room_full")

            room["permits"].add(requester_id)
            payload["status"] = "approved"
            return ServiceResult(ok=True, code="request_approved", data=payload)

    @classmethod
    async def set_discoverable_when_single(
        cls,
        room_id: str,
        user_id: str,
        discoverable_when_single: bool,
    ) -> ServiceResult:
        async with cls._lock:
            room = cls._rooms.get(room_id)
            if not room:
                return ServiceResult(ok=False, code="room_not_found")
            if user_id not in room["participants"]:
                return ServiceResult(ok=False, code="forbidden")
            room["discoverable_when_single"] = discoverable_when_single
            return ServiceResult(ok=True, code="updated", data={"room": cls._snapshot(room_id)})

    @classmethod
    async def create_direct_invite(cls, room_id: str, creator_id: str) -> ServiceResult:
        async with cls._lock:
            room = cls._rooms.get(room_id)
            if not room:
                return ServiceResult(ok=False, code="room_not_found")
            if creator_id not in room["participants"]:
                return ServiceResult(ok=False, code="forbidden")

            token = secrets.token_urlsafe(18)
            expires_at = datetime.now(UTC) + timedelta(seconds=DIRECT_INVITE_TTL_SECONDS)
            cls._invite_tokens[token] = {
                "token": token,
                "room_id": room_id,
                "created_by": creator_id,
                "created_at": cls.utc_now(),
                "expires_at": expires_at.isoformat(),
            }
            return ServiceResult(
                ok=True,
                code="created",
                data={
                    "token": token,
                    "room_id": room_id,
                    "expires_at": expires_at.isoformat(),
                },
            )

    @classmethod
    async def consume_direct_invite(cls, token: str, user_id: str) -> ServiceResult:
        async with cls._lock:
            payload = cls._invite_tokens.get(token)
            if not payload:
                return ServiceResult(ok=False, code="invite_not_found")

            expires_at_raw = payload.get("expires_at")
            try:
                expires_at = datetime.fromisoformat(expires_at_raw) if expires_at_raw else None
            except ValueError:
                expires_at = None

            now = datetime.now(UTC)
            if not expires_at or expires_at <= now:
                cls._invite_tokens.pop(token, None)
                return ServiceResult(ok=False, code="invite_expired")

            room_id = payload["room_id"]
            room = cls._rooms.get(room_id)
            if not room:
                cls._invite_tokens.pop(token, None)
                return ServiceResult(ok=False, code="room_not_found")

            if user_id not in room["participants"] and len(room["participants"]) >= MAX_ROOM_PARTICIPANTS:
                return ServiceResult(ok=False, code="room_full")

            room["permits"].add(user_id)
            cls._invite_tokens.pop(token, None)
            return ServiceResult(ok=True, code="consumed", data={"room_id": room_id})

    @classmethod
    async def create_one_time_image(
        cls,
        room_id: str,
        sender_id: str,
        sender_name: str,
        image_data_url: str,
        mime_type: str,
        view_mode: str,
        view_seconds: int | None,
    ) -> ServiceResult:
        async with cls._lock:
            room = cls._rooms.get(room_id)
            if not room:
                return ServiceResult(ok=False, code="room_not_found")
            if sender_id not in room["participants"]:
                return ServiceResult(ok=False, code="forbidden")

            message_id = secrets.token_urlsafe(10)
            payload = {
                "id": message_id,
                "message_type": "one_time_image",
                "sender_id": sender_id,
                "sender_name": sender_name,
                "sent_at": cls.utc_now(),
                "image_data_url": image_data_url,
                "mime_type": mime_type,
                "view_mode": view_mode,
                "view_seconds": int(view_seconds) if view_mode == TIMED_ONE_TIME_IMAGE_MODE else None,
                "opened_at": None,
                "opened_by": None,
                "active_viewer_id": None,
                "active_view_started_at": None,
                "is_opened": False,
                "preview_text": (
                    "Timed one-time image"
                    if view_mode == TIMED_ONE_TIME_IMAGE_MODE
                    else "One-time image"
                ),
            }
            room["ephemeral_images"][message_id] = payload
            return ServiceResult(ok=True, code="created", data={"message": cls._image_public_payload(payload)})

    @classmethod
    async def get_one_time_image_for_view(
        cls,
        room_id: str,
        message_id: str,
        viewer_id: str,
    ) -> ServiceResult:
        async with cls._lock:
            room = cls._rooms.get(room_id)
            if not room:
                return ServiceResult(ok=False, code="room_not_found")
            if viewer_id not in room["participants"]:
                return ServiceResult(ok=False, code="forbidden")

            payload = room["ephemeral_images"].get(message_id)
            if not payload:
                return ServiceResult(ok=False, code="image_not_found")
            if payload["sender_id"] == viewer_id:
                return ServiceResult(ok=False, code="sender_cannot_open")
            if payload["opened_at"]:
                return ServiceResult(ok=False, code="image_already_opened")

            active_viewer_id = payload.get("active_viewer_id")
            if active_viewer_id and active_viewer_id != viewer_id:
                return ServiceResult(ok=False, code="image_view_in_progress")

            payload["active_viewer_id"] = viewer_id
            payload["active_view_started_at"] = cls.utc_now()

            return ServiceResult(
                ok=True,
                code="open_granted",
                data={
                    "message": cls._image_public_payload(payload),
                    "view": {
                        "message_id": payload["id"],
                        "image_data_url": payload["image_data_url"],
                        "mime_type": payload["mime_type"],
                        "view_mode": payload["view_mode"],
                        "view_seconds": payload["view_seconds"],
                        "opened_at": payload["opened_at"],
                    },
                },
            )

    @classmethod
    async def consume_one_time_image(
        cls,
        room_id: str,
        message_id: str,
        viewer_id: str,
    ) -> ServiceResult:
        async with cls._lock:
            room = cls._rooms.get(room_id)
            if not room:
                return ServiceResult(ok=False, code="room_not_found")
            if viewer_id not in room["participants"]:
                return ServiceResult(ok=False, code="forbidden")

            payload = room["ephemeral_images"].get(message_id)
            if not payload:
                return ServiceResult(ok=False, code="image_not_found")
            if payload["sender_id"] == viewer_id:
                return ServiceResult(ok=False, code="sender_cannot_open")
            if payload["opened_at"]:
                return ServiceResult(
                    ok=True,
                    code="already_opened",
                    data={"message": cls._image_public_payload(payload)},
                )

            active_viewer_id = payload.get("active_viewer_id")
            if active_viewer_id and active_viewer_id != viewer_id:
                return ServiceResult(ok=False, code="forbidden")

            payload["opened_at"] = cls.utc_now()
            payload["opened_by"] = viewer_id
            payload["active_viewer_id"] = None
            payload["active_view_started_at"] = None
            payload["is_opened"] = True

            return ServiceResult(
                ok=True,
                code="opened",
                data={"message": cls._image_public_payload(payload)},
            )

    @classmethod
    def _image_public_payload(cls, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": payload["id"],
            "message_type": payload["message_type"],
            "sender_id": payload["sender_id"],
            "sender_name": payload["sender_name"],
            "sent_at": payload["sent_at"],
            "view_mode": payload["view_mode"],
            "view_seconds": payload["view_seconds"],
            "opened_at": payload["opened_at"],
            "opened_by": payload["opened_by"],
            "is_opened": bool(payload["opened_at"]),
            "preview_text": payload["preview_text"],
        }

    @classmethod
    def _snapshot(cls, room_id: str) -> dict[str, Any] | None:
        room = cls._rooms.get(room_id)
        if not room:
            return None

        participants = []
        online_count = 0
        for user in room["participants"].values():
            is_online = bool(user["connections"] > 0)
            online_count += int(is_online)
            participants.append(
                {
                    "user_id": user["user_id"],
                    "display_name": user["display_name"],
                    "joined_at": user["joined_at"],
                    "is_online": is_online,
                }
            )
        participants.sort(key=lambda user: user["joined_at"] or "")

        discoverable_when_single = bool(room["discoverable_when_single"])
        is_visible = online_count > 0 and (online_count > 1 or discoverable_when_single)

        return {
            "id": room["id"],
            "owner_id": room["owner_id"],
            "owner_name": room["owner_name"],
            "created_at": room["created_at"],
            "participants": participants,
            "occupancy": len(participants),
            "online_count": online_count,
            "is_full": len(participants) >= MAX_ROOM_PARTICIPANTS,
            "discoverable_when_single": discoverable_when_single,
            "is_visible": is_visible,
        }
