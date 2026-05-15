# PulsePair Chat (Django + Channels + MongoDB)

PulsePair is a production-focused realtime chat app with:

- Email/password authentication
- Google Sign-In for existing onboarded users
- OTP-based email verification before account creation
- Unique usernames (changeable, uniqueness enforced)
- MongoDB-backed persistence for users + chat history
- Realtime P2P direct messaging by username search
- Legacy 2-person random room chat (preserved)
- WebSocket-based live updates via Django Channels

## Stack

- Backend: Django 5 + Channels + Daphne
- Database: MongoDB Atlas (PyMongo)
- Frontend: Django templates + vanilla JS + responsive CSS
- Runtime WS fanout: In-memory channel layer (no Redis cache)

## Key Features

### Authentication

- Signup with `email`, `password`, and `username`
- Signup now requires OTP verification over email before account creation
- Login/logout session flow
- Google OAuth login (only for users already registered by email)
- Username uniqueness constraint (case-insensitive)
- Update username from UI with conflict validation
- Session lifetime fixed to 24 hours

### P2P Direct Chat

- Search users by username prefix
- Start chat instantly from search result
- Realtime send/receive over WebSocket
- Conversation list with latest message + unread counts
- Messages persisted in MongoDB

### Legacy Room Chat

- Room discovery + join requests
- Two-participant room cap
- One-time image messages preserved
- New: text room message history persisted in MongoDB and loaded on join

## Local Setup

1. Copy env template and edit values:

```bash
cp .env.example .env
```

2. Install dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

3. Run server:

```bash
python manage.py runserver
```

4. Open app:

- `http://127.0.0.1:8000/`

## Required Env Vars

- `MONGODB_URI`
- `MONGODB_DB_NAME`
- `SECRET_KEY`
- `ALLOWED_HOSTS`
- `CSRF_TRUSTED_ORIGINS`
- `SESSION_COOKIE_AGE_SECONDS`
- `EMAIL_HOST`
- `EMAIL_PORT`
- `EMAIL_HOST_USER`
- `EMAIL_HOST_PASSWORD`
- `EMAIL_USE_TLS`
- `DEFAULT_FROM_EMAIL`
- `SIGNUP_OTP_TTL_SECONDS`
- `SIGNUP_OTP_RESEND_COOLDOWN_SECONDS`
- `SIGNUP_OTP_MAX_ATTEMPTS`
- `GOOGLE_OAUTH_CLIENT_ID`
- `GOOGLE_OAUTH_CLIENT_SECRET`
- `GOOGLE_OAUTH_SCOPES`
- `GOOGLE_OAUTH_AUTH_URI`
- `GOOGLE_OAUTH_TOKEN_URI`
- `GOOGLE_OAUTH_USERINFO_URI`

See `.env.example` for full list.

## Mongo Collections + Indexes

Collections created automatically:

- `users`
- `room_messages`
- `dm_messages`
- `pending_signups`

Indexes are created automatically at runtime for:

- unique `email_lower`
- unique `username_lower`
- unique `pending_signups.email_lower`
- unique `pending_signups.username_lower`
- TTL cleanup on `pending_signups.expires_at`
- conversation/message retrieval paths
- unread scans for DMs

## Routes

- `/login/`, `/login/google/`, `/google/callback/`, `/signup/`, `/signup/verify/`, `/logout/`
- `/chat/` -> P2P home
- `/rooms/` -> legacy random room lobby
- `/room/<room_id>/` -> legacy room

## Notes

- The app intentionally avoids Redis cache usage.
- The current in-memory channel layer is process-local for websocket fanout.
