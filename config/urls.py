from django.urls import path

from chatcore import views

urlpatterns = [
    path("", views.root, name="root"),
    path("login/", views.login_view, name="login"),
    path("login/google/", views.google_login_start, name="google_login_start"),
    path("google/callback/", views.google_callback, name="google_callback"),
    path("signup/", views.signup_view, name="signup"),
    path("signup/verify/", views.signup_verify_view, name="signup_verify"),
    path("logout/", views.logout_view, name="logout"),
    path("chat/", views.chat_home, name="chat_home"),
    path("chat/people/", views.chat_people, name="chat_people"),
    path("chat/profile/", views.chat_profile, name="chat_profile"),
    path("chat/u/<str:peer_id>/", views.chat_thread, name="chat_thread"),
    path("rooms/", views.lobby, name="lobby"),
    path("room/<str:room_id>/", views.room, name="room"),
    path("invite/<str:token>/", views.accept_direct_invite, name="accept_direct_invite"),
    path("api/room/<str:room_id>/invite/", views.create_whatsapp_invite, name="create_whatsapp_invite"),
    path("api/users/search/", views.search_users, name="search_users"),
    path("api/profile/update/", views.update_profile, name="update_profile"),
    path("identity/update/", views.update_identity, name="update_identity"),
    path("healthz/", views.healthz, name="healthz"),
]
