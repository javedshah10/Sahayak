# SahayakMap — Phase 3 Product Requirements Document

**Version:** 3.0 — Draft  
**Date:** 2026-05-17  
**Depends on:** Phase 2 Complete (v2.3)  
**Status:** Planning

---

## 1. Objective

Phase 3 extends SahayakMap from a monitoring and triage tool into a **predictive and autonomous response system** — anticipating crises before gauges confirm them, coordinating multi-agency response, and reaching communities that have gone dark.

---

## 2. Authoritative Context (Inherited from Phase 2)

- 9 gauge stations (NAR/JEN/ANA/AKH/TIK/KAN/SAL/PUR/REN)
- Supabase: stations, gauge_readings, alerts, social_signals, safe_zones, road_risks, boat_assets
- Intel chat, Telegram bot, SOS triage, PDF EOC export — all live
- VPS: 72.60.98.178, ports 8002-8004, systemd timers

---

## 3. Phase 3 Tasks

---

### TASK P3-1 — RAG Historical Intelligence
**New file:** `rag_engine.py`  
**Depends on:** ChromaDB or Supabase pgvector, historical gauge_readings, past EOC PDFs

**Problem:** Rajesh cannot query past flood events. "What happened at Jenapur in the 2021 monsoon?" has no answer in the current system.

**Solution:** RAG pipeline over:
- `gauge_readings` (194,766+ rows) — chunked by station + month
- Historical EOC PDFs from `exports/` folder
- Past `alerts` table entries
- IMD bulletin archive

**Intel chat integration:**
- New intent: `history`
- Keywords: "last year", "2021", "previous flood", "historical", "what happened"
- LLM receives: RAG-retrieved context + query
- Response: "In August 2021, Jenapur WSE peaked at 24.1m over 3 days..."

**Tech:** ChromaDB (local VPS) or Supabase pgvector extension. Embed with `sentence-transformers` or OpenRouter embedding endpoint.

**Constraints:**
- Embedding runs offline on VPS — no per-query API cost
- Re-index monthly via systemd timer
- No schema changes to existing tables

---

### TASK P3-2 — Intelligent Voice Calling
**New file:** `voice_alert.py`  
**Depends on:** Twilio Voice API, `TWILIO_SID`, `TWILIO_AUTH_TOKEN`

**Problem:** During critical events, Rajesh may not see Telegram alerts. District collectors may ignore WhatsApp.

**Trigger conditions (any):**
- Any station WSE >= Danger AND no human response in Telegram for 30 min
- SILENT ZONE alert fires (P3-5)
- SOS received AND no Approve/Override in 15 min

**Behavior:**
- Twilio places automated voice call to CALL_LIST (.env)
- Reads alert in English using TTS:
  `"SahayakMap Alert. Jenapur station at Danger level. 24.5 metres. Immediate action required."`
- If no answer → retry 2x → escalate to next number in CALL_LIST
- Log call outcome to `alerts` table

**Credentials (.env):**
```
TWILIO_CALL_LIST=+91XXXXXXXXXX,+91XXXXXXXXXX
TWILIO_FROM_NUMBER=+1XXXXXXXXXX
```

**Constraints:**
- Max 3 calls per event (dedup 1h window)
- No calls between 23:00–05:00 IST unless WSE >= HFL

---

### TASK P3-3 — Inundation Extent Overlay
**New file:** `inundation_fetcher.py`  
**Depends on:** Google Earth Engine credentials OR MODIS NRT Flood API

**Problem:** Gauge readings tell you river level but not which villages are underwater.

**Data sources (in priority order):**
1. MODIS NRT Global Flood Product (free, daily, 250m resolution)
   - URL: `https://floods.gsfc.nasa.gov/`
2. Sentinel-1 SAR via GEE (requires GEE credentials)
3. Copernicus EMS (event-triggered, manual)

**Dashboard integration:**
- Leaflet WMS/GeoTIFF overlay layer
- Toggle button in IMD Weather panel: `[🌊 Flood Extent]`
- Amber/blue fill over inundated areas
- Tooltip: "Inundated — {date} — source: MODIS NRT"
- Refresh: daily via systemd timer

**Constraints:**
- GEE credentials required for Sentinel path
- MODIS path is free and automated — implement first
- Overlay must not obscure station markers

---

### TASK P3-4 — Predictive Evacuation Windows
**New file:** `evacuation_planner.py`  
**Depends on:** ml_forecast.py output, safe_zones table, road_risks table, DEM data (Phase 3 prerequisite)

**Problem:** Current evacuate window formula is single-station only. No village-level risk ranking.

**Extended formula:**
```python
# Per safe_zone village:
elevation = safe_zone.dem_elevation  # requires CartoDEM 30m
nearest_station_forecast = forecast_upper_ci_8h
inundation_risk = "HIGH" if elevation < nearest_station_forecast else "LOW"

# Time window:
rise_rate = (current_wse - wse_6h_ago) / 6
hours_to_inundation = (elevation - current_wse) / rise_rate
```

**Dashboard:** New "Evacuation" column in safe_zones panel showing:
- `✅ Safe (>12h window)`
- `⚠️ Evacuate within 6h`
- `🔴 Immediate — under 2h`

**Prerequisite:** CartoDEM 30m elevation data for 15 safe_zones — manual ingestion step required before this task.

---

### TASK P3-5 — Silent Zone Detector
**New file:** `silent_zone_detector.py`  
**Depends on:** social_signals, boat_assets, gauge_readings, power outage data

**Problem (from capstone):** The quiet district is the dangerous one. Zero messages during a flood peak means people are submerged, not safe.

**Detection logic:**
```python
SILENT_ZONE_TRIGGER = all of:
  1. power_outage: True for district  (from DISCOM API or proxy)
  2. social_silence: zero social_signals from district in >2h
  3. whatsapp_silence: zero WhatsApp signals from district in >2h  
  4. flood_active: nearest station WSE >= warning_level
```

**Power data sources (in priority):**
1. TPCODL Outage Portal: `https://www.tpcodl.in/`
2. CESU: `https://www.cesuodisha.com/`
3. **Proxy (if API unavailable):** zero tweets mentioning district for >3h during active flood treated as silence signal

**Output:**
- INSERT into `alerts` table:
  `"🔴 SILENT ZONE: {district} — no power, no comms, WSE active. Immediate aerial/boat recon required."`
- Priority: P1_critical
- Telegram auto-message to Rajesh
- Dashboard: red pulsing district label on map over affected area
- Dedup: 4h window per district

**Scheduler:** Run every 30 minutes via systemd timer.

---

### TASK P3-6 — Android APK (2G Lite Mode)
**Depends on:** PWA Service Worker (Phase 2), `/api/pulse` endpoint

**Problem:** Field teams need a native app experience on Android — faster launch, offline capability, push notifications.

**Approach:** Progressive Web App (PWA) → TWA (Trusted Web Activity) → Android APK via Bubblewrap CLI.

**Features in APK:**
- Full dashboard (same codebase)
- Offline app shell via Service Worker
- Push notifications for P1 alerts via Web Push API
- Home screen install prompt
- Background sync for SOS queue

**Build steps:**
1. Add `manifest.json` to SahayakMap frontend
2. Verify Service Worker scope
3. `bubblewrap init --manifest https://www.joodei.org/sahayak_map/manifest.json`
4. `bubblewrap build` → generates `.apk`
5. Distribute via direct download (no Play Store required for NDRF internal use)

**Constraints:**
- No new backend required
- APK targets Android 8.0+ (API level 26)
- TWA requires HTTPS (already live at joodei.org)

---

### TASK P3-7 — Daily Intelligence Briefing
**New file:** `daily_briefing.py`  
**Depends on:** All existing endpoints + Telegram bot

**Schedule:** 06:00 IST daily via systemd timer

**Briefing content:**
```
SahayakMap Daily Brief — 17 May 2026, 06:00 IST

RIVER STATUS
  NAR: 21.3m NORMAL (+0.2m overnight)
  JEN: 17.8m NORMAL (stable)
  ...3 stations STALE

IMD FORECAST
  Angul: Orange alert 0700-1000hrs
  Ganjam: Yellow watch

SOCIAL SIGNALS (last 24h)
  12 tweets processed, 2 verified crisis
  1 WhatsApp critical: Cuttack knee-deep water

BOATS
  8 Safe, 1 Active, 1 En Route

OVERNIGHT ALERTS
  R6 fired: NH-16 Jenapur (10:14 PM)
```

**Delivery:** Telegram message to `TELEGRAM_CHAT_ID`
**Voice option:** If `ENABLE_VOICE_BRIEF=true` in .env → Twilio TTS call at 06:00 IST

---

## 4. Phase 3 Deferred → Phase 4

| Item | Reason |
|------|--------|
| Multi-user EOC view | Requires WebSocket + auth layer |
| Bridge deck height matrix | CartoDEM 30m GIS ingestion required |
| Copernicus EMS integration | Manual event-triggered, not automated |
| IMD direct API | Blocked by Kaspersky on test machine |
| Play Store distribution | Requires Google developer account + review |

---

## 5. Implementation Order

```
P3-5 (Silent Zone)     ← highest operational value, no new dependencies
P3-7 (Daily Briefing)  ← quick win, uses existing endpoints
P3-2 (Voice Calling)   ← Twilio already configured
P3-1 (RAG)             ← medium complexity, high intelligence value
P3-3 (Inundation)      ← depends on MODIS API access
P3-4 (Evacuation)      ← depends on CartoDEM data
P3-6 (Android APK)     ← last, depends on PWA maturity
```

---

## 6. Constraints (All Tasks)

- Parameterised DB queries only
- All credentials from .env
- No schema changes without explicit instruction
- Retry 3x exponential backoff on external calls
- Minimal surgical changes — no full rewrites
- Dedup guards on all alert inserts
- DB: Supabase URI from .env — never localhost

---

*SahayakMap Phase 3 PRD | Joodei Consultancy | 2026-05-17*
