# SahayakMap — Current Feature Handover

## Runtime

- App folder: `/root/Sahayak/deploy`
- FastAPI app: `app.py`
- Frontend: `templates/index.html` -> symlink to `index.html`
- Live app service: `sahayak-map-app.service`
- App bind: `127.0.0.1:5001`
- Public dashboard: `https://www.joodei.org/sahayak_map/`

## Current API Surface

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/` | Dashboard HTML |
| GET | `/api/stations` | Station list enriched with forecast, stale state, confidence, data age |
| GET | `/api/alerts` | Active alert feed used by dashboard |
| GET | `/api/chart/{station}` | Historical WSE + local forecast payload |
| GET | `/api/social?minutes=` | Social feed from `social_signals` or fixtures fallback |
| GET | `/api/sos/{station}` | Station SOS intelligence drawer data |
| GET | `/api/sos/active` | Active SOS context from Telegram state + live triage |
| GET | `/api/telegram/state` | Telegram bot state, VPS-first with local fallback |
| GET | `/api/boats` | Boat asset positions from `boat_assets` |
| GET | `/api/pulse` | 2G compact station summary |
| GET | `/api/state` | Local scraper state |
| GET | `/api/vps/aircraft` | Proxy to VPS aircraft API |
| GET | `/api/vps/feeds` | Proxy to VPS IMD + Sachet feeds |
| GET | `/api/sachet` | Sachet current + previous day proxy |
| GET | `/api/rss` | Generic RSS proxy |
| GET | `/api/export/sos/{event_id}` | PDF export endpoint |
| POST | `/api/chat` | SahayakMap Intel chat endpoint |
| POST | `/api/whatsapp` | WhatsApp intake -> `social_signals` |

## Public Joodei Routes

| Public route | Target |
|---|---|
| `/sahayak_map/` | Sahayak dashboard app on `127.0.0.1:5001` |
| `/sahayak-data/` | VPS data API on `127.0.0.1:8005` |
| `/api/aircraft` | Aircraft API on `127.0.0.1:8003` |
| `/api/pulse` | Feeds API pulse on `127.0.0.1:8004` |
| `/api/telegram/state` | Feeds API telegram state bridge |
| `/api/boats` | Sahayak app `/api/boats` |
| `/api/sos/*` | Sahayak app `/api/sos/*` |
| `/api/whatsapp` | Sahayak app webhook |
| `/sachet_rss_latest` | Feeds API Sachet route |

## Frontend Features

- Leaflet base map with station markers and hover tooltips.
- Station drawer with:
  - 30-day WSE chart
  - 21-point AI forecast
  - SOS tab
- Floating `SahayakMap Intel` chat panel for gauge, weather, social, WhatsApp, SOS, news, and radar questions.
- Plotly chart behavior:
  - actual WSE line stops at last real reading
  - unified hover retained
  - forecast timeline starts strictly after last actual point
  - WSE series padded with `null` through forecast timestamps to avoid false future WSE hover
- Aircraft overlay refreshed every 90 seconds.
- Boat overlay refreshed every 5 minutes.
- Active SOS overlay:
  - `🆘` marker
  - boat-to-SOS route lines
  - route risk color coding
  - 30-second polling
- Topbar health pills:
  - Normal
  - Warning
  - Danger
  - Stale
- Side panels:
  - Stations
  - Alerts
  - IMD Weather
  - Social + News
  - Team Comms
  - KPI
- Mobile behavior:
  - bottom navigation
  - panel/drawer responsive layout
  - live aircraft and boat polling paused while page is hidden

## KPI Panel

Current KPI panel is frontend-only and uses existing endpoints.

Sections:

- Data Health
  - live stations
  - stale stations
  - unavailable stations
  - latest reading timestamp
- Pipeline Health
  - IMD last scraped
  - Sachet last scraped
  - Aircraft last updated
  - Social last visible run time from latest social row
  - Tweets in latest visible social day
- Operational
  - boat status counts
  - active SOS yes/no
  - alerts fired today from current alerts payload

Known KPI limitations from current API surface:

- `Classified today` is not exposed by an existing endpoint.
- `LLM model used (last)` is not exposed by an existing endpoint.

## Data and Pipeline

- Historical station data for charts comes from VPS data API under `/sahayak-data/data/chart/{station}`.
- Station freshness and stale logic in dashboard are derived from `latest_timestamp` and `data_age_hours`.
- Social feed date anchoring is based on `MAX(published_at)` if present, else `timestamp`, else `fetched_at`.
- Telegram SOS state is read from `/root/Sahayak/pipeline/telegram_state.json` first.
- `/api/sos/active` enriches Telegram `last_sos` with fresh `triage()` output.

## Boat and SOS Logic

- Boats source: `boat_assets`
- Boat statuses currently recognized:
  - `Safe`
  - `Active`
  - `En Route`
  - `SOS`
- Active SOS routes:
  - red for `High` / `Very High`
  - green for `Low` / `Moderate`
- `status === "dispatched"` support exists in frontend logic, but current `/api/sos/active` payload does not yet expose status, so lines remain dashed unless backend adds it.

## Main Files

| File | Purpose |
|---|---|
| `app.py` | Main FastAPI backend and public API bridge |
| `index.html` | Live frontend dashboard |
| `templates/index.html` | Symlink used by FastAPI |
| `triage_logic.py` | Nearest boats, route risk, safe zone logic |
| `telegram_bot.py` | Telegram polling, response capture, SOS dispatch workflow |
| `social_agent.py` | Social signal ingestion/classification worker |
| `ml_forecast.py` | Forecast loading and station predictions |
| `fetch_river_data.py` | River data collection |
| `db_ingest.py` | Incremental ingestion into Supabase |
| `scheduler.py` | Pipeline scheduler |

## Current Gaps

- PDF export route exists but is not considered production-stable.
- KPI panel still needs backend support for:
  - classified-today count
  - latest LLM model used
  - alerts-fired-today from full DB instead of current alert payload only
- `/api/sos/active` should expose SOS `status` explicitly if route solidification is required on dispatch.

## Backup

- Latest frontend backup before KPI work:
  - `/root/Sahayak/deploy/templates/index.html.bak_20260513_1128`
