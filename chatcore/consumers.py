from __future__ import annotations

import base64
import binascii
import hashlib
import re
import secrets
from collections.abc import Callable
from typing import Any

from asgiref.sync import sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer

from .constants import (
    ALLOWED_ONE_TIME_IMAGE_MIME_TYPES,
    LOBBY_GROUP,
    MAX_ONE_TIME_IMAGE_BYTES,
    MAX_ONE_TIME_IMAGE_VIEW_SECONDS,
    ONE_TIME_IMAGE_MODE,
    SESSION_USER_ID,
    SESSION_USER_NAME,
    TIMED_ONE_TIME_IMAGE_MODE,
)
from .services.backend import RoomStateService
from .services.chat_store import ChatStore
from .services.user_store import UserStore

ONE_TIME_IMAGE_DATA_URL_RE = re.compile(
    r"^data:(?P<mime>image\/[a-zA-Z0-9.+-]+);base64,(?P<data>[A-Za-z0-9+/=\s]+)$"
)


class BaseConsumer(AsyncJsonWebsocketConsumer):
    user_id: str
    user_name: str

    async def init_identity(self) -> bool:
        session = self.scope.get("session")
        if not session:
            return False

        user_id = session.get(SESSION_USER_ID)
        user_name = session.get(SESSION_USER_NAME)
        if not user_id or not user_name:
            return False

        self.user_id = str(user_id)
        self.user_name = str(user_name)
        return True

    async def send_error(self, code: str, message: str) -> None:
        await self.send_json({"type": "error", "code": code, "message": message})

    async def safe_action(self, fn: Callable[..., Any], payload: dict[str, Any]) -> None:
        try:
            await fn(payload)
        except Exception as exc:  # pragma: no cover - defensive runtime guard
            await self.send_error("internal_error", str(exc))


class LobbyConsumer(BaseConsumer):
    personal_group: str

    async def connect(self) -> None:
        has_identity = await self.init_identity()
        if not has_identity:
            await self.close(code=4401)
            return

        self.personal_group = RoomStateService.user_group(self.user_id)

        await self.channel_layer.group_add(LOBBY_GROUP, self.channel_name)
        await self.channel_layer.group_add(self.personal_group, self.channel_name)

        await self.accept()

        rooms = await RoomStateService.list_discoverable_rooms()
        await self.send_json(
            {
                "type": "lobby_init",
                "rooms": rooms,
                "self": {
                    "user_id": self.user_id,
                    "display_name": self.user_name,
                },
            }
        )

    async def disconnect(self, code: int) -> None:
        await self.channel_layer.group_discard(LOBBY_GROUP, self.channel_name)
        await self.channel_layer.group_discard(self.personal_group, self.channel_name)

    async def receive_json(self, content: dict[str, Any], **kwargs: Any) -> None:
        action = content.get("action")

        actions = {
            "create_room": self.handle_create_room,
            "join_room_request": self.handle_join_room_request,
            "ping": self.handle_ping,
        }
        handler = actions.get(action)
        if not handler:
            await self.send_error("unknown_action", "Unsupported action")
            return

        await self.safe_action(handler, content)

    async def handle_ping(self, _: dict[str, Any]) -> None:
        await self.send_json({"type": "pong"})

    async def handle_create_room(self, _: dict[str, Any]) -> None:
        result = await RoomStateService.create_room(self.user_id, self.user_name)
        if not result.ok:
            await self.send_error(result.code, "Unable to create room")
            return

        room = result.data["room"]
        await self.send_json(
            {
                "type": "room_created",
                "room": room,
                "redirect_url": f"/room/{room['id']}/",
            }
        )

    async def handle_join_room_request(self, payload: dict[str, Any]) -> None:
        room_id = str(payload.get("room_id", "")).upper()
        result = await RoomStateService.create_join_request(room_id, self.user_id, self.user_name)
        if not result.ok:
            await self.send_error(result.code, "Could not request room access")
            return

        request_payload = result.data
        await self.channel_layer.group_send(
            RoomStateService.room_group(room_id),
            {
                "type": "join.requested",
                "payload": request_payload,
            },
        )
        await self.send_json({"type": "join_request_sent", "payload": request_payload})

    async def lobby_room_update(self, event: dict[str, Any]) -> None:
        await self.send_json({"type": "lobby_room_update", "room": event["room"]})

    async def lobby_room_remove(self, event: dict[str, Any]) -> None:
        await self.send_json({"type": "lobby_room_remove", "room_id": event["room_id"]})

    async def user_notification(self, event: dict[str, Any]) -> None:
        await self.send_json({"type": "notification", "payload": event["payload"]})


class RoomConsumer(BaseConsumer):
    room_id: str
    room_group: str

    async def connect(self) -> None:
        self.connected = False
        has_identity = await self.init_identity()
        if not has_identity:
            await self.close(code=4401)
            return

        self.room_id = self.scope["url_route"]["kwargs"]["room_id"].upper()
        self.room_group = RoomStateService.room_group(self.room_id)

        result = await RoomStateService.connect_participant(
            self.room_id,
            self.user_id,
            self.user_name,
        )
        if not result.ok:
            await self.close(code=4403)
            return

        await self.channel_layer.group_add(self.room_group, self.channel_name)
        await self.accept()
        self.connected = True

        room = result.data["room"]
        history = await sync_to_async(ChatStore.list_room_messages, thread_sensitive=False)(
            self.room_id,
            80,
        )

        await self.send_json(
            {
                "type": "room_init",
                "room": room,
                "messages": history,
                "self": {
                    "user_id": self.user_id,
                    "display_name": self.user_name,
                },
            }
        )

        await self.channel_layer.group_send(
            self.room_group,
            {
                "type": "room.presence",
                "room": room,
                "actor_id": self.user_id,
            },
        )
        await self.channel_layer.group_send(
            self.room_group,
            {
                "type": "chat.participant_joined",
                "payload": {
                    "user_id": self.user_id,
                    "display_name": self.user_name,
                },
            },
        )
        await self.emit_lobby_state(room)

    async def disconnect(self, close_code: int) -> None:
        if not getattr(self, "connected", False):
            return

        await self.channel_layer.group_discard(self.room_group, self.channel_name)
        result = await RoomStateService.disconnect_participant(self.room_id, self.user_id)

        if result.code == "room_deleted":
            await self.channel_layer.group_send(
                LOBBY_GROUP,
                {
                    "type": "lobby.room.remove",
                    "room_id": self.room_id,
                },
            )
            return

        room = result.data.get("room") if result.data else None
        if room:
            await self.channel_layer.group_send(
                self.room_group,
                {
                    "type": "chat.participant_left",
                    "payload": {
                        "user_id": self.user_id,
                        "display_name": self.user_name,
                    },
                },
            )
            await self.channel_layer.group_send(
                self.room_group,
                {
                    "type": "room.presence",
                    "room": room,
                    "actor_id": self.user_id,
                },
            )
            await self.emit_lobby_state(room)

    async def receive_json(self, content: dict[str, Any], **kwargs: Any) -> None:
        action = content.get("action")

        actions = {
            "message_send": self.handle_message_send,
            "image_send": self.handle_image_send,
            "image_open": self.handle_image_open,
            "image_close": self.handle_image_close,
            "message_read": self.handle_message_read,
            "typing": self.handle_typing,
            "join_decision": self.handle_join_decision,
            "set_discoverable_single": self.handle_discoverability,
            "ping": self.handle_ping,
        }
        handler = actions.get(action)
        if not handler:
            await self.send_error("unknown_action", "Unsupported action")
            return

        await self.safe_action(handler, content)

    async def handle_ping(self, _: dict[str, Any]) -> None:
        await self.send_json({"type": "pong"})

    async def handle_message_send(self, payload: dict[str, Any]) -> None:
        text = (payload.get("message") or "").strip()
        if not text:
            return
        if len(text) > 2000:
            await self.send_error("message_too_long", "Max 2000 characters")
            return

        reply_to = self._sanitize_reply(payload.get("reply_to"))

        message_id = secrets.token_urlsafe(10)
        event_payload = {
            "id": message_id,
            "message_type": "text",
            "body": text,
            "sender_id": self.user_id,
            "sender_name": self.user_name,
            "sent_at": RoomStateService.utc_now(),
            "reply_to": reply_to,
        }

        await sync_to_async(ChatStore.save_room_message, thread_sensitive=False)(
            self.room_id,
            event_payload,
        )

        await self.channel_layer.group_send(
            self.room_group,
            {
                "type": "chat.message",
                "payload": event_payload,
            },
        )

        online_users = await RoomStateService.online_user_ids(self.room_id)
        recipient_ids = [uid for uid in online_users if uid != self.user_id]
        if recipient_ids:
            await self.send_json(
                {
                    "type": "message_status",
                    "status": "delivered",
                    "message_id": message_id,
                    "recipient_ids": recipient_ids,
                }
            )

    async def handle_image_send(self, payload: dict[str, Any]) -> None:
        parsed_image = self._parse_one_time_image(payload)
        if not parsed_image:
            await self.send_error("invalid_image_payload", "Unsupported image format or size")
            return

        view_mode = str(payload.get("view_mode") or ONE_TIME_IMAGE_MODE)
        if view_mode not in {ONE_TIME_IMAGE_MODE, TIMED_ONE_TIME_IMAGE_MODE}:
            await self.send_error("invalid_view_mode", "Unsupported one-time image mode")
            return

        view_seconds: int | None = None
        if view_mode == TIMED_ONE_TIME_IMAGE_MODE:
            raw_seconds = payload.get("view_seconds")
            try:
                view_seconds = int(raw_seconds)
            except (TypeError, ValueError):
                await self.send_error("invalid_view_seconds", "Provide viewing time in seconds")
                return
            if not (1 <= view_seconds <= MAX_ONE_TIME_IMAGE_VIEW_SECONDS):
                await self.send_error(
                    "invalid_view_seconds",
                    f"Viewing time must be 1-{MAX_ONE_TIME_IMAGE_VIEW_SECONDS} seconds",
                )
                return

        result = await RoomStateService.create_one_time_image(
            self.room_id,
            self.user_id,
            self.user_name,
            parsed_image["data_url"],
            parsed_image["mime_type"],
            view_mode,
            view_seconds,
        )
        if not result.ok:
            await self.send_error(result.code, "Unable to send one-time image")
            return

        message = result.data["message"]
        await sync_to_async(ChatStore.save_room_message, thread_sensitive=False)(
            self.room_id,
            message,
        )
        await self.channel_layer.group_send(
            self.room_group,
            {
                "type": "chat.message",
                "payload": message,
            },
        )

        online_users = await RoomStateService.online_user_ids(self.room_id)
        recipient_ids = [uid for uid in online_users if uid != self.user_id]
        if recipient_ids:
            await self.send_json(
                {
                    "type": "message_status",
                    "status": "delivered",
                    "message_id": message["id"],
                    "recipient_ids": recipient_ids,
                }
            )

    async def handle_image_open(self, payload: dict[str, Any]) -> None:
        message_id = str(payload.get("message_id", "")).strip()
        if not message_id:
            await self.send_error("invalid_request", "Missing image id")
            return

        result = await RoomStateService.get_one_time_image_for_view(
            self.room_id,
            message_id,
            self.user_id,
        )
        if not result.ok:
            await self.send_error(result.code, "Unable to open one-time image")
            return

        await self.send_json(
            {
                "type": "image_open_result",
                "message": result.data["message"],
                "view": result.data["view"],
            }
        )

    async def handle_image_close(self, payload: dict[str, Any]) -> None:
        message_id = str(payload.get("message_id", "")).strip()
        if not message_id:
            await self.send_error("invalid_request", "Missing image id")
            return

        result = await RoomStateService.consume_one_time_image(
            self.room_id,
            message_id,
            self.user_id,
        )
        if not result.ok:
            await self.send_error(result.code, "Unable to close one-time image")
            return

        message = result.data["message"]
        if result.code == "already_opened":
            await self.send_json({"type": "image_opened", "payload": message})
            return

        await self.channel_layer.group_send(
            self.room_group,
            {
                "type": "chat.image_opened",
                "payload": message,
            },
        )

    async def handle_message_read(self, payload: dict[str, Any]) -> None:
        message_id = payload.get("message_id")
        if not message_id:
            return

        await self.channel_layer.group_send(
            self.room_group,
            {
                "type": "chat.message_read",
                "payload": {
                    "message_id": message_id,
                    "reader_id": self.user_id,
                    "reader_name": self.user_name,
                    "read_at": RoomStateService.utc_now(),
                },
            },
        )

    async def handle_typing(self, payload: dict[str, Any]) -> None:
        is_typing = bool(payload.get("is_typing"))
        await self.channel_layer.group_send(
            self.room_group,
            {
                "type": "chat.typing",
                "payload": {
                    "user_id": self.user_id,
                    "display_name": self.user_name,
                    "is_typing": is_typing,
                },
            },
        )

    async def handle_join_decision(self, payload: dict[str, Any]) -> None:
        request_id = payload.get("request_id")
        approved = bool(payload.get("approved"))
        if not request_id:
            await self.send_error("invalid_request", "Missing request id")
            return

        result = await RoomStateService.resolve_join_request(
            self.room_id,
            request_id,
            self.user_id,
            approved,
        )
        if not result.ok:
            await self.send_error(result.code, "Unable to resolve request")
            return

        join_payload = result.data
        target_user_group = RoomStateService.user_group(join_payload["requester_id"])
        await self.channel_layer.group_send(
            target_user_group,
            {
                "type": "user.notification",
                "payload": {
                    "kind": "join_decision",
                    "status": join_payload["status"],
                    "room_id": self.room_id,
                    "room_url": f"/room/{self.room_id}/",
                    "request_id": request_id,
                },
            },
        )

        await self.send_json({"type": "join_decision_applied", "payload": join_payload})

    async def handle_discoverability(self, payload: dict[str, Any]) -> None:
        discoverable = bool(payload.get("discoverable_when_single"))
        result = await RoomStateService.set_discoverable_when_single(
            self.room_id,
            self.user_id,
            discoverable,
        )
        if not result.ok:
            await self.send_error(result.code, "Unable to update setting")
            return

        room = result.data["room"]
        await self.channel_layer.group_send(
            self.room_group,
            {
                "type": "room.presence",
                "room": room,
                "actor_id": self.user_id,
            },
        )
        await self.emit_lobby_state(room)

    async def emit_lobby_state(self, room: dict[str, Any]) -> None:
        if room["is_visible"]:
            await self.channel_layer.group_send(
                LOBBY_GROUP,
                {
                    "type": "lobby.room.update",
                    "room": room,
                },
            )
            return

        await self.channel_layer.group_send(
            LOBBY_GROUP,
            {
                "type": "lobby.room.remove",
                "room_id": room["id"],
            },
        )

    async def room_presence(self, event: dict[str, Any]) -> None:
        await self.send_json(
            {
                "type": "room_presence",
                "room": event["room"],
                "actor_id": event.get("actor_id"),
            }
        )

    async def join_requested(self, event: dict[str, Any]) -> None:
        await self.send_json({"type": "join_requested", "payload": event["payload"]})

    async def chat_message(self, event: dict[str, Any]) -> None:
        payload = event["payload"]
        await self.send_json(
            {
                "type": "message_new",
                "payload": payload,
                "is_self": payload["sender_id"] == self.user_id,
            }
        )

    async def chat_message_read(self, event: dict[str, Any]) -> None:
        payload = event["payload"]
        await self.send_json(
            {
                "type": "message_status",
                "status": "read",
                "message_id": payload["message_id"],
                "reader_id": payload["reader_id"],
                "read_at": payload["read_at"],
            }
        )

    async def chat_typing(self, event: dict[str, Any]) -> None:
        await self.send_json({"type": "typing", "payload": event["payload"]})

    async def chat_participant_joined(self, event: dict[str, Any]) -> None:
        await self.send_json({"type": "participant_joined", "payload": event["payload"]})

    async def chat_participant_left(self, event: dict[str, Any]) -> None:
        await self.send_json({"type": "participant_left", "payload": event["payload"]})

    async def chat_image_opened(self, event: dict[str, Any]) -> None:
        await self.send_json({"type": "image_opened", "payload": event["payload"]})

    @staticmethod
    def _sanitize_reply(reply_to_raw: Any) -> dict[str, str] | None:
        if not isinstance(reply_to_raw, dict):
            return None
        reply_id = str(reply_to_raw.get("id", "")).strip()
        reply_sender_name = str(reply_to_raw.get("sender_name", "")).strip()
        reply_body = str(reply_to_raw.get("body", "")).strip()
        if reply_id and reply_sender_name and reply_body:
            return {
                "id": reply_id[:64],
                "sender_name": reply_sender_name[:40],
                "body": reply_body[:220],
            }
        return None

    @staticmethod
    def _parse_one_time_image(payload: dict[str, Any]) -> dict[str, str] | None:
        raw_data_url = str(payload.get("image_data_url") or "").strip()
        if not raw_data_url:
            return None
        match = ONE_TIME_IMAGE_DATA_URL_RE.match(raw_data_url)
        if not match:
            return None

        mime_type = match.group("mime").lower()
        if mime_type not in ALLOWED_ONE_TIME_IMAGE_MIME_TYPES:
            return None

        raw_base64 = "".join(match.group("data").split())
        try:
            image_bytes = base64.b64decode(raw_base64, validate=True)
        except (ValueError, binascii.Error):
            return None
        if len(image_bytes) > MAX_ONE_TIME_IMAGE_BYTES:
            return None

        return {
            "mime_type": mime_type,
            "data_url": f"data:{mime_type};base64,{raw_base64}",
        }


class DMConsumer(BaseConsumer):
    personal_group: str
    joined_threads: set[str]

    @staticmethod
    def dm_user_group(user_id: str) -> str:
        return f"dm.user.{user_id}"

    @staticmethod
    def dm_thread_group(thread_key: str) -> str:
        # Channels group names cannot contain ":"; use a stable ASCII-safe digest.
        digest = hashlib.sha1(thread_key.encode("utf-8")).hexdigest()
        return f"dm.thread.{digest}"

    async def connect(self) -> None:
        self.personal_group = ""
        self.joined_threads = set()

        has_identity = await self.init_identity()
        if not has_identity:
            await self.close(code=4401)
            return

        self.personal_group = self.dm_user_group(self.user_id)

        await self.channel_layer.group_add(self.personal_group, self.channel_name)
        await self.accept()

        conversations = await sync_to_async(ChatStore.list_conversations, thread_sensitive=False)(
            self.user_id,
            40,
        )
        await self.send_json(
            {
                "type": "dm_bootstrap",
                "self": {
                    "user_id": self.user_id,
                    "username": self.user_name,
                },
                "conversations": conversations,
            }
        )

    async def disconnect(self, close_code: int) -> None:
        if getattr(self, "personal_group", ""):
            await self.channel_layer.group_discard(self.personal_group, self.channel_name)
        for group in list(getattr(self, "joined_threads", set())):
            await self.channel_layer.group_discard(group, self.channel_name)

    async def receive_json(self, content: dict[str, Any], **kwargs: Any) -> None:
        action = content.get("action")
        actions = {
            "search_users": self.handle_search_users,
            "open_thread": self.handle_open_thread,
            "dm_send": self.handle_send_dm,
            "mark_thread_read": self.handle_mark_read,
            "ping": self.handle_ping,
        }
        handler = actions.get(action)
        if not handler:
            await self.send_error("unknown_action", "Unsupported action")
            return

        await self.safe_action(handler, content)

    async def handle_ping(self, _: dict[str, Any]) -> None:
        await self.send_json({"type": "pong"})

    async def handle_search_users(self, payload: dict[str, Any]) -> None:
        query = str(payload.get("query") or "").strip()
        if not query:
            await self.send_json({"type": "search_results", "query": query, "results": []})
            return

        results = await sync_to_async(UserStore.search_users_by_prefix, thread_sensitive=False)(
            query,
            self.user_id,
            14,
        )
        await self.send_json({"type": "search_results", "query": query, "results": results})

    async def handle_open_thread(self, payload: dict[str, Any]) -> None:
        peer_user_id = str(payload.get("peer_user_id") or "").strip()
        peer_username = str(payload.get("peer_username") or "").strip()

        peer = None
        if peer_user_id:
            peer = await sync_to_async(UserStore.get_user_by_id, thread_sensitive=False)(peer_user_id)
        elif peer_username:
            peer = await sync_to_async(UserStore.get_user_by_username, thread_sensitive=False)(peer_username)

        if not peer:
            await self.send_error("user_not_found", "User not found")
            return
        if peer["user_id"] == self.user_id:
            await self.send_error("invalid_target", "You cannot chat with yourself")
            return

        history_result = await sync_to_async(ChatStore.list_dm_messages, thread_sensitive=False)(
            self.user_id,
            peer["user_id"],
            90,
        )
        if not history_result.ok:
            await self.send_error(history_result.code, "Unable to open chat")
            return

        thread_key = history_result.data["thread_key"]
        thread_group = self.dm_thread_group(thread_key)
        if thread_group not in self.joined_threads:
            await self.channel_layer.group_add(thread_group, self.channel_name)
            self.joined_threads.add(thread_group)

        await sync_to_async(ChatStore.mark_thread_read, thread_sensitive=False)(self.user_id, peer["user_id"])

        await self.send_json(
            {
                "type": "thread_opened",
                "thread_key": thread_key,
                "peer": {
                    "user_id": peer["user_id"],
                    "username": peer["username"],
                },
                "messages": history_result.data["messages"],
            }
        )

        await self._send_conversations()

    async def handle_send_dm(self, payload: dict[str, Any]) -> None:
        peer_user_id = str(payload.get("peer_user_id") or "").strip()
        if not peer_user_id:
            await self.send_error("invalid_target", "Missing chat partner")
            return

        result = await sync_to_async(ChatStore.send_dm_message, thread_sensitive=False)(
            self.user_id,
            peer_user_id,
            str(payload.get("message") or ""),
        )
        if not result.ok:
            await self.send_error(result.code, "Unable to send message")
            return

        message = result.data["message"]
        thread_group = self.dm_thread_group(message["thread_key"])
        if thread_group not in self.joined_threads:
            await self.channel_layer.group_add(thread_group, self.channel_name)
            self.joined_threads.add(thread_group)

        await self.channel_layer.group_send(
            thread_group,
            {
                "type": "dm.message",
                "payload": message,
            },
        )

        await self.channel_layer.group_send(
            self.dm_user_group(self.user_id),
            {
                "type": "dm.conversations.refresh",
            },
        )
        await self.channel_layer.group_send(
            self.dm_user_group(peer_user_id),
            {
                "type": "dm.conversations.refresh",
            },
        )

    async def handle_mark_read(self, payload: dict[str, Any]) -> None:
        peer_user_id = str(payload.get("peer_user_id") or "").strip()
        if not peer_user_id:
            return
        await sync_to_async(ChatStore.mark_thread_read, thread_sensitive=False)(self.user_id, peer_user_id)
        await self._send_conversations()

    async def dm_message(self, event: dict[str, Any]) -> None:
        payload = event["payload"]
        await self.send_json(
            {
                "type": "dm_message",
                "payload": payload,
                "is_self": payload["sender_id"] == self.user_id,
            }
        )

    async def dm_conversations_refresh(self, event: dict[str, Any]) -> None:
        await self._send_conversations()

    async def _send_conversations(self) -> None:
        conversations = await sync_to_async(ChatStore.list_conversations, thread_sensitive=False)(
            self.user_id,
            40,
        )
        await self.send_json({"type": "conversations", "items": conversations})
