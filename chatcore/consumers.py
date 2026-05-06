from __future__ import annotations

import secrets
from collections.abc import Callable
from typing import Any

from channels.generic.websocket import AsyncJsonWebsocketConsumer

from .constants import LOBBY_GROUP, SESSION_USER_ID, SESSION_USER_NAME
from .services.backend import RoomStateService


class BaseConsumer(AsyncJsonWebsocketConsumer):
    user_id: str
    user_name: str

    async def init_identity(self) -> None:
        session = self.scope["session"]
        self.user_id = session.get(SESSION_USER_ID) or secrets.token_urlsafe(10)
        self.user_name = session.get(SESSION_USER_NAME) or f"Guest-{self.user_id[:4].upper()}"

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
        await self.init_identity()
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
        await self.init_identity()
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
        await self.send_json(
            {
                "type": "room_init",
                "room": room,
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

        reply_to_raw = payload.get("reply_to") or None
        reply_to = None
        if isinstance(reply_to_raw, dict):
            reply_id = str(reply_to_raw.get("id", "")).strip()
            reply_sender_name = str(reply_to_raw.get("sender_name", "")).strip()
            reply_body = str(reply_to_raw.get("body", "")).strip()
            if reply_id and reply_sender_name and reply_body:
                reply_to = {
                    "id": reply_id[:64],
                    "sender_name": reply_sender_name[:40],
                    "body": reply_body[:220],
                }

        message_id = secrets.token_urlsafe(10)
        event_payload = {
            "id": message_id,
            "body": text,
            "sender_id": self.user_id,
            "sender_name": self.user_name,
            "sent_at": RoomStateService.utc_now(),
            "reply_to": reply_to,
        }

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
