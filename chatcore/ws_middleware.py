from __future__ import annotations

from channels.sessions import SessionMiddlewareStack


def IdentitySessionMiddlewareStack(inner):
    return SessionMiddlewareStack(inner)
