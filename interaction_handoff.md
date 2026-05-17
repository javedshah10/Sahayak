# SahayakMap Interaction Handoff

Source of truth: `/root/Sahayak/deploy/templates/index.html`

## 1. Panel Switching

### Desktop rail
- Primary rail buttons live in `#rail`
- Each button has `data-panel`:
  - `stations`
  - `alerts`
  - `weather`
  - `social`
  - `teams`
  - `kpi`
- Click handler:
  - `#rail` delegates to `activatePanel(btn.dataset.panel)`

### Mobile bottom nav
- Primary mobile buttons live in `#bottom-nav`
- Uses the same `data-panel` values
- Click handler:
  - `#bottom-nav` delegates to `activatePanel(btn.dataset.panel)`

### Switching logic
- Function: `activatePanel(p)`
- Behavior:
  - If the clicked panel is already open, it closes it:
    - `activePanel = null`
    - `#side-panel` loses `.open`
    - `body` loses `.panel-open`
    - all nav buttons lose `.active`
  - Otherwise:
    - sets `activePanel`
    - marks matching rail/mobile button `.active`
    - opens `#side-panel`
    - adds `body.panel-open`
    - updates `#panel-title`
    - calls `renderPanel()`
    - on mobile, closes the station drawer with `closeDrawer()`

### Panel content dispatch
- Function: `renderPanel()`
- Routes by `activePanel`:
  - `stations` → `renderStations(el)`
  - `alerts` → `renderAlerts(el)`
  - `weather` → `loadWeather()`
  - `social` → `loadSocial()`
  - `teams` → `loadTeams()`
  - `kpi` → `loadKpi()`

### Close behavior
- `closePanel()` fully resets:
  - `activePanel = null`
  - closes `#side-panel`
  - removes `body.panel-open`
  - clears `.active` from nav buttons

## 2. Station Drawer Tabs

Drawer tabs:
- `#forecast-tab`
- `#sos-tab`
- `#obs-tab`

Drawer panes:
- `#forecast-div`
- `#sos-div`
- `#obs-div`

### Entry point
- Clicking a station row or marker calls `selectStation(name)`
- `selectStation()`:
  - sets `selectedStation`
  - closes any Leaflet popup
  - rerenders station list if needed
  - closes side panel on mobile
  - calls `openDrawer(selectedStation)`
  - flies map to station

### Drawer open
- `openDrawer(s)`:
  - opens `#station-drawer`
  - fills header, status, KPI grid, updated/stale text
  - forces default tab:
    - `switchDrawerTab("forecast")`
  - loads chart:
    - `loadDrawerChart(s.name)`

### Tab switching logic
- Function: `switchDrawerTab(tab)`

#### Forecast tab
- Active when `tab === "forecast"`
- Shows:
  - `#forecast-div`
- Hides:
  - `#sos-div`
  - `#obs-div`
- Resizes Plotly after a short delay

#### SOS tab
- Active when `tab === "sos"`
- Shows:
  - `#sos-div`
- Hides:
  - `#forecast-div`
  - `#obs-div`
- Fetches:
  - `GET /sahayak_map/api/sos/{station}`
- Uses request sequencing guard:
  - `sosSeq`
- Renders:
  - forecast +8h
  - evacuation window
  - nearest boats
  - route risk
  - nearest safe zone
  - manual triage/escalation note

#### Obs tab
- Active when `tab === "obs"`
- Shows:
  - `#obs-div`
- Hides:
  - `#forecast-div`
  - `#sos-div`
- Calls:
  - `loadDrawerObservations()`
- Fetches:
  - `GET /sahayak_map/api/vps/feeds`
- Reads:
  - `bulletin` array from feeds payload
- Maps current station name to locked station code via `stationCodeMap`
- Renders:
  - ground observations card
  - or “Observations not available for this station”

## 3. Map Marker Behaviors

### Station markers
- Built by `updateMarkers()`
- One marker per station in `stationsData`
- Marker is a `Leaflet divIcon` with class:
  - `.station-marker`
- Marker state/color depends on:
  - age / stale state
  - `wse_source`
  - `alert_status`

### Station hover
- Uses `bindTooltip(...)`
- Tooltip content changes by age:
  - if `data_age_hours > 168`:
    - shows unavailable warning
    - hides WSE/forecast/status detail
  - otherwise:
    - shows river
    - district
    - WSE
    - AI forecast +8h / +24h
    - warning/danger thresholds
    - status
    - updated time

### Station click
- `m.on("click",()=>selectStation(s.name))`
- Behavior:
  - opens station drawer
  - flies map to station
  - syncs station selection state in list

### Aircraft markers
- Refreshed by `refreshAircraft()`
- Fetched from:
  - `GET /sahayak_map/api/vps/aircraft`
- Uses popup, not tooltip:
  - `bindPopup(...)`

### Boat markers
- Refreshed by `refreshBoats()`
- Fetched from:
  - `GET /sahayak_map/api/boats`
- Uses `🚤` divIcon
- Hover uses `bindTooltip(...)`
- Tooltip shows:
  - call sign
  - status
  - lat/lon
  - last ping
  - nearest station

## 4. Chat Flow

### Open/close
- Floating button:
  - `#chat-fab`
  - `onclick="toggleChat()"`
- Panel:
  - `#chat-panel`
- `toggleChat()`:
  - toggles `.open`
  - bootstraps first bot prompt once
  - focuses input
- `closeChat()`:
  - removes `.open`

### Initial bootstrap
- `ensureChatBootstrapped()`
- Adds one starter bot message:
  - “Ask about gauges, weather, tweets, WhatsApp reports, or SOS.”

### Send flow
- Form submit:
  - `#chat-form` → `sendChatMessage`
- `sendChatMessage(ev)`:
  - prevents default
  - blocks double-send via `chatBusy`
  - reads `#chat-input`
  - appends user bubble
  - disables send button
  - appends temporary meta message:
    - “Thinking…”
  - POSTs:
    - `POST /sahayak_map/api/chat`
    - body: `{"message": "..."}`
  - removes thinking state
  - appends bot reply
  - on error, shows:
    - “Intel unavailable. Check dashboard directly.”
  - re-enables send and refocuses input

### Keyboard behavior
- `Escape` on `#chat-input` closes the panel

## 5. Refresh Timers

### Global dashboard data
- `loadAll()`
- Runs:
  - once on boot
  - every `3 * 60 * 60 * 1000`
- Refreshes:
  - `/api/stations`
  - `/api/alerts`
  - topbar pills
  - critical banner
  - station markers
  - station panel if open

### KPI panel
- Interval:
  - every `5 * 60 * 1000`
- Guard:
  - only runs if `activePanel === "kpi"`

### Clock
- `tick()`
- Interval:
  - every `30000 ms`

### Aircraft layer
- `refreshAircraft()`
- Interval:
  - every `90000 ms` (90 seconds)

### Boat layer
- `refreshBoats()`
- Interval:
  - every `5 * 60 * 1000` (5 minutes)

### SOS routes layer
- `refreshSosRoutes()`
- Interval:
  - every `30000 ms` (30 seconds)

### Weather/social/team panels
- These do not have persistent polling loops
- They refresh when the panel is opened

## 6. 2G Detection

There is no explicit 2G or slow-network detection in `templates/index.html`.

What is present:
- no use of:
  - `navigator.connection`
  - `effectiveType`
  - `saveData`
- no frontend branch that switches to `/api/pulse`
- no reduced-payload mode based on network speed

What does exist instead:
- the backend exposes compact endpoints such as `/api/pulse`
- but this template does not automatically switch to them

So the current frontend behavior is:
- same UI and same fetch pattern regardless of network quality

## 7. SOS Route Lines

### Layer ownership
- SOS overlay lives in `sLayer`
- Helper:
  - `sEnsure()`

### Refresh path
- Function: `refreshSosRoutes()`
- Fetches:
  - `GET /sahayak_map/api/sos/active`

### Clear behavior
- First line of each refresh:
  - `l.clearLayers()`
- That means:
  - all previous SOS marker/lines are removed before redraw

### When routes appear
- Only when response satisfies:
  - `d.active === true`
  - `d.sos_lat != null`
  - `d.sos_lon != null`
- Then it draws:
  - `🆘` marker at SOS point
  - one polyline from each boat to SOS location

### Route styling
- `sosRouteColor(risk)`:
  - `High` / `Very High` → red `#dc2626`
  - otherwise → green `#16a34a`
- Line style:
  - dashed: `dashArray: "8 4"`
  - if `d.status === "dispatched"`:
    - solid line (`dashArray: null`)

### Route hover
- Each polyline uses `bindTooltip(...)`
- Tooltip shows:
  - `{call_sign} → SOS`
  - distance
  - route risk
  - road id

### When routes clear
- If `/api/sos/active` returns:
  - inactive
  - missing lat/lon
  - invalid payload
- Then no new lines are drawn after `clearLayers()`
- Result:
  - SOS overlay disappears cleanly

## 8. Visibility-Based Live Layer Control

Live layers are paused when the page is hidden.

### Functions
- `startLiveLayers()`
- `stopLiveLayers()`
- `syncLiveLayers()`

### Trigger
- `document.addEventListener("visibilitychange", syncLiveLayers)`

### Behavior
- If `document.hidden`:
  - stops aircraft, boat, and SOS timers
- If page becomes visible:
  - restarts those timers and refreshes layers immediately

This is the main frontend performance optimization currently present for mobile/background use.
