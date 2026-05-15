from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from bson import ObjectId
from pymongo.errors import PyMongoError

from .mongo_client import MongoStore, utc_now
from .user_store import UserStore


@dataclass(slots=True)
class ChatResult:
    ok: bool
    code: str
    data: dict[str, Any] | None = None


class ChatStore:
    @staticmethod
    def thread_key(user_a: str, user_b: str) -> str:
        left, right = sorted([user_a, user_b])
        return f"{left}:{right}"

    @classmethod
    def save_room_message(cls, room_id: str, payload: dict[str, Any]) -> None:
        message_type = payload.get("message_type")
        if message_type not in {"text", "one_time_image"}:
            return

        body = payload.get("body", "")
        normalized_type = "text"
        if message_type == "one_time_image":
            body = payload.get("preview_text") or "One-time image"

        try:
            MongoStore.room_messages().insert_one(
                {
                    "room_id": room_id,
                    "message_id": payload.get("id"),
                    "message_type": normalized_type,
                    "body": body,
                    "sender_id": payload.get("sender_id"),
                    "sender_username": payload.get("sender_name"),
                    "sent_at": utc_now(),
                    "reply_to": payload.get("reply_to"),
                }
            )
        except PyMongoError:
            return

    @classmethod
    def list_room_messages(cls, room_id: str, limit: int = 60) -> list[dict[str, Any]]:
        try:
            docs = (
                MongoStore.room_messages()
                .find({"room_id": room_id})
                .sort([("sent_at", -1), ("_id", -1)])
                .limit(max(1, min(limit, 200)))
            )
        except PyMongoError:
            return []

        messages = []
        for doc in docs:
            messages.append(
                {
                    "id": doc.get("message_id") or str(doc.get("_id")),
                    "message_type": doc.get("message_type", "text"),
                    "body": doc.get("body", ""),
                    "sender_id": doc.get("sender_id"),
                    "sender_name": doc.get("sender_username", "Unknown"),
                    "sent_at": cls._to_iso(doc.get("sent_at")),
                    "reply_to": doc.get("reply_to"),
                }
            )
        messages.reverse()
        return messages

    @classmethod
    def send_dm_message(
        cls,
        sender_id: str,
        recipient_id: str,
        body: str,
    ) -> ChatResult:
        sender = UserStore.get_user_by_id(sender_id)
        recipient = UserStore.get_user_by_id(recipient_id)
        if not sender or not recipient:
            return ChatResult(ok=False, code="user_not_found")

        clean = (body or "").strip()
        if not clean:
            return ChatResult(ok=False, code="empty_message")
        if len(clean) > 2000:
            return ChatResult(ok=False, code="message_too_long")

        sent_at = utc_now()
        thread_key = cls.thread_key(sender_id, recipient_id)
        doc = {
            "thread_key": thread_key,
            "participants": sorted([sender_id, recipient_id]),
            "sender_id": sender_id,
            "recipient_id": recipient_id,
            "body": clean,
            "sent_at": sent_at,
            "read_at": None,
        }
        try:
            inserted = MongoStore.dm_messages().insert_one(doc)
        except PyMongoError:
            return ChatResult(ok=False, code="database_error")

        message = {
            "id": str(inserted.inserted_id),
            "thread_key": thread_key,
            "sender_id": sender_id,
            "sender_username": sender["username"],
            "recipient_id": recipient_id,
            "recipient_username": recipient["username"],
            "body": clean,
            "sent_at": sent_at.isoformat(),
            "read_at": None,
        }

        return ChatResult(ok=True, code="sent", data={"message": message})

    @classmethod
    def list_dm_messages(cls, user_id: str, peer_id: str, limit: int = 80) -> ChatResult:
        if not UserStore.get_user_by_id(user_id) or not UserStore.get_user_by_id(peer_id):
            return ChatResult(ok=False, code="user_not_found")

        thread_key = cls.thread_key(user_id, peer_id)
        try:
            docs = (
                MongoStore.dm_messages()
                .find({"thread_key": thread_key})
                .sort([("sent_at", -1), ("_id", -1)])
                .limit(max(1, min(limit, 200)))
            )
        except PyMongoError:
            return ChatResult(ok=False, code="database_error")

        messages = [cls._serialize_dm_message(doc) for doc in docs]
        messages.reverse()
        return ChatResult(ok=True, code="ok", data={"thread_key": thread_key, "messages": messages})

    @classmethod
    def mark_thread_read(cls, user_id: str, peer_id: str) -> int:
        now = utc_now()
        try:
            result = MongoStore.dm_messages().update_many(
                {
                    "thread_key": cls.thread_key(user_id, peer_id),
                    "recipient_id": user_id,
                    "read_at": None,
                },
                {
                    "$set": {
                        "read_at": now,
                    }
                },
            )
        except PyMongoError:
            return 0
        return int(result.modified_count)

    @classmethod
    def list_conversations(cls, user_id: str, limit: int = 40) -> list[dict[str, Any]]:
        pipeline = [
            {"$match": {"participants": user_id}},
            {"$sort": {"sent_at": -1, "_id": -1}},
            {
                "$group": {
                    "_id": "$thread_key",
                    "latest": {"$first": "$$ROOT"},
                    "unread_count": {
                        "$sum": {
                            "$cond": [
                                {
                                    "$and": [
                                        {"$eq": ["$recipient_id", user_id]},
                                        {"$eq": ["$read_at", None]},
                                    ]
                                },
                                1,
                                0,
                            ]
                        }
                    },
                }
            },
            {"$sort": {"latest.sent_at": -1, "latest._id": -1}},
            {"$limit": max(1, min(limit, 100))},
        ]

        try:
            rows = list(MongoStore.dm_messages().aggregate(pipeline))
        except PyMongoError:
            return []

        peer_ids: set[str] = set()
        for row in rows:
            participants = row["latest"].get("participants", [])
            peer = participants[0] if participants and participants[0] != user_id else None
            if len(participants) == 2 and not peer:
                peer = participants[1]
            if peer:
                peer_ids.add(peer)

        peers = cls._load_users(peer_ids)

        conversations: list[dict[str, Any]] = []
        for row in rows:
            latest = row["latest"]
            participants = latest.get("participants", [])
            peer_id = participants[0] if participants and participants[0] != user_id else None
            if len(participants) == 2 and not peer_id:
                peer_id = participants[1]
            if not peer_id:
                continue

            peer = peers.get(peer_id)
            if not peer:
                continue

            conversations.append(
                {
                    "thread_key": row["_id"],
                    "peer": {
                        "user_id": peer_id,
                        "username": peer.get("username", "Unknown"),
                    },
                    "last_message": {
                        "body": latest.get("body", ""),
                        "sender_id": latest.get("sender_id"),
                        "sent_at": cls._to_iso(latest.get("sent_at")),
                    },
                    "unread_count": int(row.get("unread_count", 0)),
                }
            )

        return conversations

    @classmethod
    def _load_users(cls, user_ids: set[str]) -> dict[str, dict[str, Any]]:
        object_ids = [ObjectId(raw) for raw in user_ids if ObjectId.is_valid(raw)]
        if not object_ids:
            return {}
        try:
            docs = MongoStore.users().find({"_id": {"$in": object_ids}}, {"username": 1})
        except PyMongoError:
            return {}
        return {str(doc["_id"]): {"username": doc.get("username", "Unknown")} for doc in docs}

    @classmethod
    def _serialize_dm_message(cls, doc: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": str(doc.get("_id")),
            "thread_key": doc.get("thread_key"),
            "sender_id": doc.get("sender_id"),
            "recipient_id": doc.get("recipient_id"),
            "body": doc.get("body", ""),
            "sent_at": cls._to_iso(doc.get("sent_at")),
            "read_at": cls._to_iso(doc.get("read_at")),
        }

    @staticmethod
    def _to_iso(value: Any) -> str | None:
        if value is None:
            return None
        iso = getattr(value, "isoformat", None)
        if callable(iso):
            return iso()
        return str(value)
