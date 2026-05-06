from __future__ import annotations

import asyncio
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from chatcore.constants import DEFAULT_SINGLE_USER_DISCOVERABLE, MAX_ROOM_PARTICIPANTS


@dataclass(slots=True)
class ServiceResult:
    ok: bool
    code: str
    data: dict[str, Any] | None = None


class RoomStateService:
    _lock = asyncio.Lock()
    _rooms: dict[str, dict[str, Any]] = {}

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
