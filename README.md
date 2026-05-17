# SahayakMap

SahayakMap is an operational flood-response dashboard for Odisha. It combines live river stage monitoring, forecast support, IMD and Sachet feeds, aircraft awareness, boat tracking, SOS triage, and an operator-facing intelligence chat in one map-first interface.

## Contents

- `app.py` — main FastAPI app
- `templates/index.html` — live frontend template
- `ml_forecast.py` — forecast loader
- `triage_logic.py` — SOS and nearest-boat logic
- `telegram_bot.py` — Telegram workflow
- `social_agent.py` — social signal processing
- `opensky/` — aircraft and feeds APIs
- `scrapers/` — bulletin and IMD scrapers
- `models/` — forecast model JSON files
- `PRD.md` — product requirements
- `features.md` — feature handover

## Runtime

- App bind: `127.0.0.1:5001`
- Public dashboard path: `/sahayak_map/`

## Main Endpoints

- `GET /api/stations`
- `GET /api/chart/{station}`
- `GET /api/alerts`
- `GET /api/social`
- `GET /api/boats`
- `GET /api/sos/{station}`
- `GET /api/sos/active`
- `GET /api/vps/aircraft`
- `GET /api/vps/feeds`
- `POST /api/chat`

## Environment

Copy `.env.example` to `.env` and populate:

- `URI`
- `OPENROUTER_API_KEY`
- `GROQ_API`
- `TWITTER_BEARER_TOKEN`
- `GETXAPI_KEY`
- `BOT_TOKEN`

## Notes

- This export excludes secrets, runtime state, caches, and backup files.
- Some public routes depend on external Nginx proxy configuration.
