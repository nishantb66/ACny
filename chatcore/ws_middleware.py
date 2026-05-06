from __future__ import annotations

import secrets

from channels.sessions import SessionMiddlewareStack

from .constants import SESSION_USER_ID, SESSION_USER_NAME


class IdentityWsMiddleware:
    def __init__(self, inner):
        self.inner = inner

    async def __call__(self, scope, receive, send):
        session = scope.get("session")
        if session is not None:
            changed = False
            if SESSION_USER_ID not in session:
                session[SESSION_USER_ID] = secrets.token_urlsafe(10)
                changed = True
            if SESSION_USER_NAME not in session:
                suffix = session[SESSION_USER_ID][:4].upper()
                session[SESSION_USER_NAME] = f"Guest-{suffix}"
                changed = True
            if changed:
                await session.asave()
        return await self.inner(scope, receive, send)


def IdentitySessionMiddlewareStack(inner):
    return SessionMiddlewareStack(IdentityWsMiddleware(inner))
