# SahayakMap — Product Requirements Document

## Product Goal

SahayakMap is an operational flood-response dashboard for Odisha. It combines live river stage data, forecast support, weather and alert feeds, social signals, aircraft awareness, rescue boat tracking, and Telegram-linked SOS triage in one map-first interface.

The product is not a public information site. It is an operator console for monitoring, triage, and response coordination.

## Primary Users

- EOC / control room operators
- District flood monitoring staff
- Field coordination leads
- Telegram-based response teams

## Core Use Cases

1. See current flood station status and stale/unavailable data at a glance.
2. Open any station and inspect actual WSE history, thresholds, and forecast.
3. Cross-check IMD, Sachet, aircraft, social, and alert signals in one place.
4. Track rescue boats on map and understand their current status.
5. Surface a live SOS on the map and draw candidate boat routes to it.
6. Monitor operational health through KPI summaries without leaving the dashboard.
7. Ask for tactical summaries through the in-app intelligence chat without leaving the map.

## Current Scope

### Map and stations

- 9 Odisha flood stations
- warning / danger / HFL thresholds
- stale and unavailable handling
- station drawer with forecast chart

### Forecasting

- local forecast models loaded from existing model files
- no retraining in dashboard request path
- forecast visual separation from actual WSE

### Weather and news

- IMD stations
- Sachet alerts
- previous-day Sachet continuity in the news panel

### Mobility and operations

- aircraft overlay
- boat overlay
- active SOS overlay with route lines
- Telegram team state

### Comms and signals

- social feed from DB-backed `social_signals`
- WhatsApp webhook intake
- RSS proxy support
- in-app `SahayakMap Intel` chat backed by `/api/chat`

## Current Delivered Features

- Public dashboard served at `https://www.joodei.org/sahayak_map/`
- VPS data API bridge under `/sahayak-data/`
- 2G pulse endpoint
- `boats` API and boat markers
- `sos/active` API and SOS route visualization
- `chat` API and floating intelligence assistant
- KPI panel in sidebar
- topbar stale pill
- mobile responsive layout
- background polling pause when page is hidden

## Functional Requirements

### FR1 — Station health

- Show every station with current operational state:
  - live
  - stale
  - unavailable
- Grey out stale/unavailable elements consistently in map, tooltip, and list.

### FR2 — Historical vs forecast clarity

- Actual WSE must end at the last true reading.
- Forecast must start after the last actual timestamp.
- Hover and chart display must not imply future actual WSE values.

### FR3 — Multi-source situational awareness

- Dashboard must expose:
  - river status
  - IMD feed
  - Sachet feed
  - aircraft positions
  - social feed
  - boat positions
  - active SOS

### FR4 — SOS operations

- If there is an active SOS, operators should see:
  - SOS point
  - nearest boats
  - route risk
  - approximate route lines
- If no active SOS exists, no SOS overlay should remain on map.

### FR5 — KPI visibility

- Operators should see a fast operational summary without opening multiple tabs.
- KPI data must come only from existing APIs unless backend support is explicitly added.

## Non-Goals

- Full dispatch workflow management
- Rich asset management UI for boats
- Historical analytics warehouse UI
- Public-facing citizen portal

## Constraints

- Existing apps on the VPS must not be broken by Sahayak routing changes.
- Frontend should prefer existing endpoints instead of adding backend work unless needed.
- Where data is unavailable from current APIs, UI should show unavailable rather than fabricate values.

## Known Gaps

- KPI panel lacks direct API support for:
  - latest `llm_model_used`
  - classified-today metric
  - precise DB-backed daily alerts count
- Active SOS payload should expose dispatch status if map lines need to switch from dashed to solid after approval.
- PDF export exists but is not treated as production-complete.

## Near-Term Next Requirements

1. Add backend KPI summary endpoint to avoid frontend fan-out and expose missing metrics cleanly.
2. Add dispatch status to `/api/sos/active`.
3. Add DB-backed daily counts for alerts and classified social signals.
4. Tighten public-route documentation so every joodei proxy endpoint is tracked in one place.
