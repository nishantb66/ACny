from django.conf import settings

if settings.USE_REDIS:
    from .realtime_store import RoomStateService  # noqa: F401
else:
    from .memory_store import RoomStateService  # noqa: F401
