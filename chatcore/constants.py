LOBBY_GROUP = "lobby.broadcast"

SESSION_USER_ID = "auth_user_id"
SESSION_USER_NAME = "auth_user_name"
SESSION_USER_EMAIL = "auth_user_email"

MAX_ROOM_PARTICIPANTS = 2
DEFAULT_SINGLE_USER_DISCOVERABLE = True

ONE_TIME_IMAGE_MODE = "one_time_seen"
TIMED_ONE_TIME_IMAGE_MODE = "timed_one_time_seen"
ALLOWED_ONE_TIME_IMAGE_MIME_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/gif",
}
MAX_ONE_TIME_IMAGE_BYTES = 5 * 1024 * 1024
MAX_ONE_TIME_IMAGE_VIEW_SECONDS = 60

DIRECT_INVITE_TTL_SECONDS = 15 * 60
