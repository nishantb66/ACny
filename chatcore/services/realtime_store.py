from __future__ import annotations

import json
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from django.conf import settings
from redis.asyncio import Redis

from chatcore.constants import (
    DEFAULT_SINGLE_USER_DISCOVERABLE,
    MAX_ROOM_PARTICIPANTS,
    TIMED_ONE_TIME_IMAGE_MODE,
)


@dataclass(slots=True)
class ServiceResult:
    ok: bool
    code: str
    data: dict[str, Any] | None = None


class RoomStateService:
    _redis: Redis | None = None
    _ONE_TIME_IMAGE_TTL_SECONDS = 60 * 60 * 12

    @classmethod
    def redis(cls) -> Redis:
        if cls._redis is None:
            cls._redis = Redis.from_url(settings.REDIS_URL, encoding="utf-8", decode_responses=True)
        return cls._redis

    @classmethod
    def prefix(cls) -> str:
        return settings.APP_PREFIX

    @classmethod
    def room_group(cls, room_id: str) -> str:
        return f"room.{room_id}"

    @classmethod
    def user_group(cls, user_id: str) -> str:
        return f"user.{user_id}"

    @classmethod
    def room_key(cls, room_id: str) -> str:
        return f"{cls.prefix()}:room:{room_id}"

    @classmethod
    def participants_key(cls, room_id: str) -> str:
        return f"{cls.prefix()}:room:{room_id}:participants"

    @classmethod
    def participant_meta_key(cls, room_id: str) -> str:
        return f"{cls.prefix()}:room:{room_id}:participant_meta"

    @classmethod
    def presence_key(cls, room_id: str) -> str:
        return f"{cls.prefix()}:room:{room_id}:presence"

    @classmethod
    def discoverable_rooms_key(cls) -> str:
        return f"{cls.prefix()}:rooms:discoverable"

    @classmethod
    def pending_requests_key(cls, room_id: str) -> str:
        return f"{cls.prefix()}:room:{room_id}:pending_requests"

    @classmethod
    def pending_request_key(cls, room_id: str, request_id: str) -> str:
        return f"{cls.prefix()}:room:{room_id}:join_request:{request_id}"

    @classmethod
    def permit_key(cls, room_id: str, user_id: str) -> str:
        return f"{cls.prefix()}:room:{room_id}:permit:{user_id}"

    @classmethod
    def one_time_images_key(cls, room_id: str) -> str:
        return f"{cls.prefix()}:room:{room_id}:one_time_images"

    @classmethod
    def one_time_image_key(cls, room_id: str, message_id: str) -> str:
        return f"{cls.prefix()}:room:{room_id}:one_time_image:{message_id}"

    @staticmethod
    def utc_now() -> str:
        return datetime.now(UTC).isoformat()

    @staticmethod
    def generate_room_id() -> str:
        return secrets.token_urlsafe(8).replace("-", "").replace("_", "")[:10].upper()

    @classmethod
    async def create_room(cls, owner_id: str, owner_name: str) -> ServiceResult:
        redis = cls.redis()
        for _ in range(6):
            room_id = cls.generate_room_id()
            room_key = cls.room_key(room_id)
            if await redis.exists(room_key):
                continue

            mapping = {
                "id": room_id,
                "owner_id": owner_id,
                "owner_name": owner_name,
                "created_at": cls.utc_now(),
                "discoverable_when_single": "1" if DEFAULT_SINGLE_USER_DISCOVERABLE else "0",
            }
            pipe = redis.pipeline()
            pipe.hset(room_key, mapping=mapping)
            pipe.sadd(cls.participants_key(room_id), owner_id)
            pipe.hset(
                cls.participant_meta_key(room_id),
                owner_id,
                json.dumps(
                    {
                        "user_id": owner_id,
                        "display_name": owner_name,
                        "joined_at": cls.utc_now(),
                    }
                ),
            )
            await pipe.execute()
            snapshot = await cls.get_room_snapshot(room_id)
            return ServiceResult(ok=True, code="created", data={"room": snapshot})

        return ServiceResult(ok=False, code="room_generation_failed")

    @classmethod
    async def list_discoverable_rooms(cls) -> list[dict[str, Any]]:
        redis = cls.redis()
        room_ids = await redis.smembers(cls.discoverable_rooms_key())
        if not room_ids:
            return []

        rooms: list[dict[str, Any]] = []
        stale_room_ids: list[str] = []
        for room_id in sorted(room_ids):
            snapshot = await cls.get_room_snapshot(room_id)
            if not snapshot:
                stale_room_ids.append(room_id)
                continue
            if snapshot["is_visible"]:
                rooms.append(snapshot)
            else:
                stale_room_ids.append(room_id)

        if stale_room_ids:
            await redis.srem(cls.discoverable_rooms_key(), *stale_room_ids)

        return rooms

    @classmethod
    async def get_owner_id(cls, room_id: str) -> str | None:
        return await cls.redis().hget(cls.room_key(room_id), "owner_id")

    @classmethod
    async def get_room_snapshot(cls, room_id: str) -> dict[str, Any] | None:
        redis = cls.redis()
        room_map = await redis.hgetall(cls.room_key(room_id))
        if not room_map:
            return None

        raw_meta = await redis.hgetall(cls.participant_meta_key(room_id))
        raw_presence = await redis.hgetall(cls.presence_key(room_id))

        participants: list[dict[str, Any]] = []
        online_count = 0
        for user_id, payload in raw_meta.items():
            try:
                meta = json.loads(payload)
            except json.JSONDecodeError:
                meta = {"user_id": user_id, "display_name": f"User-{user_id[:4]}"}
            connections = int(raw_presence.get(user_id, "0") or 0)
            is_online = connections > 0
            if is_online:
                online_count += 1
            participants.append(
                {
                    "user_id": meta.get("user_id", user_id),
                    "display_name": meta.get("display_name", f"User-{user_id[:4]}"),
                    "joined_at": meta.get("joined_at"),
                    "is_online": is_online,
                }
            )

        participants.sort(key=lambda user: user["joined_at"] or "")
        discoverable_when_single = room_map.get("discoverable_when_single", "1") == "1"
        is_visible = online_count > 0 and (online_count > 1 or discoverable_when_single)

        return {
            "id": room_map.get("id", room_id),
            "owner_id": room_map.get("owner_id"),
            "owner_name": room_map.get("owner_name"),
            "created_at": room_map.get("created_at"),
            "participants": participants,
            "occupancy": len(participants),
            "online_count": online_count,
            "is_full": len(participants) >= MAX_ROOM_PARTICIPANTS,
            "discoverable_when_single": discoverable_when_single,
            "is_visible": is_visible,
        }

    @classmethod
    async def sync_visibility(cls, room_id: str) -> dict[str, Any] | None:
        redis = cls.redis()
        snapshot = await cls.get_room_snapshot(room_id)
        if not snapshot:
            return None

        discoverable_key = cls.discoverable_rooms_key()
        if snapshot["is_visible"]:
            await redis.sadd(discoverable_key, room_id)
        else:
            await redis.srem(discoverable_key, room_id)

        return snapshot

    @classmethod
    async def connect_participant(cls, room_id: str, user_id: str, display_name: str) -> ServiceResult:
        redis = cls.redis()
        room_key = cls.room_key(room_id)
        room_map = await redis.hgetall(room_key)
        if not room_map:
            return ServiceResult(ok=False, code="room_not_found")

        member_key = cls.participants_key(room_id)
        is_member = await redis.sismember(member_key, user_id)
        is_owner = room_map.get("owner_id") == user_id

        if not is_member:
            if not is_owner and not await redis.exists(cls.permit_key(room_id, user_id)):
                return ServiceResult(ok=False, code="join_not_permitted")
            if (await redis.scard(member_key)) >= MAX_ROOM_PARTICIPANTS:
                return ServiceResult(ok=False, code="room_full")

            meta_payload = json.dumps(
                {
                    "user_id": user_id,
                    "display_name": display_name,
                    "joined_at": cls.utc_now(),
                }
            )
            pipe = redis.pipeline()
            pipe.sadd(member_key, user_id)
            pipe.hset(cls.participant_meta_key(room_id), user_id, meta_payload)
            if not is_owner:
                pipe.delete(cls.permit_key(room_id, user_id))
            await pipe.execute()

        await redis.hset(
            cls.participant_meta_key(room_id),
            user_id,
            json.dumps(
                {
                    "user_id": user_id,
                    "display_name": display_name,
                    "joined_at": cls.utc_now(),
                }
            ),
        )
        await redis.hincrby(cls.presence_key(room_id), user_id, 1)
        await cls.sync_visibility(room_id)

        snapshot = await cls.get_room_snapshot(room_id)
        return ServiceResult(ok=True, code="connected", data={"room": snapshot})

    @classmethod
    async def disconnect_participant(cls, room_id: str, user_id: str) -> ServiceResult:
        redis = cls.redis()
        room_key = cls.room_key(room_id)
        room_map = await redis.hgetall(room_key)
        if not room_map:
            return ServiceResult(ok=True, code="room_missing")

        presence_key = cls.presence_key(room_id)
        remaining = await redis.hincrby(presence_key, user_id, -1)
        if remaining <= 0:
            pipe = redis.pipeline()
            pipe.hdel(presence_key, user_id)
            pipe.srem(cls.participants_key(room_id), user_id)
            pipe.hdel(cls.participant_meta_key(room_id), user_id)
            await pipe.execute()

        snapshot = await cls.get_room_snapshot(room_id)
        if not snapshot:
            return ServiceResult(ok=True, code="room_missing")

        if snapshot["occupancy"] == 0 or snapshot["online_count"] == 0:
            await cls.delete_room(room_id)
            return ServiceResult(ok=True, code="room_deleted", data={"room_id": room_id})

        if room_map.get("owner_id") == user_id and snapshot["participants"]:
            new_owner = snapshot["participants"][0]
            await redis.hset(
                room_key,
                mapping={
                    "owner_id": new_owner["user_id"],
                    "owner_name": new_owner["display_name"],
                },
            )

        await cls.sync_visibility(room_id)
        snapshot = await cls.get_room_snapshot(room_id)
        return ServiceResult(ok=True, code="updated", data={"room": snapshot})

    @classmethod
    async def delete_room(cls, room_id: str) -> None:
        redis = cls.redis()
        request_ids = await redis.smembers(cls.pending_requests_key(room_id))
        image_ids = await redis.smembers(cls.one_time_images_key(room_id))
        pipe = redis.pipeline()
        pipe.srem(cls.discoverable_rooms_key(), room_id)
        pipe.delete(cls.room_key(room_id))
        pipe.delete(cls.participants_key(room_id))
        pipe.delete(cls.participant_meta_key(room_id))
        pipe.delete(cls.presence_key(room_id))
        pipe.delete(cls.pending_requests_key(room_id))
        pipe.delete(cls.one_time_images_key(room_id))
        for request_id in request_ids:
            pipe.delete(cls.pending_request_key(room_id, request_id))
        for image_id in image_ids:
            pipe.delete(cls.one_time_image_key(room_id, image_id))
        await pipe.execute()

    @classmethod
    async def online_user_ids(cls, room_id: str) -> list[str]:
        raw = await cls.redis().hgetall(cls.presence_key(room_id))
        return [user_id for user_id, count in raw.items() if int(count or 0) > 0]

    @classmethod
    async def create_join_request(
        cls,
        room_id: str,
        requester_id: str,
        requester_name: str,
    ) -> ServiceResult:
        redis = cls.redis()
        snapshot = await cls.get_room_snapshot(room_id)
        if not snapshot:
            return ServiceResult(ok=False, code="room_not_found")

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

        pipe = redis.pipeline()
        pipe.set(cls.pending_request_key(room_id, request_id), json.dumps(payload), ex=90)
        pipe.sadd(cls.pending_requests_key(room_id), request_id)
        await pipe.execute()

        return ServiceResult(ok=True, code="request_created", data=payload)

    @classmethod
    async def resolve_join_request(
        cls,
        room_id: str,
        request_id: str,
        approver_id: str,
        approved: bool,
    ) -> ServiceResult:
        redis = cls.redis()
        if not await redis.sismember(cls.participants_key(room_id), approver_id):
            return ServiceResult(ok=False, code="forbidden")

        if approver_id not in await cls.online_user_ids(room_id):
            return ServiceResult(ok=False, code="forbidden")

        req_key = cls.pending_request_key(room_id, request_id)
        raw_payload = await redis.get(req_key)
        if not raw_payload:
            return ServiceResult(ok=False, code="request_not_found")

        payload = json.loads(raw_payload)
        pipe = redis.pipeline()
        pipe.delete(req_key)
        pipe.srem(cls.pending_requests_key(room_id), request_id)

        if not approved:
            await pipe.execute()
            payload["status"] = "rejected"
            return ServiceResult(ok=True, code="request_rejected", data=payload)

        current_count = await redis.scard(cls.participants_key(room_id))
        requester_id = payload["requester_id"]
        if current_count >= MAX_ROOM_PARTICIPANTS and not await redis.sismember(
            cls.participants_key(room_id), requester_id
        ):
            await pipe.execute()
            return ServiceResult(ok=False, code="room_full")

        pipe.set(cls.permit_key(room_id, requester_id), "1", ex=120)
        await pipe.execute()

        payload["status"] = "approved"
        return ServiceResult(ok=True, code="request_approved", data=payload)

    @classmethod
    async def set_discoverable_when_single(
        cls,
        room_id: str,
        user_id: str,
        discoverable_when_single: bool,
    ) -> ServiceResult:
        if not await cls.redis().sismember(cls.participants_key(room_id), user_id):
            return ServiceResult(ok=False, code="forbidden")

        await cls.redis().hset(
            cls.room_key(room_id),
            "discoverable_when_single",
            "1" if discoverable_when_single else "0",
        )
        snapshot = await cls.sync_visibility(room_id)
        return ServiceResult(ok=True, code="updated", data={"room": snapshot})

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
        redis = cls.redis()
        if not await redis.exists(cls.room_key(room_id)):
            return ServiceResult(ok=False, code="room_not_found")
        if not await redis.sismember(cls.participants_key(room_id), sender_id):
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
            "preview_text": (
                "Timed one-time image"
                if view_mode == TIMED_ONE_TIME_IMAGE_MODE
                else "One-time image"
            ),
        }

        pipe = redis.pipeline()
        pipe.set(
            cls.one_time_image_key(room_id, message_id),
            json.dumps(payload),
            ex=cls._ONE_TIME_IMAGE_TTL_SECONDS,
        )
        pipe.sadd(cls.one_time_images_key(room_id), message_id)
        await pipe.execute()

        return ServiceResult(ok=True, code="created", data={"message": cls._image_public_payload(payload)})

    @classmethod
    async def get_one_time_image_for_view(
        cls,
        room_id: str,
        message_id: str,
        viewer_id: str,
    ) -> ServiceResult:
        redis = cls.redis()
        if not await redis.exists(cls.room_key(room_id)):
            return ServiceResult(ok=False, code="room_not_found")
        if not await redis.sismember(cls.participants_key(room_id), viewer_id):
            return ServiceResult(ok=False, code="forbidden")

        key = cls.one_time_image_key(room_id, message_id)
        raw_payload = await redis.get(key)
        if not raw_payload:
            return ServiceResult(ok=False, code="image_not_found")

        payload = json.loads(raw_payload)
        if payload["sender_id"] == viewer_id:
            return ServiceResult(ok=False, code="sender_cannot_open")
        if payload["opened_at"]:
            return ServiceResult(ok=False, code="image_already_opened")

        active_viewer_id = payload.get("active_viewer_id")
        if active_viewer_id and active_viewer_id != viewer_id:
            return ServiceResult(ok=False, code="image_view_in_progress")

        payload["active_viewer_id"] = viewer_id
        payload["active_view_started_at"] = cls.utc_now()
        await redis.set(key, json.dumps(payload), ex=cls._ONE_TIME_IMAGE_TTL_SECONDS)

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
        redis = cls.redis()
        if not await redis.exists(cls.room_key(room_id)):
            return ServiceResult(ok=False, code="room_not_found")
        if not await redis.sismember(cls.participants_key(room_id), viewer_id):
            return ServiceResult(ok=False, code="forbidden")

        key = cls.one_time_image_key(room_id, message_id)
        raw_payload = await redis.get(key)
        if not raw_payload:
            return ServiceResult(ok=False, code="image_not_found")
        payload = json.loads(raw_payload)

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
        await redis.set(key, json.dumps(payload), ex=cls._ONE_TIME_IMAGE_TTL_SECONDS)

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
