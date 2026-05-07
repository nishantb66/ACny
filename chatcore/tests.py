from django.test import Client, SimpleTestCase

from .constants import SESSION_USER_ID, SESSION_USER_NAME, TIMED_ONE_TIME_IMAGE_MODE
from .services.memory_store import RoomStateService


class HealthTests(SimpleTestCase):
    def test_health_endpoint(self):
        response = self.client.get("/healthz/")
        self.assertEqual(response.status_code, 200)


class OneTimeImageFlowTests(SimpleTestCase):
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

    @staticmethod
    def async_run(awaitable):
        import asyncio

        return asyncio.run(awaitable)

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

    def test_timed_one_time_image_carries_duration(self):
        created = self.async_run(RoomStateService.create_room("owner-1", "Owner One"))
        room_id = created.data["room"]["id"]

        sent = self.async_run(
            RoomStateService.create_one_time_image(
                room_id,
                "owner-1",
                "Owner One",
                "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO2P/qoAAAAASUVORK5CYII=",
                "image/png",
                TIMED_ONE_TIME_IMAGE_MODE,
                30,
            )
        )
        self.assertTrue(sent.ok, sent.code)
        self.assertEqual(sent.data["message"]["view_seconds"], 30)


class DirectInviteFlowTests(SimpleTestCase):
    @staticmethod
    def async_run(awaitable):
        import asyncio

        return asyncio.run(awaitable)

    def setUp(self):
        RoomStateService._rooms = {}
        RoomStateService._invite_tokens = {}

    def test_whatsapp_invite_link_redirects_directly_to_room(self):
        self.client.get("/")
        owner_session = self.client.session
        owner_id = owner_session[SESSION_USER_ID]
        owner_name = owner_session[SESSION_USER_NAME]

        created = self.async_run(RoomStateService.create_room(owner_id, owner_name))
        room_id = created.data["room"]["id"]

        invite_resp = self.client.post(f"/api/room/{room_id}/invite/")
        self.assertEqual(invite_resp.status_code, 200)
        invite_url = invite_resp.json()["invite_url"]

        guest_client = Client()
        response = guest_client.get(invite_url)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, f"/room/{room_id}/")

    def test_direct_invite_is_single_use(self):
        self.client.get("/")
        owner_id = self.client.session[SESSION_USER_ID]
        owner_name = self.client.session[SESSION_USER_NAME]
        created = self.async_run(RoomStateService.create_room(owner_id, owner_name))
        room_id = created.data["room"]["id"]

        invite_resp = self.client.post(f"/api/room/{room_id}/invite/")
        invite_url = invite_resp.json()["invite_url"]

        first_guest = Client()
        first_redirect = first_guest.get(invite_url)
        self.assertEqual(first_redirect.status_code, 302)
        self.assertEqual(first_redirect.url, f"/room/{room_id}/")

        second_guest = Client()
        second_redirect = second_guest.get(invite_url)
        self.assertEqual(second_redirect.status_code, 302)
        self.assertEqual(second_redirect.url, "/?invite_error=invite_not_found")
