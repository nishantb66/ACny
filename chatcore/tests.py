import re

from django.test import SimpleTestCase

from .consumers import DMConsumer
from .services.memory_store import RoomStateService


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
