from django.urls import path

from chatcore import views

urlpatterns = [
    path("", views.lobby, name="lobby"),
    path("room/<str:room_id>/", views.room, name="room"),
    path("invite/<str:token>/", views.accept_direct_invite, name="accept_direct_invite"),
    path("api/room/<str:room_id>/invite/", views.create_whatsapp_invite, name="create_whatsapp_invite"),
    path("identity/update/", views.update_identity, name="update_identity"),
    path("healthz/", views.healthz, name="healthz"),
]
