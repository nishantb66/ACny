# PulsePair Chat (Django + Channels + Tailwind)

A production-structured, fully real-time, ephemeral two-person chat application.

## Core capabilities
- Real-time lobby room discovery via WebSockets.
- Real-time join request approval flow.
- Strict two-user room limit.
- Ephemeral room lifecycle with Redis-backed state only (no relational DB).
- Live room visibility rules:
  - Room is visible only if at least one participant is online.
  - Remaining participant can toggle whether single-user room stays discoverable.
  - Room is deleted automatically when everyone leaves.
- Message delivery and read receipts in real time.
- Mobile-first responsive UI with yellow/green/white modern theme.
- Optional no-Redis runtime (`USE_REDIS=False`) for single-instance deployments.

## Stack
- Backend: Django 5 + Channels + Daphne
- Real-time store and channel layer: Redis
- Frontend: Django templates (Jinja-style) + Tailwind + custom CSS
- Deployment target: Render (web service + Redis)

## Architecture
- `chatcore/services/realtime_store.py`: Redis room state service (modular state engine)
- `chatcore/consumers.py`: WebSocket orchestration for lobby + room
- `chatcore/templates/chatcore/`: frontend pages
- `chatcore/static/chatcore/js/`: realtime UI logic
- `config/settings/`: split settings (`base`, `dev`, `prod`)

## Local run
1. Create env file:
```bash
cp .env.example .env
```
2. Start Redis.
3. Create and activate venv, then install dependencies:
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```
4. Start server:
```bash
python manage.py runserver
```
5. Open:
- `http://127.0.0.1:8000/`

### Run without Redis
Set `USE_REDIS=False` in `.env`. This uses in-memory runtime state and channel layer.
Note: in-memory mode is single-instance and state is lost on restart.

## Docker run
```bash
docker compose up --build
```

## Render deployment notes
- Add a Redis service and paste its internal connection URL into `REDIS_URL`.
- Use `DJANGO_SETTINGS_MODULE=config.settings.prod`.
- Set your final public hostname in both:
  - `ALLOWED_HOSTS`
  - `CSRF_TRUSTED_ORIGINS`

## Security + scalability notes
- No chat payload persistence to disk or SQL.
- Redis-based state designed for horizontal scaling with shared channel layer.
- All join approvals are server-validated.
- Room isolation is enforced server-side (membership/permit checks), not only in UI.
