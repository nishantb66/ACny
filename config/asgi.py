from __future__ import annotations

import os

from channels.routing import ProtocolTypeRouter, URLRouter
from channels.security.websocket import AllowedHostsOriginValidator
from django.core.asgi import get_asgi_application

from chatcore.routing import websocket_urlpatterns
from chatcore.ws_middleware import IdentitySessionMiddlewareStack

default_settings = "config.settings.prod" if os.getenv("RENDER") else "config.settings.dev"
os.environ.setdefault("DJANGO_SETTINGS_MODULE", default_settings)

django_asgi_app = get_asgi_application()

application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        "websocket": AllowedHostsOriginValidator(
            IdentitySessionMiddlewareStack(URLRouter(websocket_urlpatterns))
        ),
    }
)
