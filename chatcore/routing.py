from django.urls import re_path

from . import consumers

websocket_urlpatterns = [
    re_path(r"ws/lobby/$", consumers.LobbyConsumer.as_asgi()),
    re_path(r"ws/room/(?P<room_id>[A-Z0-9_-]{6,20})/$", consumers.RoomConsumer.as_asgi()),
]
