"""
SahayakMap — FastAPI Backend
=============================
REST API serving station data, alerts, social signals,
WSE charts with Prophet forecast, and intelligence engine trigger.

Run:
    uvicorn app:app --reload --host 0.0.0.0 --port 5000
"""

from __future__ import annotations

import httpx
import json
import logging
import os
import re
import subprocess
import sys
import base64
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List

import pandas as pd
import psycopg2
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("SahayakMap.API")

app = FastAPI(title="SahayakMap API", version="2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

DATA_DIR = Path("data")
FIXTURES_DIR = Path("fixtures")
STATE_FILE = Path("state.json")
ALERTS_FILE = Path("alerts.json")

VPS_DATA_API = "https://www.joodei.org/sahayak-data"

INTENT_RULES = {
    "gauge": ["water", "wse", "level", "gauge", "naraj", "jenapur", "station"],
    "weather": ["weather", "rain", "imd", "wind", "storm", "forecast weather", "climate", "temperature", "condition"],
    "radar": ["radar", "storm approaching", "storm cell", "approaching storm", "rain coming", "clouds moving", "precipitation", "doppler", "any storm", "storm near", "weather radar", "rain radar"],
    "news": ["news", "latest", "update", "sachet", "weather alert", "warning", "what is happening", "any alert", "district alert"],
    "tweet": ["tweet", "twitter", "social", "fake", "real", "verify", "citizen"],
    "whatsapp": ["whatsapp", "message", "field team", "report"],
    "sos": ["sos", "boat", "rescue", "triage"],
    "summary": ["summary", "brief", "overview", "situation", "status"],
}

_station_context_cache = {"expires_at": None, "raw": None, "gauge": None, "live_count": 0, "stale_count": 0}


def _clip_words(text: str, max_words: int) -> str:
    words = str(text or "").split()
    return " ".join(words[:max_words])


def _weather_icon_label(rain: str | None, wind: str | None) -> str:
    r = str(rain or "").lower()
    w = str(wind or "").lower()
    if "very heavy" in r or "extremely heavy" in r:
        return "⛈️ DANGER"
    if "heavy" in r:
        return "🌧️ ALERT"
    if "moderate" in r:
        return "🌦️ CAUTION"
    if "light" in r:
        return "🌦️ MONITOR"
    if "thunderstorm" in w or "t-storm" in w:
        return "🌩️ DANGER"
    if "wind" in w or "squall" in w:
        return "💨 MONITOR"
    return "☀️ CLEAR"


def _detect_intent(message: str) -> str:
    text = str(message or "").lower()
    scores = {}
    for intent, terms in INTENT_RULES.items():
        score = sum(1 for term in terms if term in text)
        if score:
            scores[intent] = score
    if not scores:
        return "summary"
    return max(scores.items(), key=lambda item: item[1])[0]


async def _fetch_station_payload() -> List[Dict]:
    now = datetime.now(timezone.utc)
    expires_at = _station_context_cache.get("expires_at")
    if expires_at and expires_at > now and _station_context_cache.get("raw") is not None:
        return _station_context_cache["raw"]
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(f"{VPS_DATA_API}/data/stations")
        stations = r.json() if r.status_code == 200 else []
    for s in stations if isinstance(stations, list) else []:
        if s.get("data_age_hours") is None:
            ts = s.get("latest_timestamp")
            if ts:
                try:
                    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    age = (datetime.now(timezone.utc) - dt).total_seconds() / 3600
                    s["data_age_hours"] = round(age, 1)
                except Exception:
                    s["data_age_hours"] = 999
            else:
                s["data_age_hours"] = 999
    for s in stations if isinstance(stations, list) else []:
        logging.info(f"STATION AGE: {s.get('name')} → {s.get('data_age_hours')}h")
    gauge_bits = []
    live_count = 0
    stale_count = 0
    for s in stations if isinstance(stations, list) else []:
        age_hours = s.get("data_age_hours")
        try:
            age_hours = float(age_hours) if age_hours is not None else None
        except Exception:
            age_hours = None
        if age_hours is None or age_hours >= 48:
            stale_count += 1
            continue
        live_count += 1
        short = s.get("name", "")[:3].upper()
        wse = s.get("latest_wse")
        state = s.get("alert_status", "NORMAL")
        gauge_bits.append(f"{short}:{wse if wse is not None else 'NA'}m {state}")
    _station_context_cache["expires_at"] = now + timedelta(minutes=5)
    _station_context_cache["raw"] = stations if isinstance(stations, list) else []
    _station_context_cache["gauge"] = _clip_words(" | ".join(gauge_bits), 60)
    _station_context_cache["live_count"] = live_count
    _station_context_cache["stale_count"] = stale_count
    logging.info("LIVE STATIONS: %s", live_count)
    logging.info("STALE STATIONS: %s", stale_count)
    logging.info("GAUGE BITS: %s", _station_context_cache["gauge"])
    return _station_context_cache["raw"]


async def _build_chat_context(intent: str) -> str:
    parts = []

    if intent in {"gauge", "summary", "radar"}:
        stations = await _fetch_station_payload()
        gauge_ctx = _station_context_cache.get("gauge") or ""
        stale_count = int(_station_context_cache.get("stale_count") or 0)
        stale_note = (
            f" Note: {stale_count} stations excluded (stale >48h)"
            if stale_count else ""
        )
        if intent == "summary":
            live = sum(1 for s in stations if (s.get("data_age_hours") or 0) < 48)
            parts.append(_clip_words(f"Gauges: {gauge_ctx}. Live stations {live}/{len(stations) or 9}.{stale_note}", 90))
        elif intent == "radar":
            radar_context = {
                "radar_url": "https://mausam.imd.gov.in/Radar/caz_pdp.gif",
                "stations": _clip_words(f"Gauges: {gauge_ctx}.{stale_note}", 60),
            }
            parts.append(json.dumps(radar_context, ensure_ascii=False))
        else:
            parts.append(_clip_words(f"Gauges: {gauge_ctx}.{stale_note}", 60))

    if intent in {"weather", "summary"}:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(VPS_FEEDS)
                feeds = r.json()
            imd = feeds.get("imd", {}).get("stations", []) if isinstance(feeds, dict) else []
            items = []
            for s in imd[:12]:
                station = s.get("name") or s.get("district") or "Unknown"
                rain = s.get("rain") or s.get("rain_intensity") or "none"
                wind = s.get("wind") or s.get("wind_speed") or "none"
                if intent == "weather":
                    items.append(f"{station} {_weather_icon_label(rain, wind)} {rain} | {wind}")
                else:
                    district = s.get("district") or s.get("name") or "Unknown"
                    wms = s.get("wms_color")
                    items.append(f"{district}:wms{wms}")
            parts.append(_clip_words(f"Weather: {' | '.join(items)}", 150 if intent == "weather" else 70))
        except Exception:
            pass

    if intent == "news":
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(VPS_FEEDS)
                feeds = r.json()
            sachet_alerts = feeds.get("sachet", {}).get("alerts", []) if isinstance(feeds, dict) else []
            alerts = sorted(
                [a for a in sachet_alerts if isinstance(a, dict)],
                key=lambda a: a.get("published_at") or "",
                reverse=True,
            )[:5]
            news_bits = []
            for alert in alerts:
                district = alert.get("location_match") or alert.get("district") or "Odisha"
                summary = alert.get("summary") or alert.get("title") or "Untitled alert"
                published_at = alert.get("published_at") or "unknown time"
                news_bits.append(f"{district} — {summary} — {published_at}")
            parts.append(_clip_words(f"News: {' | '.join(news_bits)}", 150))
        except Exception:
            pass

    if intent in {"tweet", "summary", "whatsapp"}:
        try:
            conn = psycopg2.connect(os.getenv("URI", ""))
            cur = conn.cursor()
            if intent in {"tweet", "summary"}:
                cur.execute("""
                    SELECT district,
                           summary,
                           severity,
                           reliability_score,
                           verified,
                           text,
                           timestamp,
                           station_proximity
                    FROM social_signals
                    WHERE platform = 'twitter'
                    ORDER BY severity DESC NULLS LAST,
                             reliability_score DESC NULLS LAST,
                             timestamp DESC
                    LIMIT 5
                """)
                rows = cur.fetchall()
                if rows:
                    tweet_context = _clip_words(
                        "Tweets: " + " | ".join(
                            f"{r[0] or 'Unknown'} / {r[1] or r[5] or 'No summary'} / sev {r[2] if r[2] is not None else 0} / rel {r[3] if r[3] is not None else 0} / {'verified' if r[4] else 'unverified'}"
                            for r in rows
                        ),
                        90 if intent == "tweet" else 120
                    )
                    logging.info(f"TWEET CONTEXT: {tweet_context}")
                    parts.append(tweet_context)
                else:
                    logging.info("TWEET CONTEXT: NONE")
                    if intent == "tweet":
                        parts.append("Tweets: No Twitter signals available in social_signals.")
            if intent in {"whatsapp", "summary"}:
                cur.execute("""
                    SELECT district, summary, severity, sender
                    FROM social_signals
                    WHERE source = 'whatsapp'
                    ORDER BY severity DESC NULLS LAST, COALESCE(timestamp, fetched_at) DESC
                    LIMIT 3
                """)
                rows = cur.fetchall()
                if rows:
                    parts.append(_clip_words(
                        "WhatsApp: " + " | ".join(
                            f"{r[0] or 'Unknown'} / {r[1] or 'No summary'} / sev {r[2] if r[2] is not None else 0} / {r[3] or 'unknown sender'}"
                            for r in rows
                        ),
                        60 if intent == "whatsapp" else 90
                    ))
            cur.close()
            conn.close()
        except Exception as exc:
            logging.info(f"TWEET CONTEXT ERROR: {exc}")
            if intent == "tweet":
                parts.append("Tweets: No Twitter signals available in social_signals.")

    if intent in {"sos", "summary"}:
        try:
            sos_data = await api_sos_active()
            boats_data = api_boats()
            if isinstance(boats_data, list):
                counts = {
                    "safe": sum(1 for b in boats_data if b.get("status") == "Safe"),
                    "active": sum(1 for b in boats_data if b.get("status") == "Active"),
                    "enroute": sum(1 for b in boats_data if b.get("status") == "En Route"),
                }
            else:
                counts = {"safe": 0, "active": 0, "enroute": 0}
            if isinstance(sos_data, dict) and sos_data.get("active"):
                boat_bits = [
                    f"{b.get('call_sign')} {b.get('distance_km')}km {b.get('route_risk') or 'Moderate'}"
                    for b in sos_data.get("boats", [])[:3]
                ]
                parts.append(_clip_words(
                    f"SOS: active at {sos_data.get('station') or 'unknown station'}; boats {' | '.join(boat_bits)}; fleet safe {counts['safe']} active {counts['active']} enroute {counts['enroute']}",
                    60 if intent == "sos" else 90
                ))
            elif intent == "sos":
                parts.append(_clip_words(
                    f"SOS: none active; fleet safe {counts['safe']} active {counts['active']} enroute {counts['enroute']}",
                    45
                ))
        except Exception:
            pass

    return _clip_words(" ".join(parts), 550)


async def _chat_llm(message: str, intent: str, context: str) -> Dict:
    live_count = int(_station_context_cache.get("live_count") or 0)
    stale_count = int(_station_context_cache.get("stale_count") or 0)
    system_prompt = (
        "You are SahayakMap Intel, a flood ops assistant for Rajesh Sharma, "
        "NDRF commander in Odisha. Answer in max 3 sentences. Be direct and tactical. "
        "Flag fake signals clearly. Prioritize life safety. "
        "STRICT RULES: "
        "- Never state counts or values not explicitly in the context provided. "
        "- Never invent station names, WSE values, or alert statuses. "
        "- If context says 6 live stations, say 6 — not 12. "
        "- If all stations show NORMAL, say all normal. "
        "- Do not extrapolate or infer beyond given data. "
        f"You have data from {live_count} live stations and {stale_count} stale stations excluded. "
        f"Current time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
    )
    if intent == "tweet":
        system_prompt += (
            " For each tweet, state: VERIFIED or LIKELY FAKE. "
            "Fake signals: contradict gauge data, implausible location, single unverified source."
        )
    if intent == "whatsapp":
        system_prompt += (
            " Summarize top 3 WhatsApp reports in one line each. "
            "Format: [District] — [what happened] — [severity]."
        )
    if intent == "weather":
        system_prompt += (
            " Summarize weather conditions per station. "
            "Flag any DANGER or ALERT conditions first. "
            "Be specific about district and threat type."
        )
    if intent == "news":
        system_prompt += (
            " Summarize these Sachet weather alerts for Rajesh in plain English. "
            "State district, threat type, and timeframe. Be direct and tactical."
        )
    if intent == "radar":
        system_prompt += (
            " You are analyzing Paradip Doppler radar for Odisha. "
            "Radar shows reflectivity (dBZ) — blue/green=light rain, "
            "yellow=moderate, red/purple=heavy/severe. "
            "Key stations: Naraj(Cuttack), Jenapur(Jajpur), "
            "Anandpur(Keonjhar), Akhuapada(Bhadrak). "
            "Give Rajesh a 2-sentence plain English summary: "
            "where storm cells are, which stations are threatened, "
            "estimated arrival time if moving southeast."
        )
    user_prompt = f"Context: {context}\n\nUser question: {message}"

    groq_key = os.getenv("GROQ_API_KEY") or os.getenv("GROQ_API") or ""
    openrouter_key = os.getenv("OPENROUTER_API_KEY") or ""

    if intent == "radar":
        logging.info("RADAR INTENT TRIGGERED")
        auth_header = f"Bearer {groq_key}".strip()
        if auth_header in {"", "Bearer"}:
            return {"reply": "Intel unavailable. Check dashboard directly.", "model_used": "unavailable", "tokens_used": 0}
        radar_url = "https://mausam.imd.gov.in/Radar/caz_pdp.gif"
        image_payload = None
        img_b64 = ""
        radar_context = context
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(radar_url)
                if r.status_code < 400 and r.content:
                    img_b64 = base64.b64encode(r.content).decode()
                    image_payload = {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/gif;base64,{img_b64}"},
                    }
        except Exception:
            image_payload = None
        logging.info(
            "RADAR IMAGE: payload type=%s, size=%s bytes",
            type(image_payload),
            len(img_b64) if img_b64 else 0,
        )
        if image_payload is None:
            radar_context = f"{context}\nRadar image unavailable — gauge data only."
        payload = {
            "model": "meta-llama/llama-4-scout-17b-16e-instruct",
            "messages": [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": [{"type": "text", "text": f"Context: {radar_context}\n\nUser question: {message}"}] + ([image_payload] if image_payload else []),
                },
            ],
            "max_tokens": 150,
        }
        async with httpx.AsyncClient(timeout=30) as client:
            try:
                r = await client.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={"Authorization": auth_header},
                    json=payload,
                )
                if r.status_code < 400:
                    data = r.json()
                    reply = (
                        data.get("choices", [{}])[0]
                        .get("message", {})
                        .get("content", "")
                        .strip()
                    )
                    if reply:
                        usage = data.get("usage", {}) if isinstance(data, dict) else {}
                        return {
                            "reply": reply,
                            "model_used": "meta-llama/llama-4-scout-17b-16e-instruct",
                            "tokens_used": usage.get("total_tokens", 0),
                        }
            except Exception:
                pass
        return {"reply": "Intel unavailable. Check dashboard directly.", "model_used": "unavailable", "tokens_used": 0}

    providers = [
        {
            "name": "meta-llama/llama-4-scout-17b-16e-instruct",
            "url": "https://api.groq.com/openai/v1/chat/completions",
            "headers": {"Authorization": f"Bearer {groq_key}"},
        },
        {
            "name": "llama-3.3-70b-versatile",
            "url": "https://api.groq.com/openai/v1/chat/completions",
            "headers": {"Authorization": f"Bearer {groq_key}"},
        },
        {
            "name": "mistralai/mistral-7b-instruct",
            "url": "https://openrouter.ai/api/v1/chat/completions",
            "headers": {"Authorization": f"Bearer {openrouter_key}"},
        },
        {
            "name": "meta-llama/llama-3-8b-instruct",
            "url": "https://openrouter.ai/api/v1/chat/completions",
            "headers": {"Authorization": f"Bearer {openrouter_key}"},
        },
    ]

    async with httpx.AsyncClient(timeout=20) as client:
        for provider in providers:
            auth_header = provider["headers"].get("Authorization", "")
            if not auth_header.endswith(" ") and auth_header.strip() in {"Bearer", ""}:
                continue
            payload = {
                "model": provider["name"],
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "max_tokens": 150,
            }
            try:
                r = await client.post(provider["url"], headers=provider["headers"], json=payload)
                if r.status_code == 429:
                    continue
                if r.status_code >= 400:
                    continue
                data = r.json()
                reply = (
                    data.get("choices", [{}])[0]
                    .get("message", {})
                    .get("content", "")
                    .strip()
                )
                if reply:
                    usage = data.get("usage", {}) if isinstance(data, dict) else {}
                    return {
                        "reply": reply,
                        "model_used": provider["name"],
                        "tokens_used": usage.get("total_tokens", 0),
                    }
            except Exception:
                continue
    return {"reply": "Intel unavailable. Check dashboard directly.", "model_used": "unavailable", "tokens_used": 0}


# ──────────────────────────────────────────────
#  Routes
# ──────────────────────────────────────────────

@app.get("/api/stations")
async def api_stations():
    """Proxy to VPS data API — stations with latest WSE."""
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(f"{VPS_DATA_API}/data/stations")
            stations = r.json()
    except Exception:
        return JSONResponse({"error": "VPS data API unreachable"}, status_code=502)

    # Attach model output without retraining; predict() loads existing model files.
    for s in stations:
        wse = s.get("latest_wse")
        ts = s.get("latest_timestamp")
        name = s.get("name", "")

        s["forecast_8h"] = None
        s["forecast_24h"] = None
        s["forecast"] = []
        s["confidence_pct"] = None

        if wse is None or ts is None:
            s["wse_source"] = "stale"
            s["data_age_hours"] = 999
            s["label"] = "No data available"
            continue

        age_hours = (datetime.now(timezone.utc) - datetime.fromisoformat(ts.replace("Z", "+00:00"))).total_seconds() / 3600
        s["data_age_hours"] = round(age_hours, 1)

        pred = None
        try:
            from ml_forecast import predict
            pred = predict(name)
        except Exception:
            pred = None

        if pred:
            forecast = pred.get("forecast") or []
            s["forecast"] = [
                {
                    "hour": item.get("hour"),
                    "wse": item.get("wse"),
                    "lower": item.get("lower"),
                    "upper": item.get("upper"),
                }
                for item in forecast
            ]
            s["forecast_8h"] = pred.get("forecast_8h")
            s["forecast_24h"] = pred.get("forecast_24h")

        if age_hours <= 48:
            s["wse_source"] = "live"
            s["label"] = f"{wse}m (live)"
        elif age_hours > 168:
            s["wse_source"] = "stale"
            s["label"] = f"Data unavailable — last reading {age_hours / 24:.0f}d ago"
        else:
            # Recent stale data may use the forecast if the model agrees with the last reading.
            forecast_val = s["forecast_8h"]
            if forecast_val is not None and wse > 0 and forecast_val > 0:
                ratio = min(wse, forecast_val) / max(wse, forecast_val)
                diff = abs(wse - forecast_val)
                if ratio >= 0.93 and diff <= 1.5:
                    s["wse_source"] = "predicted"
                    s["confidence_pct"] = round(ratio * 100, 1)
                    s["label"] = f"{forecast_val}m (model)"
                else:
                    s["wse_source"] = "stale"
                    s["label"] = f"Model divergence — data {age_hours:.0f}h old"
            else:
                s["wse_source"] = "stale"
                s["label"] = f"No forecast model — data {age_hours:.0f}h old"

    return stations


@app.get("/api/alerts")
def api_alerts():
    """Current active alerts ranked by priority."""
    if ALERTS_FILE.exists():
        try:
            with open(ALERTS_FILE) as f:
                alerts = json.load(f)
        except Exception:
            alerts = []
    else:
        alerts = []

    alerts = [a for a in alerts if a.get("data_age_min", 0) < 1440]
    alerts.sort(key=lambda a: (a.get("priority", 99), -a.get("confidence", 0)))
    return alerts[:20]


@app.get("/api/chart/{station}")
async def api_chart(station: str, days: int = 30):
    """WSE history from VPS + Prophet forecast from local models."""
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(f"{VPS_DATA_API}/data/chart/{station}", params={"days": days})
            data = r.json()
            sr = await client.get(f"{VPS_DATA_API}/data/stations")
            stations = sr.json()
    except Exception:
        return JSONResponse({"error": "VPS data API unreachable"}, status_code=502)

    latest_ts = None
    for item in stations:
        if item.get("name") == station:
            latest_ts = item.get("latest_timestamp")
            break
    data["latest_timestamp"] = latest_ts

    if latest_ts and data.get("timestamps") and data.get("values"):
        try:
            latest_dt = datetime.fromisoformat(latest_ts.replace("Z", "+00:00"))
            filtered = []
            for ts, value in zip(data["timestamps"], data["values"]):
                dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                if dt <= latest_dt:
                    filtered.append((ts, value))
            data["timestamps"] = [ts for ts, _ in filtered]
            data["values"] = [value for _, value in filtered]
        except Exception:
            pass

    data["forecast"] = None

    # Attach Prophet 7-day forecast
    try:
        from ml_forecast import predict
        pred = predict(station)
        if pred:
            fc = pred.get("forecast", [])
            data["forecast"] = {
                "curve": fc,
                "trained_at": pred["trained_at"],
                "low_confidence": pred.get("low_confidence", False),
                "proxy_used": pred.get("proxy_used"),
                "timestamps": [p["timestamp"] for p in pred["predictions"]],
                "yhat": [p["yhat"] for p in pred["predictions"]],
                "yhat_lower": [p["yhat_lower"] for p in pred["predictions"]],
                "yhat_upper": [p["yhat_upper"] for p in pred["predictions"]],
                "thresholds_detected": pred["thresholds_detected"],
            }
    except Exception:
        pass

    return data


@app.get("/api/social")
def api_social(minutes: int = 60):
    """Social signals from Supabase social_signals (live) + fixtures fallback."""
    signals = []

    # Try Supabase first (real data from social_agent.py)
    try:
        conn = psycopg2.connect(os.getenv("URI", ""))
        cur = conn.cursor()
        cur.execute("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'social_signals'
        """)
        columns = {r[0] for r in cur.fetchall()}

        text_col = "raw_text" if "raw_text" in columns else "text"
        ts_col = "published_at" if "published_at" in columns else "timestamp" if "timestamp" in columns else "fetched_at"
        district_expr = "district" if "district" in columns else "NULL::text AS district"
        source_expr = "source" if "source" in columns else "'twitter'::text AS source"
        platform_expr = "platform" if "platform" in columns else "'twitter'::text AS platform"
        location_expr = "location" if "location" in columns else "NULL::text AS location"
        coords_expr = "CAST(coordinates AS TEXT)" if "coordinates" in columns else "NULL::text AS coordinates"
        severity_expr = "severity" if "severity" in columns else "0 AS severity"
        event_type_expr = "event_type" if "event_type" in columns else "NULL::text AS event_type"
        station_expr = "station_proximity" if "station_proximity" in columns else "NULL::text AS station_proximity"
        summary_expr = "summary" if "summary" in columns else f"LEFT({text_col}, 220) AS summary"
        reliability_expr = "reliability_score" if "reliability_score" in columns else "0 AS reliability_score"
        flags_expr = "credibility_flags" if "credibility_flags" in columns else "NULL::jsonb AS credibility_flags"
        verified_expr = "verified" if "verified" in columns else "false AS verified"
        sender_expr = "sender" if "sender" in columns else "NULL::text AS sender"

        query = f"""
            WITH latest AS (
                SELECT MAX({ts_col}) AS max_ts
                FROM social_signals
                WHERE {ts_col} IS NOT NULL
            )
            SELECT {source_expr}, {platform_expr}, {district_expr}, {text_col},
                   {location_expr}, {coords_expr}, {severity_expr}, {event_type_expr},
                   {station_expr}, {summary_expr}, {reliability_expr},
                   {flags_expr}, {verified_expr}, {ts_col}, {sender_expr}
            FROM social_signals, latest
            WHERE latest.max_ts IS NOT NULL
              AND {ts_col} >= date_trunc('day', latest.max_ts AT TIME ZONE 'UTC')
              AND {ts_col} < date_trunc('day', latest.max_ts AT TIME ZONE 'UTC') + INTERVAL '1 day'
            ORDER BY {ts_col} DESC LIMIT 50
        """
        cur.execute(query)
        rows = cur.fetchall()
        cur.close(); conn.close()

        for r in rows:
            signals.append({
                "source": r[0], "platform": r[1], "district": r[2],
                "text": r[3], "location": r[4], "coordinates": r[5],
                "severity": r[6], "event_type": r[7], "station_proximity": r[8],
                "summary": r[9], "reliability_score": r[10],
                "credibility_flags": r[11], "verified": r[12],
                "timestamp": str(r[13]) if r[13] else None,
                "sender": r[14],
            })

        if signals:
            signals.sort(key=lambda s: (s.get("verified", False), s.get("severity", 0)), reverse=True)
            return signals
    except Exception:
        pass

    # Fallback to dummy fixtures
    latest_ts = None

    for fname in ["dummy_twitter.json", "dummy_whatsapp.json"]:
        path = FIXTURES_DIR / fname
        if not path.exists():
            continue
        try:
            with open(path) as f:
                items = json.load(f)
            for item in items:
                ts = datetime.fromisoformat(item["timestamp"]).replace(tzinfo=timezone.utc)
                if latest_ts is None or ts > latest_ts:
                    latest_ts = ts
                item["platform"] = "twitter" if "twitter" in fname else "whatsapp"
                signals.append(item)
        except Exception:
            continue

    if latest_ts is not None:
        latest_day = latest_ts.date()
        signals = [
            item for item in signals
            if datetime.fromisoformat(item["timestamp"]).replace(tzinfo=timezone.utc).date() == latest_day
        ]

    signals.sort(key=lambda s: s.get("timestamp", ""), reverse=True)
    return signals


@app.get("/api/sos/{station}")
async def api_sos(station: str):
    """SOS triage: WSE, forecast, HFL countdown, route risk, nearest boats."""
    if station == "active":
        return await api_sos_active()

    try:
        from triage_logic import triage, format_triage, haversine
    except ImportError:
        return JSONResponse({"error": "Triage module not available"}, status_code=500)

    # Get station data from cached stations (avoids re-fetching all stations)
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(f"{VPS_DATA_API}/data/stations")
        stations = r.json()

    st = next((s for s in stations if s["name"] == station), None)
    if not st:
        raise HTTPException(404, f"Station not found: {station}")

    wse = st.get("latest_wse")
    hfl = st.get("hfl")
    lat = st.get("lat", 20.5)
    lon = st.get("lon", 84.5)

    result = {
        "station": station,
        "current_wse": wse,
        "hfl": hfl,
        "warning_level": st.get("warning_level"),
        "danger_level": st.get("danger_level"),
        "alert_status": st.get("alert_status"),
        "data_age_hours": st.get("data_age_hours"),
        "wse_source": st.get("wse_source"),
    }

    # Prophet forecast
    try:
        from ml_forecast import predict
        pred = predict(station)
        if pred and pred.get("predictions"):
            p0 = pred["predictions"][0]
            result["forecast_8h"] = p0["yhat"]
            result["forecast_upper_ci"] = p0["yhat_upper"]
            result["forecast_lower_ci"] = p0["yhat_lower"]
            result["forecast_confidence"] = pred.get("confidence_interval")
    except Exception:
        result["forecast_8h"] = None

    # Evacuate window
    if wse and hfl and hfl > (wse or 0):
        try:
            ch = await client.get(f"{VPS_DATA_API}/data/chart/{station}", params={"days": 7})
            chart = ch.json()
            vals = chart.get("values", [])
            if len(vals) >= 2:
                rise_rate = (vals[-1] - vals[-2]) / 8  # m/hr (8h interval)
                if rise_rate > 0:
                    hours_to_hfl = round((hfl - (result.get("forecast_upper_ci", result.get("forecast_8h") or wse))) / rise_rate, 1)
                    result["rise_rate_mph"] = round(rise_rate, 4)
                    result["hours_to_hfl"] = max(0, hours_to_hfl)
                    result["evacuate_window"] = f"~{max(0, hours_to_hfl):.0f} hours"
        except Exception:
            pass

    # Triage: nearest boats + road risk + safe zone
    try:
        triage_result = triage(lat, lon)
        boats = triage_result.get("nearest_boats", [])
        result["nearest_boats"] = [{
            "team_id": b["team_id"], "call_sign": b["call_sign"],
            "distance_km": b["distance_km"], "district": b["district"], "status": b["status"]
        } for b in boats[:3]]
        risks = triage_result.get("road_alerts", [])
        if risks:
            result["route_risk"] = risks[0]["road_name"]
            result["route_risk_level"] = risks[0]["risk_level"]
        sz = triage_result.get("safe_zone")
        if sz:
            result["nearest_safe_zone"] = f"{sz['name']} ({sz['type']})"
        if triage_result.get("escalate"):
            result["triage_escalate"] = True
            result["triage_escalate_reason"] = triage_result["escalate_reason"]
    except Exception:
        pass

    return result


# ── TASK 9: PDF Export ────────────────────────────
@app.get("/api/export/sos/{event_id}")
async def api_export_sos(event_id: str, station: str = "Naraj"):
    """Generate timestamp-locked EOC justification PDF."""
    try:
        from pdf_export import generate
        path = generate(event_id, station)
        return FileResponse(path, media_type="application/pdf",
                           filename=Path(path).name)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ── TASK 12: WhatsApp Twilio Webhook ───────────────
@app.post("/api/whatsapp")
async def api_whatsapp(request: Request):
    """Receive WhatsApp messages via Twilio webhook & feed into social_signals."""
    import hashlib, re

    form = await request.form()
    body = (form.get("Body") or "").strip()
    sender_full = (form.get("From") or "").strip()
    lat = form.get("Latitude")
    lon = form.get("Longitude")
    sender = sender_full[-4:] if len(sender_full) >= 4 else sender_full

    if not body:
        return Response(content='<Response><Message>Empty message received.</Message></Response>', media_type="application/xml")

    # Keyword filter (same as social_agent.py)
    keywords = ["submerged","breach","stuck","rescue","flood","trapped",
                "washed","overflow","stranded","NH-16","SH-42","SH-24",
                "Naraj","Jenapur","Anandpur","Akhuapada","Tikarpara",
                "Kantamal","Salebhata","Purusottampur","Mahanadi",
                "Brahmani","Baitarani","Cuttack","Jajpur","Bhadrak",
                "Keonjhar","Angul","Boudh","Bargarh","Ganjam","help","alert","danger"]
    lower = body.lower()
    has_keyword = any(k.lower() in lower for k in keywords)
    has_coords = lat is not None and lon is not None
    if "forest fire" in lower:
        return Response(content='<Response><Message>✅ Received.</Message></Response>', media_type="application/xml")
    if not has_keyword and not has_coords:
        return Response(content='<Response><Message>✅ Received.</Message></Response>', media_type="application/xml")

    # Dedup
    text_hash = hashlib.sha256(body.encode()).hexdigest()[:16]
    try:
        conn = psycopg2.connect(os.getenv("URI", ""))
        cur = conn.cursor()
        cur.execute("SELECT id FROM social_signals WHERE content_hash=%s AND fetched_at > NOW() - INTERVAL '2 hours'", [text_hash])
        if cur.fetchone():
            cur.close(); conn.close()
            return Response(content='<Response><Message>✅ Received.</Message></Response>', media_type="application/xml")
        cur.close(); conn.close()
    except: pass

    # LLM extraction (with fallback)
    extract = {"location": None, "coordinates": None, "severity": 2, "event_type": "flood",
               "station_proximity": None, "summary": body[:80], "reliability_score": 2,
               "credibility_flags": [], "coordinates_source": "unknown"}
    try:
        openrouter_key = os.getenv("OPENROUTER_API_KEY", "")
        if openrouter_key:
            station_guide = "Naraj=20.4706,85.9321 Jenapur=20.8489,86.1922 Anandpur=21.2167,86.1333 Akhuapada=21.0667,86.5167 Tikarpara=20.5833,84.7833 Kantamal=20.6333,83.7167 Salebhata=21.5167,83.5333 Purusottampur=19.4167,84.9667 Rengali=21.3833,84.0667"
            resp = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {openrouter_key}"},
                json={"model": "openai/gpt-4o-mini", "messages": [
                    {"role": "system", "content": f"Extract flood info. If GPS outside Odisha bbox 19.3-21.7N,83.3-86.7E, ignore and infer from place names using: {station_guide}. Return JSON: location,coordinates[lat,lon],severity(1-5),event_type,station_proximity,summary(20 words),reliability_score(1-5),credibility_flags[],coordinates_source('gps'|'inferred'|'unknown')"},
                    {"role": "user", "content": body}],
                "temperature": 0.1, "max_tokens": 300}, timeout=15)
            raw = resp.json()["choices"][0]["message"]["content"]
            match = re.search(r'\{.*\}', raw, re.DOTALL)
            if match: extract = json.loads(match.group())
    except: pass

    # Validate/infer coordinates
    if lat and lon:
        try:
            la, lo = float(lat), float(lon)
            if 19.3 <= la <= 21.7 and 83.3 <= lo <= 86.7:
                extract["coordinates"] = [la, lo]
                extract["coordinates_source"] = "gps"
        except: pass

    # Reliability scoring
    trusted = (os.getenv("TRUSTED_SENDERS", "")).split(",")
    reliability = 2
    if sender_full in trusted: reliability += 1
    if extract.get("coordinates_source") == "unknown": reliability -= 1
    if extract.get("station_proximity"): reliability = max(reliability, 3)
    reliability = max(1, min(5, reliability))

    # Insert
    try:
        conn = psycopg2.connect(os.getenv("URI", ""))
        cur = conn.cursor()
        coords = extract.get("coordinates")
        la, lo = (coords[0], coords[1]) if isinstance(coords, list) and len(coords) >= 2 else (None, None)
        cur.execute("INSERT INTO social_signals (source,platform,raw_text,location,coordinates,severity,event_type,station_proximity,summary,reliability_score,credibility_flags,verified,content_hash,fetched_at,timestamp,coordinates_source,sender) VALUES (%s,%s,%s,%s,point(%s,%s),%s,%s,%s,%s,%s,%s,false,%s,NOW(),NOW(),%s,%s)",
            ["whatsapp","whatsapp",body,extract.get("location"),la,lo,extract.get("severity",2),extract.get("event_type","flood"),extract.get("station_proximity"),extract.get("summary",body[:80]),reliability,json.dumps(extract.get("credibility_flags",[])),text_hash,extract.get("coordinates_source","unknown"),sender])
        conn.commit(); cur.close(); conn.close()
    except Exception as e:
        return Response(content='<Response><Message>✅ Received.</Message></Response>', media_type="application/xml")

    # Silent source check
    try:
        stations_res = requests.get("https://www.joodei.org/sahayak-data/data/stations", timeout=10).json()
        active = any(s.get("latest_wse",0) >= (s.get("warning_level") or 999) for s in stations_res)
        if active:
            for t in trusted:
                t4 = t[-4:] if len(t) >= 4 else t
                conn = psycopg2.connect(os.getenv("URI", ""))
                cur = conn.cursor()
                cur.execute("SELECT id FROM social_signals WHERE sender=%s AND source='whatsapp' AND timestamp > NOW() - INTERVAL '2 hours'", [t4])
                silent = cur.fetchone() is None
                cur.execute("SELECT id FROM alerts WHERE rule_id='WA-SILENT-SOURCE' AND district=%s AND created_at > NOW() - INTERVAL '2 hours'", [t4])
                dup = cur.fetchone() is not None
                if silent and not dup:
                    cur.execute("INSERT INTO alerts (rule_id,priority,district,title,detail,action,confidence,created_at) VALUES ('WA-SILENT-SOURCE',1,%s,%s,%s,%s,0.85,NOW())",
                        [t4, f"SILENT SOURCE: {t4}. No field report in 2h during active flood. Possible comms failure — verify immediately.", f"Trusted sender {t4} has not reported in 2h while WSE is above warning.", "Verify comms status with field team immediately."])
                    conn.commit()
                cur.close(); conn.close()
    except: pass

    return Response(content='<Response><Message>✅ Report received. SahayakMap intelligence updated.</Message></Response>', media_type="application/xml")


@app.get("/")
def serve_index():
    return FileResponse("templates/index.html")


@app.get("/api/state")
def api_state():
    """Scraper state information."""
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {}


@app.post("/api/chat")
async def api_chat(request: Request):
    """SahayakMap intelligence chat."""
    logging.info("CHAT HIT")
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    message = str((payload or {}).get("message") or "").strip()
    if not message:
        return JSONResponse({"error": "message required"}, status_code=400)

    intent = _detect_intent(message)
    logging.info(f"INTENT DETECTED: {intent}")
    context = await _build_chat_context(intent)
    log.info("CHAT CONTEXT: %s", context)
    result = await _chat_llm(message, intent, context)
    log.info(
        "chat_query intent=%s tokens_used=%s model_used=%s",
        intent,
        result.get("tokens_used", 0),
        result.get("model_used", "unavailable"),
    )
    return {"reply": result.get("reply", "Intel unavailable. Check dashboard directly.")}


@app.get("/api/boats")
def api_boats():
    """Boat asset positions for Leaflet map markers."""
    try:
        conn = psycopg2.connect(os.getenv("URI", ""))
        cur = conn.cursor()
        cur.execute("""
            SELECT call_sign, status, lat, lon,
                   MAX(last_ping) AS last_ping,
                   nearest_station
            FROM boat_assets
            GROUP BY call_sign, status, lat, lon, nearest_station
            ORDER BY call_sign
        """)
        rows = cur.fetchall()
        cur.close(); conn.close()
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

    return [
        {
            "call_sign": r[0],
            "status": r[1],
            "lat": r[2],
            "lon": r[3],
            "last_ping": r[4].isoformat().replace("+00:00", "Z") if r[4] else None,
            "nearest_station": r[5],
        }
        for r in rows
    ]


# ── 2G Fallback — /api/pulse (< 200 bytes) ──────
STATION_CODES = {
    "Naraj": "NAR", "Jenapur": "JEN", "Anandpur": "ANA",
    "Akhuapada": "AKH", "Tikarpara": "TIK", "Kantamal": "KAN",
    "Salebhata": "SAL", "Purusottampur": "PUR", "Rengali Reservoir": "REN",
}
LEVEL_MAP = {"NORMAL": 0, "WARNING": 1, "DANGER": 2, "EXTREME": 3, "NO_DATA": 9, "STALE": 9}


@app.get("/api/pulse")
async def api_pulse():
    """v2: Compact 2G-friendly summary with nearest boat (<200 bytes)."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"{VPS_DATA_API}/data/stations")
            stations = r.json()
    except Exception:
        return JSONResponse({"error": "VPS unreachable"}, status_code=502)

    # Get nearest boats per station
    boat_map = {}
    try:
        import psycopg2
        conn = psycopg2.connect(os.getenv("URI", ""))
        cur = conn.cursor()
        cur.execute("SELECT team_id, nearest_station FROM boat_assets WHERE status IN ('Safe','Active','En Route')")
        for b in cur.fetchall():
            if b[1] and b[1] not in boat_map:
                boat_map[b[1]] = b[0]
        cur.close(); conn.close()
    except Exception:
        pass

    parts = []
    for s in stations:
        code = STATION_CODES.get(s.get("name", ""), "???")
        wse = s.get("latest_wse")
        wse_str = f"{wse:.1f}" if wse is not None else "0.0"
        status = s.get("alert_status", "STALE")
        level = LEVEL_MAP.get(status, 9)
        boat = boat_map.get(s.get("name", ""), "--")
        parts.append(f"{code},{wse_str},{status},{level},{boat}")

    return "|".join(parts)


# ── VPS CORS proxies ─────────────────────────────

VPS_AIRCRAFT = "http://72.60.98.178:8003/api/aircraft"
VPS_FEEDS    = "http://72.60.98.178:8004/api/feeds"


@app.get("/api/vps/aircraft")
async def proxy_aircraft():
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(VPS_AIRCRAFT)
            return r.json()
    except Exception:
        return {"error": "VPS unreachable", "aircraft": []}


@app.get("/api/vps/feeds")
async def proxy_feeds():
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(VPS_FEEDS)
            return r.json()
    except Exception:
        return {"error": "VPS unreachable", "stations": [], "alerts": []}


# ── Sachet RSS proxy ────────────────────────────
@app.get("/api/sachet")
async def proxy_sachet():
    current_alerts = []
    fetched_at = None
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            r = await client.get("https://www.joodei.org/sachet_rss_latest")
            payload = r.json()
            if isinstance(payload, dict):
                fetched_at = payload.get("fetched_at")
                current_alerts = payload.get("alerts", []) if isinstance(payload.get("alerts"), list) else []
    except Exception:
        current_alerts = []

    previous_day_alerts = []
    try:
        conn = psycopg2.connect(os.getenv("URI", ""))
        cur = conn.cursor()
        cur.execute("""
            SELECT DISTINCT ON (LOWER(title))
                title,
                published_at,
                location_match
            FROM sachet_rss_entries
            WHERE published_at >= date_trunc('day', NOW() AT TIME ZONE 'UTC') - INTERVAL '1 day'
              AND published_at <  date_trunc('day', NOW() AT TIME ZONE 'UTC')
              AND LOWER(COALESCE(title, '')) NOT LIKE '%%forest fire%%'
            ORDER BY LOWER(title), published_at DESC
        """)
        current_titles = {str(a.get("title", "")).strip().lower() for a in current_alerts}
        for title, published_at, location_match in cur.fetchall():
            key = str(title or "").strip().lower()
            if not key or key in current_titles:
                continue
            previous_day_alerts.append({
                "title": title,
                "published_at": str(published_at) if published_at else None,
                "location_match": location_match or "",
                "out_of_zone": False,
            })
        cur.close()
        conn.close()
    except Exception:
        previous_day_alerts = []

    return {
        "fetched_at": fetched_at,
        "alerts": current_alerts,
        "previous_day_alerts": previous_day_alerts[:20],
    }


@app.get("/api/rss")
async def proxy_rss(url: str = "https://www.joodei.org/sachet_rss_latest"):
    try:
        import feedparser
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            r = await client.get(url, headers={"User-Agent": "SahayakMap/1.0"})
            r.raise_for_status()
        feed = feedparser.parse(r.content)
        return [
            {"title": e.get("title",""), "link": e.get("link",""),
             "published": e.get("published", e.get("updated","")),
             "source": feed.feed.get("title", url)}
            for e in feed.entries[:10]
        ]
    except Exception:
        return []


# ── Telegram team state ──────────────────────────
@app.get("/api/telegram/state")
async def api_telegram_state():
    """Proxy VPS telegram state — with local fallback."""
    # Try VPS first (bot runs there)
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            r = await client.get("https://www.joodei.org/api/telegram/state")
            data = r.json()
            if data and data.get("last_poll_state") is not None:
                return data
    except Exception:
        pass
    # Local fallback
    tg_state = Path("telegram_state.json")
    if tg_state.exists():
        try:
            return json.loads(tg_state.read_text())
        except Exception:
            pass
    return {"status": "offline", "teams": {}, "last_poll": None, "wse_state": "unknown"}


@app.get("/api/sos/active")
async def api_sos_active():
    """Return the latest active SOS context from Telegram state, enriched with live triage."""
    state_paths = [
        Path("/root/Sahayak/pipeline/telegram_state.json"),
        Path("telegram_state.json"),
    ]
    tg_data = None
    for path in state_paths:
        if path.exists():
            try:
                tg_data = json.loads(path.read_text())
                break
            except Exception:
                continue

    if not tg_data or not tg_data.get("last_sos"):
        return {"active": False}

    sos = tg_data["last_sos"]
    loc = str(sos.get("location") or "").strip()
    try:
        lat_str, lon_str = [part.strip() for part in loc.split(",", 1)]
        sos_lat = float(lat_str)
        sos_lon = float(lon_str)
    except Exception:
        return {"active": False}

    station_name = None
    boats_out = []
    try:
        from triage_logic import triage, haversine

        triage_result = triage(sos_lat, sos_lon)
        route_risks = {r.get("boat"): r for r in triage_result.get("road_alerts", [])}

        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(f"{VPS_DATA_API}/data/stations")
            stations = r.json()

        best_dist = None
        for st in stations:
            if st.get("lat") is None or st.get("lon") is None:
                continue
            dist = haversine(sos_lat, sos_lon, st["lat"], st["lon"])
            if best_dist is None or dist < best_dist:
                best_dist = dist
                station_name = st.get("name")

        for boat in triage_result.get("nearest_boats", [])[:3]:
            risk = route_risks.get(boat.get("call_sign"), {})
            boats_out.append({
                "call_sign": boat.get("call_sign"),
                "lat": boat.get("lat"),
                "lon": boat.get("lon"),
                "distance_km": boat.get("distance_km"),
                "route_risk": risk.get("risk_level"),
                "road_id": risk.get("road_name"),
            })
    except Exception:
        boats_out = []

    return {
        "active": True,
        "sos_lat": sos_lat,
        "sos_lon": sos_lon,
        "station": station_name,
        "boats": boats_out,
    }
