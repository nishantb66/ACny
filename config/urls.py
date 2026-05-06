from django.urls import path

from chatcore import views

urlpatterns = [
    path("", views.lobby, name="lobby"),
    path("room/<str:room_id>/", views.room, name="room"),
    path("identity/update/", views.update_identity, name="update_identity"),
    path("healthz/", views.healthz, name="healthz"),
]
