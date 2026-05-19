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
import difflib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List
from urllib.parse import urlsplit, urlunsplit

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
PULSE_SNAPSHOT_PATH = Path("/root/Sahayak/pipeline/snapshots/stations_latest.json")
BOATS_SNAPSHOT_PATH = Path("/root/Sahayak/pipeline/snapshots/boats_latest.json")
SUPABASE_REST_URL = "https://vflimxjetrquydkznxoc.supabase.co"
SUPABASE_REST_KEY = "sb_publishable_QxFNvDdqQIwZqcJHMHM85Q_osBCxzSl"
CHART_CACHE_TTL = timedelta(hours=8)
_chart_cache: dict[tuple[str, int], dict] = {}

INTENT_RULES = {
    "gauge": ["water", "wse", "level", "gauge", "naraj", "jenapur", "station"],
    "weather": ["weather", "rain", "imd", "wind", "storm", "forecast weather", "climate", "temperature", "condition"],
    "radar": ["radar", "storm approaching", "storm cell", "approaching storm", "rain coming", "clouds moving", "precipitation", "doppler", "any storm", "storm near", "weather radar", "rain radar", "storm", "coming", "approaching", "next few hours"],
    "news": ["news", "latest", "update", "sachet", "weather alert", "warning", "what is happening", "any alert", "district alert"],
    "tweet": ["tweet", "twitter", "social", "fake", "real", "verify", "citizen"],
    "whatsapp": ["whatsapp", "message", "field team", "report"],
    "sos": ["sos", "boat", "rescue", "triage"],
    "summary": ["summary", "brief", "overview", "situation", "status"],
}

CHAT_TOOL_NAMES = ["gauges", "weather", "social", "whatsapp", "sos", "news"]

_station_context_cache = {"expires_at": None, "raw": None, "gauge": None, "live_count": 0, "stale_count": 0}
DISTRICT_TO_STATION = {
    "cuttack": "Naraj",
    "jajpur": "Jenapur",
    "keonjhar": "Anandpur",
    "kendujhar": "Anandpur",
    "bhadrak": "Akhuapada",
    "angul": "Tikarpara",
    "boudh": "Kantamal",
    "bargarh": "Salebhata",
    "ganjam": "Purusottampur",
}
DB_HOST_FALLBACKS = {
    "aws-1-ap-northeast-2.pooler.supabase.com": ["15.164.188.235", "3.39.47.126"],
}
DB_RETRY_COOLDOWN_SECONDS = 300
_db_unavailable_until = None
CANONICAL_STATION_NAMES = {
    "Purushottampur": "Purusottampur",
}


def _clip_words(text: str, max_words: int) -> str:
    words = str(text or "").split()
    return " ".join(words[:max_words])


def _station_aliases(name: str) -> list[str]:
    aliases = [name]
    if name == "Purusottampur":
        aliases.append("Purushottampur")
    return aliases


def _canonical_station_name(name: str | None) -> str | None:
    if name is None:
        return None
    return CANONICAL_STATION_NAMES.get(str(name), str(name))


def _replace_db_host(uri: str, new_host: str) -> str:
    parts = urlsplit(uri)
    if "@" not in parts.netloc:
        return uri
    auth, hostpart = parts.netloc.rsplit("@", 1)
    port = ""
    if ":" in hostpart:
        _, port = hostpart.rsplit(":", 1)
        hostpart = new_host
        return urlunsplit((parts.scheme, f"{auth}@{hostpart}:{port}", parts.path, parts.query, parts.fragment))
    return urlunsplit((parts.scheme, f"{auth}@{new_host}", parts.path, parts.query, parts.fragment))


def _supabase_rest_get(table: str, params: dict | None = None, limit: int = 50) -> list[dict]:
    """Fetch rows from Supabase REST API. Returns empty list on failure."""
    try:
        url = f"{SUPABASE_REST_URL}/rest/v1/{table}"
        headers = {
            "apikey": SUPABASE_REST_KEY,
            "Authorization": f"Bearer {SUPABASE_REST_KEY}",
            "Accept": "application/json",
        }
        query = dict(params or {})
        query.setdefault("limit", str(limit))
        r = httpx.get(url, headers=headers, params=query, timeout=8)
        if r.status_code == 200:
            data = r.json()
            return data if isinstance(data, list) else []
    except Exception:
        pass
    return []


async def _supabase_rest_get_async(table: str, params: dict | None = None, limit: int = 50) -> list[dict]:
    """Async variant of _supabase_rest_get."""
    try:
        url = f"{SUPABASE_REST_URL}/rest/v1/{table}"
        headers = {
            "apikey": SUPABASE_REST_KEY,
            "Authorization": f"Bearer {SUPABASE_REST_KEY}",
            "Accept": "application/json",
        }
        query = dict(params or {})
        query.setdefault("limit", str(limit))
        async with httpx.AsyncClient(timeout=8) as client:
            r = await client.get(url, headers=headers, params=query)
            if r.status_code == 200:
                data = r.json()
                return data if isinstance(data, list) else []
    except Exception:
        pass
    return []
    global _db_unavailable_until
    uri = os.getenv("URI", "")
    if not uri:
        raise RuntimeError("URI not configured")
    now = datetime.now(timezone.utc)
    if _db_unavailable_until and now < _db_unavailable_until:
        raise RuntimeError(
            f"DB connect cooldown active until {_db_unavailable_until.strftime('%Y-%m-%dT%H:%M:%SZ')}"
        )
    try:
        conn = psycopg2.connect(uri, connect_timeout=3)
        _db_unavailable_until = None
        return conn
    except psycopg2.OperationalError as exc:
        msg = str(exc)
        if "could not translate host name" not in msg:
            _db_unavailable_until = now + timedelta(seconds=DB_RETRY_COOLDOWN_SECONDS)
            raise
        for host, ips in DB_HOST_FALLBACKS.items():
            if host in uri:
                for ip in ips:
                    try:
                        conn = psycopg2.connect(_replace_db_host(uri, ip), connect_timeout=3)
                        _db_unavailable_until = None
                        return conn
                    except psycopg2.OperationalError:
                        continue
        _db_unavailable_until = now + timedelta(seconds=DB_RETRY_COOLDOWN_SECONDS)
        raise


def _live_station_payload_from_db() -> list[dict]:
    conn = _db_connect()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT s.name, s.river, s.district, s.lat, s.lon, s.tier,
                   s.warning_level, s.danger_level, s.hfl,
                   g.wse, g.timestamp
            FROM stations s
            LEFT JOIN LATERAL (
                SELECT wse, timestamp
                FROM gauge_readings g
                WHERE g.station_id = s.id AND g.wse IS NOT NULL
                ORDER BY g.timestamp DESC
                LIMIT 1
            ) g ON TRUE
            ORDER BY s.id
            """
        )
        rows = cur.fetchall()
    finally:
        cur.close()
        conn.close()

    payload = []
    for row in rows:
        name = _canonical_station_name(row[0])
        latest_wse = float(row[9]) if row[9] is not None else None
        latest_ts = row[10].astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if row[10] else None
        payload.append({
            "name": name,
            "river": row[1],
            "district": row[2],
            "lat": row[3],
            "lon": row[4],
            "tier": row[5],
            "warning_level": row[6],
            "danger_level": row[7],
            "hfl": row[8],
            "latest_wse": latest_wse,
            "latest_timestamp": latest_ts,
            "alert_status": "NO_DATA" if latest_wse is None else (
                "EXTREME" if row[8] is not None and latest_wse >= row[8] else
                "DANGER" if row[7] is not None and latest_wse >= row[7] else
                "WARNING" if row[6] is not None and latest_wse >= row[6] else
                "NORMAL"
            ),
        })
    return payload


def _live_chart_payload_from_db(station: str, days: int = 30) -> dict | None:
    conn = _db_connect()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT s.warning_level, s.danger_level, s.hfl
            FROM stations s
            WHERE s.name = ANY(%s)
            LIMIT 1
            """,
            [_station_aliases(station)],
        )
        meta = cur.fetchone()
        cur.execute(
            """
            SELECT g.timestamp, g.wse
            FROM gauge_readings g
            JOIN stations s ON s.id = g.station_id
            WHERE s.name = ANY(%s) AND g.wse IS NOT NULL
            ORDER BY g.timestamp
            """,
            [_station_aliases(station)],
        )
        rows = cur.fetchall()
    finally:
        cur.close()
        conn.close()
    if not rows:
        return None
    latest_ts = rows[-1][0]
    cutoff = latest_ts - timedelta(days=days)
    filtered = [(ts, wse) for ts, wse in rows if ts >= cutoff]
    return {
        "station": station,
        "timestamps": [ts.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") for ts, _ in filtered],
        "values": [float(wse) for _, wse in filtered],
        "thresholds": {
            "warning": meta[0] if meta else None,
            "danger": meta[1] if meta else None,
            "hfl": meta[2] if meta else None,
        },
        "latest_timestamp": latest_ts.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def _looks_like_flood_claim(text: str) -> bool:
    t = str(text or "").lower()
    return any(term in t for term in [
        "flood", "danger level", "above danger", "overflowing", "river rising dangerously",
        "submerged", "washed away", "severe inundation", "rising fast",
        "road will be cut off", "cut off", "bridge unstable", "at risk"
    ])


def _looks_like_tweet_text(message: str) -> bool:
    text = str(message or "").lower()
    has_hashtag = "#" in text
    has_claim = _looks_like_flood_claim(text) or _message_has_router_signal(
        text,
        ["bridge", "road", "traffic", "barrage", "embankment", "stranded", "nh16", "nh-16"],
        cutoff=0.9,
    )
    has_place = _message_has_router_signal(
        text,
        [
            "naraj", "jenapur", "anandpur", "akhuapada", "tikarpara",
            "kantamal", "salebhata", "purusottampur", "rengali",
            "cuttack", "jajpur", "bhadrak", "ganjam", "angul",
        ],
        cutoff=0.9,
    )
    return has_place and (has_hashtag or has_claim)


def _extract_query_terms(message: str) -> list[str]:
    stop = {
        "is", "the", "a", "an", "of", "or", "and", "to", "about", "should", "i", "it",
        "real", "ignore", "what", "which", "tweet", "tweets", "summary"
    }
    return [w for w in re.findall(r"[a-z0-9-]+", str(message or "").lower()) if len(w) > 2 and w not in stop]


def _tweet_limit_from_message(message: str) -> int:
    text = str(message or "").lower()
    if "2 tweets" in text or "two tweets" in text or "2 tweet" in text or "two tweet" in text:
        return 2
    if "5 tweets" in text or "five tweets" in text or "5 tweet" in text or "five tweet" in text:
        return 5
    return 5


def _message_has_router_signal(message: str, signals: list[str], cutoff: float = 0.82) -> bool:
    text = str(message or "").lower()
    if any(signal in text for signal in signals):
        return True
    tokens = re.findall(r"[a-z0-9-]+", text)
    for signal in signals:
        parts = re.findall(r"[a-z0-9-]+", signal.lower())
        if not parts:
            continue
        if len(parts) == 1:
            if difflib.get_close_matches(parts[0], tokens, n=1, cutoff=cutoff):
                return True
        else:
            for i in range(len(tokens) - len(parts) + 1):
                phrase = " ".join(tokens[i:i + len(parts)])
                if difflib.SequenceMatcher(None, phrase, " ".join(parts)).ratio() >= cutoff:
                    return True
    return False


def route_tweet_query(message: str, tweets: list[tuple]) -> tuple[str, list[tuple]]:
    msg = str(message or "").lower()

    single_signals = [
        "verify", "real", "fake", "ignore", "trust",
        "naraj", "jenapur", "anandpur", "akhuapada",
        "tikarpara", "kantamal", "salebhata",
        "purusottampur", "rengali", "cuttack",
        "jajpur", "bhadrak", "ganjam", "angul",
    ]

    summary_signals = [
        "summary", "tweets", "top", "all",
        "list", "provide", "show", "critical",
    ]

    if _message_has_router_signal(msg, single_signals):
        return "single_tweet", tweets[:1]
    if _message_has_router_signal(msg, summary_signals):
        return "tweet_summary", tweets[:5]

    if len(tweets) == 1:
        return "single_tweet", tweets[:1]
    return "tweet_summary", tweets[:5]


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
        for intent, terms in INTENT_RULES.items():
            score = sum(1 for term in terms if _message_has_router_signal(text, [term]))
            if score:
                scores[intent] = score
    if not scores:
        return "summary"
    return max(scores.items(), key=lambda item: item[1])[0]


def _message_requests_gauge_weather(message: str) -> bool:
    text = str(message or "").lower()
    has_gauge = (
        bool(re.search(r"\bgauge\b|\bguage\b|\bwse\b|\blevel\b", text))
        or _message_has_router_signal(text, ["gauge", "guage", "wse", "level"], cutoff=0.9)
    )
    has_weather = _message_has_router_signal(text, ["weather", "rain", "wind", "imd", "climate", "condition"])
    asks_full_summary = _message_has_router_signal(
        text,
        ["summary", "overview", "situation", "social", "signals", "full report", "situation report"],
    )
    return has_gauge and has_weather and not asks_full_summary


def _message_requests_full_situation(message: str) -> bool:
    text = str(message or "").lower()
    asks_summary = _message_has_router_signal(
        text,
        ["summary", "overview", "situation", "full report", "situation report"],
    )
    asks_gauge = _message_has_router_signal(text, ["gauge", "guage", "wse", "water", "level"])
    asks_weather = _message_has_router_signal(text, ["weather", "rain", "wind", "imd", "climate", "condition"])
    asks_social = _message_has_router_signal(text, ["social", "signal", "signals", "tweet", "tweets", "whatsapp"])
    return asks_summary and asks_gauge and asks_weather and asks_social


async def _fetch_station_payload() -> List[Dict]:
    now = datetime.now(timezone.utc)
    expires_at = _station_context_cache.get("expires_at")
    if expires_at and expires_at > now and _station_context_cache.get("raw") is not None:
        return _station_context_cache["raw"]
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            r = await client.get(f"{VPS_DATA_API}/data/stations")
            stations = r.json() if r.status_code == 200 else []
    except Exception as exc:
        logging.warning("STATION FETCH ERROR: %s — using cached/local fallback", exc)
        cached = _station_context_cache.get("raw")
        if cached:
            stations = cached
        elif PULSE_SNAPSHOT_PATH.exists():
            try:
                payload = json.loads(PULSE_SNAPSHOT_PATH.read_text(encoding="utf-8"))
                stations = payload.get("stations") if isinstance(payload, dict) else []
            except Exception:
                stations = []
        else:
            stations = []
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


async def _fetch_feeds_payload() -> Dict:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(VPS_FEEDS)
            if r.status_code != 200:
                logging.warning("FEEDS FETCH NON-200: %s", r.status_code)
                return {}
            payload = r.json()
            return payload if isinstance(payload, dict) else {}
    except Exception as exc:
        logging.exception("FEEDS FETCH ERROR: %s", exc)
        return {}


async def _tool_live_gauges() -> str:
    stations = await _fetch_station_payload()
    live_bits = []
    stale_count = 0
    for s in stations if isinstance(stations, list) else []:
        try:
            age_hours = float(s.get("data_age_hours")) if s.get("data_age_hours") is not None else 999
        except Exception:
            age_hours = 999
        if age_hours >= 48:
            stale_count += 1
            continue
        name = s.get("name", "")
        code = STATION_CODES.get(name, name[:3].upper())
        wse = s.get("latest_wse")
        status = s.get("alert_status", "NORMAL")
        if wse is not None:
            live_bits.append(f"{code} {float(wse):.2f}m {status}")
    if not live_bits:
        return "Gauges: unavailable."
    return f"Gauges: {len(live_bits)} live stations; {stale_count} stale excluded. " + " | ".join(live_bits)


async def _tool_imd_weather() -> str:
    feeds = await _fetch_feeds_payload()
    imd = feeds.get("imd", {}).get("stations", []) if isinstance(feeds, dict) else []
    if not isinstance(imd, list) or not imd:
        return "Weather: unavailable."
    notable = []
    clear_count = 0
    for row in imd[:12]:
        station = row.get("name") or row.get("district") or "Unknown"
        rain = row.get("rain") or row.get("rain_intensity") or "None"
        wind = row.get("wind") or row.get("wind_speed") or "None"
        label = _weather_icon_label(rain, wind)
        if label == "☀️ CLEAR":
            clear_count += 1
        else:
            notable.append(f"{station} {label} {rain} | {wind}")
    if notable:
        return "Weather: " + " | ".join(notable[:5])
    return f"Weather: all {len(imd[:12])} IMD-monitored stations CLEAR; no ALERT or DANGER conditions."


async def _tool_social_signals(limit: int = 3) -> str:
    try:
        rows = await _supabase_rest_get_async("social_signals", {
            "select": "district,summary,text,severity,platform,source",
            "order": "severity.desc.nullslast,timestamp.desc.nullslast",
        }, limit=limit)
        if rows:
            parts = []
            for r in rows:
                parts.append(
                    f"{r.get('district') or 'Unknown'} / "
                    f"{r.get('summary') or r.get('text') or 'No summary'} / "
                    f"sev {int(r.get('severity') or 0)} / "
                    f"{r.get('platform') or r.get('source') or 'social'}"
                )
            return "Social: " + " | ".join(parts)
        else:
            rows = []
    except Exception:
        pass

    if not rows:
        return "Social: none."


async def _tool_whatsapp_reports(limit: int = 3) -> str:
    try:
        rows = await _supabase_rest_get_async("social_signals", {
            "select": "district,summary,severity,sender",
            "source": "eq.whatsapp",
            "order": "severity.desc.nullslast,timestamp.desc.nullslast",
        }, limit=limit)
        if rows:
            parts = []
            for r in rows:
                parts.append(
                    f"{r.get('district') or 'Unknown'} / "
                    f"{r.get('summary') or 'No summary'} / "
                    f"sev {int(r.get('severity') or 0)} / "
                    f"{r.get('sender') or 'unknown sender'}"
                )
            return "WhatsApp: " + " | ".join(parts)
        else:
            rows = []
    except Exception as exc:
        rows = []
    if not rows:
        return "WhatsApp: none."


async def _tool_sos_status() -> str:
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
            boats = sos_data.get("boats", [])[:3]
            boat_bits = [
                f"{b.get('call_sign')} {b.get('distance_km')}km {b.get('route_risk') or 'Moderate'}"
                for b in boats
            ]
            return (
                f"SOS: active at {sos_data.get('station') or 'unknown station'}; "
                f"boats {' | '.join(boat_bits)}; fleet safe {counts['safe']} active {counts['active']} enroute {counts['enroute']}"
            )
        return f"SOS: none active; fleet safe {counts['safe']} active {counts['active']} enroute {counts['enroute']}"
    except Exception as exc:
        logging.info("SOS TOOL ERROR: %s", exc)
        return "SOS: unavailable."


async def _tool_news_alerts(limit: int = 3) -> str:
    feeds = await _fetch_feeds_payload()
    sachet_alerts = feeds.get("sachet", {}).get("alerts", []) if isinstance(feeds, dict) else []
    alerts = sorted(
        [a for a in sachet_alerts if isinstance(a, dict)],
        key=lambda a: a.get("published_at") or "",
        reverse=True,
    )[:limit]
    if not alerts:
        return "News: none."
    return "News: " + " | ".join(
        f"{a.get('location_match') or a.get('district') or 'Odisha'} / {a.get('summary') or a.get('title') or 'Untitled alert'} / {a.get('published_at') or 'unknown time'}"
        for a in alerts
    )


def _fallback_chat_tools(message: str, intent: str) -> list[str]:
    text = str(message or "").lower()
    tools: list[str] = []
    if intent == "gauge":
        tools.append("gauges")
    elif intent == "weather":
        tools.append("weather")
    elif intent == "news":
        tools.append("news")
    elif intent == "whatsapp":
        tools.append("whatsapp")
    elif intent == "sos":
        tools.extend(["sos", "gauges"])
    elif intent == "summary":
        tools.extend(["gauges", "weather", "social"])
    if _message_has_router_signal(text, ["social", "signal", "signals"]):
        tools.append("social")
    if _message_has_router_signal(text, ["whatsapp", "field team"]):
        tools.append("whatsapp")
    if _message_has_router_signal(text, ["sachet", "news", "alert"]):
        tools.append("news")
    if _message_has_router_signal(text, ["boat", "rescue", "sos"]):
        tools.append("sos")
    if _message_has_router_signal(text, ["gauge", "guage", "wse", "water", "level"]):
        tools.append("gauges")
    if _message_has_router_signal(text, ["weather", "rain", "wind", "imd", "climate"]):
        tools.append("weather")
    deduped = []
    for name in tools:
        if name in CHAT_TOOL_NAMES and name not in deduped:
            deduped.append(name)
    return deduped or ["gauges"]


async def _plan_chat_tools(message: str, intent: str) -> list[str]:
    fallback = _fallback_chat_tools(message, intent)
    groq_key = os.getenv("GROQ_API_KEY") or os.getenv("GROQ_API") or ""
    auth_header = f"Bearer {groq_key}".strip()
    if auth_header in {"", "Bearer"}:
        return fallback
    prompt = (
        "Select the minimum internal data tools needed for this question. "
        "Available tools: gauges, weather, social, whatsapp, sos, news. "
        "Return JSON only in the form {\"tools\":[...]} with tool names from that list only."
    )
    payload = {
        "model": "llama-3.3-70b-versatile",
        "messages": [
            {"role": "system", "content": prompt},
            {"role": "user", "content": f"Intent hint: {intent}\nQuestion: {message}"},
        ],
        "max_tokens": 80,
    }
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": auth_header},
                json=payload,
            )
            if r.status_code >= 400:
                return fallback
            data = r.json()
            content = (
                data.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
                .strip()
            )
            match = re.search(r"\{.*\}", content, re.S)
            planned = json.loads(match.group(0) if match else content)
            tools = [t for t in planned.get("tools", []) if t in CHAT_TOOL_NAMES]
            deduped = []
            for name in tools:
                if name not in deduped:
                    deduped.append(name)
            return deduped or fallback
    except Exception as exc:
        logging.info("CHAT TOOL PLAN ERROR: %s", exc)
        return fallback


async def _build_tool_context(message: str, intent: str) -> str:
    tools = await _plan_chat_tools(message, intent)
    logging.info("CHAT TOOLS: %s", tools)
    parts = [f"Tools used: {', '.join(tools)}."]
    for tool in tools:
        if tool == "gauges":
            parts.append(await _tool_live_gauges())
        elif tool == "weather":
            parts.append(await _tool_imd_weather())
        elif tool == "social":
            parts.append(await _tool_social_signals(3 if intent == "summary" else 5))
        elif tool == "whatsapp":
            parts.append(await _tool_whatsapp_reports())
        elif tool == "sos":
            parts.append(await _tool_sos_status())
        elif tool == "news":
            parts.append(await _tool_news_alerts())
    return _clip_words(" ".join(parts), 550)


async def _weather_reply(include_gauge: bool = False) -> str:
    feeds = await _fetch_feeds_payload()
    imd = feeds.get("imd", {}).get("stations", []) if isinstance(feeds, dict) else []
    if not isinstance(imd, list) or not imd:
        return "IMD weather feed unavailable right now."

    notable = []
    for row in imd[:12]:
        station = row.get("name") or row.get("district") or "Unknown"
        rain = row.get("rain") or row.get("rain_intensity") or "None"
        wind = row.get("wind") or row.get("wind_speed") or "None"
        label = _weather_icon_label(rain, wind)
        if label != "☀️ CLEAR":
            notable.append(f"{station} {label} {rain} | {wind}")

    if notable:
        weather_summary = f"Weather: {' | '.join(notable[:5])}."
    else:
        weather_summary = "All IMD-monitored stations show CLEAR weather with no ALERT or DANGER conditions."

    if not include_gauge:
        return weather_summary

    stations = await _fetch_station_payload()
    gauge_bits = []
    for s in stations if isinstance(stations, list) else []:
        try:
            age_hours = float(s.get("data_age_hours")) if s.get("data_age_hours") is not None else 999
        except Exception:
            age_hours = 999
        if age_hours >= 48:
            continue
        name = s.get("name", "")
        code = STATION_CODES.get(name, name[:3].upper())
        wse = s.get("latest_wse")
        status = s.get("alert_status", "NORMAL")
        if wse is None:
            continue
        gauge_bits.append(f"{code} {float(wse):.2f}m {status}")

    if not gauge_bits:
        return f"Gauge data unavailable. {weather_summary}"
    return f"Live gauges: {', '.join(gauge_bits)}. {weather_summary}"


async def _situation_reply() -> str:
    stations = await _fetch_station_payload()
    live_bits = []
    stale_count = 0
    for s in stations if isinstance(stations, list) else []:
        try:
            age_hours = float(s.get("data_age_hours")) if s.get("data_age_hours") is not None else 999
        except Exception:
            age_hours = 999
        if age_hours >= 48:
            stale_count += 1
            continue
        name = s.get("name", "")
        code = STATION_CODES.get(name, name[:3].upper())
        wse = s.get("latest_wse")
        status = s.get("alert_status", "NORMAL")
        if wse is not None:
            live_bits.append(f"{code} {float(wse):.2f}m {status}")

    gauge_summary = (
        f"Live gauges: {', '.join(live_bits)}. {stale_count} stations excluded as stale (>48h)."
        if live_bits else
        "Gauge data unavailable."
    )

    weather_summary = await _weather_reply(include_gauge=False)

    social_summary = "No social signals available."
    try:
        rows = await _supabase_rest_get_async("social_signals", {
            "select": "district,summary,text,severity,platform,source",
            "order": "severity.desc.nullslast,timestamp.desc.nullslast",
        }, limit=3)
        if rows:
            social_summary = "Social signals: " + " | ".join(
                f"{r.get('district') or 'Unknown'} / "
                f"{r.get('summary') or r.get('text') or 'No summary'} / "
                f"sev {int(r.get('severity') or 0)} / "
                f"{r.get('platform') or r.get('source') or 'social'}"
                for r in rows
            ) + "."
    except Exception:
        pass

    return f"{gauge_summary} {weather_summary} {social_summary}"


async def _build_chat_context(intent: str) -> str:
    parts = []
    gauge_context = ""
    weather_context = ""
    tweet_context = ""
    stations = []
    imd = []

    if intent in {"gauge", "summary", "radar", "tweet"}:
        stations = await _fetch_station_payload()
        gauge_ctx = _station_context_cache.get("gauge") or ""
        stale_count = int(_station_context_cache.get("stale_count") or 0)
        stale_note = (
            f" Note: {stale_count} stations excluded (stale >48h)"
            if stale_count else ""
        )
        if intent == "summary":
            live = sum(1 for s in stations if (s.get("data_age_hours") or 0) < 48)
            gauge_context = _clip_words(f"Gauges: {gauge_ctx}. Live stations {live}/{len(stations) or 9}.{stale_note}", 90)
            parts.append(gauge_context)
        elif intent == "radar":
            radar_context = {
                "radar_url": "https://mausam.imd.gov.in/Radar/caz_pdp.gif",
                "stations": _clip_words(f"Gauges: {gauge_ctx}.{stale_note}", 60),
            }
            parts.append(json.dumps(radar_context, ensure_ascii=False))
        else:
            gauge_context = _clip_words(f"Gauges: {gauge_ctx}.{stale_note}", 60)
            if intent != "tweet":
                parts.append(gauge_context)

    if intent in {"weather", "summary", "tweet"}:
        try:
            feeds = await _fetch_feeds_payload()
            imd = feeds.get("imd", {}).get("stations", []) if isinstance(feeds, dict) else []
            items = []
            for s in imd[:12]:
                station = s.get("name") or s.get("district") or "Unknown"
                rain = s.get("rain") or s.get("rain_intensity") or "none"
                wind = s.get("wind") or s.get("wind_speed") or "none"
                if intent == "weather":
                    items.append(f"{station} {_weather_icon_label(rain, wind)} {rain} | {wind}")
                elif intent == "tweet":
                    district = s.get("district") or s.get("name") or "Unknown"
                    items.append(f"{district} {_weather_icon_label(rain, wind)} {rain} | {wind}")
                else:
                    district = s.get("district") or s.get("name") or "Unknown"
                    wms = s.get("wms_color")
                    items.append(f"{district}:wms{wms}")
            if items:
                weather_context = _clip_words(f"Weather: {' | '.join(items)}", 150 if intent == "weather" else (120 if intent == "tweet" else 70))
            else:
                weather_context = "Weather: unavailable"
            if intent != "tweet":
                parts.append(weather_context)
        except Exception as exc:
            logging.exception("WEATHER CONTEXT BUILD ERROR: %s", exc)
            if intent == "weather":
                weather_context = "Weather: unavailable"
                parts.append(weather_context)

    if intent == "news":
        try:
            feeds = await _fetch_feeds_payload()
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
            if intent in {"tweet", "summary"}:
                tweet_limit = 3 if intent == "summary" else 5
                rows = await _supabase_rest_get_async("social_signals", {
                    "select": "district,summary,severity,reliability_score,verified,text,timestamp,station_proximity",
                    "platform": "eq.twitter",
                    "order": "severity.desc.nullslast,reliability_score.desc.nullslast,timestamp.desc.nullslast",
                }, limit=tweet_limit)
                if rows:
                    tweet_parts = []
                    station_lookup = {}
                    district_lookup = {}
                    for s in stations if isinstance(stations, list) else []:
                        name = str(s.get("name") or "").strip()
                        district = str(s.get("district") or "").strip()
                        if name:
                            station_lookup[name.lower()] = s
                            code = STATION_CODES.get(name)
                            if code:
                                station_lookup[code.lower()] = s
                        if district and district.lower() not in district_lookup:
                            district_lookup[district.lower()] = s
                    imd_lookup = {}
                    for row in imd if isinstance(imd, list) else []:
                        district = str(row.get("district") or row.get("district_proxy") or row.get("name") or "").strip()
                        if district and district.lower() not in imd_lookup:
                            imd_lookup[district.lower()] = row
                    if intent == "tweet":
                        if gauge_context:
                            tweet_parts.append(gauge_context)
                        if weather_context:
                            tweet_parts.append(weather_context)
                        check_lines = []
                        for r in rows:
                            district = str(r.get("district") or "Unknown").strip()
                            proximity = str(r.get("station_proximity") or district).strip()
                            st = station_lookup.get(proximity.lower()) or district_lookup.get(district.lower())
                            code = STATION_CODES.get(st.get("name")) if st else (proximity[:3].upper() if proximity else "UNK")
                            latest_wse = st.get("latest_wse") if st else None
                            warning_level = st.get("warning_level") if st else None
                            below_warning = (
                                latest_wse is not None and warning_level is not None and float(latest_wse) < float(warning_level)
                            ) if st else None
                            imd_row = imd_lookup.get(district.lower()) or imd_lookup.get(str(st.get("district") if st else "").lower())
                            wms_color = imd_row.get("wms_color") if isinstance(imd_row, dict) else None
                            weather_clear = (wms_color is not None and int(wms_color) <= 1) if wms_color is not None else None
                            check_lines.append(_clip_words(
                                f"{district}→{code}: WSE={f'{float(latest_wse):.2f}' if latest_wse is not None else 'NA'}m, "
                                f"warning={f'{float(warning_level):.2f}' if warning_level is not None else 'NA'}m, "
                                f"below_warning={below_warning}, IMD={wms_color if wms_color is not None else 'NA'}, "
                                f"clear={weather_clear}",
                                20
                            ))
                        if check_lines:
                            tweet_parts.append("Checks: " + " | ".join(check_lines))
                    tweet_parts.append(
                        "Tweets: " + " | ".join(
                            f"{r.get('district') or 'Unknown'} / {r.get('summary') or r.get('text') or 'No summary'} / sev {r.get('severity') if r.get('severity') is not None else 0} / rel {r.get('reliability_score') if r.get('reliability_score') is not None else 0}"
                            for r in rows
                        )
                    )
                    tweet_context = _clip_words(
                        " ".join(tweet_parts),
                        300 if intent == "tweet" else 120
                    )
                    logging.info(f"TWEET CONTEXT: {tweet_context}")
                    logging.info(f"GAUGE CONTEXT: {gauge_context}")
                    logging.info(f"WEATHER CONTEXT: {weather_context}")
                    parts.append(tweet_context)
                else:
                    logging.info("TWEET CONTEXT: NONE")
                    logging.info(f"GAUGE CONTEXT: {gauge_context}")
                    logging.info(f"WEATHER CONTEXT: {weather_context}")
                    if intent == "tweet":
                        parts.append("Tweets: No Twitter signals available in social_signals.")
            if intent == "whatsapp":
                rows = await _supabase_rest_get_async("social_signals", {
                    "select": "district,summary,severity,sender",
                    "source": "eq.whatsapp",
                    "order": "severity.desc.nullslast,timestamp.desc.nullslast",
                }, limit=3)
                if rows:
                    parts.append(_clip_words(
                        "WhatsApp: " + " | ".join(
                            f"{r.get('district') or 'Unknown'} / {r.get('summary') or 'No summary'} / sev {r.get('severity') if r.get('severity') is not None else 0} / {r.get('sender') or 'unknown sender'}"
                            for r in rows
                        ),
                        60 if intent == "whatsapp" else 90
                    ))
        except Exception as exc:
            logging.info(f"TWEET CONTEXT ERROR: {exc}")
            if intent == "tweet":
                parts.append("Tweets: No Twitter signals available in social_signals.")

    if intent == "sos":
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
            " VERIFIED if: severity >= 4 AND reliability >= 4 "
            "AND (WSE >= warning_level "
            "OR IMD wms_color >= 2 "
            "OR weather NOT clear). "
            " MONITOR if: severity >= 4 AND reliability >= 4 "
            "AND WSE < warning_level "
            "AND IMD wms_color <= 1 "
            "AND weather clear. "
            " LIKELY FAKE if: tweet claims river is at FLOOD/DANGER level "
            "BUT WSE < warning_level for that station. "
            " Use only these labels: LIKELY FAKE, MONITOR, VERIFIED. "
            " Respond in exactly 3 sentences: "
            "sentence 1 = classification, "
            "sentence 2 = gauge/weather cross-check, "
            "sentence 3 = why severity/reliability alone is insufficient or sufficient. "
            "For each tweet on a new line: "
            "[VERIFIED] or [LIKELY FAKE] or [MONITOR] — {district} — {summary}"
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
    if intent == "gauge":
        system_prompt += (
            " Summarize only the live gauge stations shown in context. "
            "Explicitly state the live station count and the stale station count excluded. "
            "If all live gauges are NORMAL, say that directly."
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
            async with httpx.AsyncClient(timeout=6) as client:
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
        max_tokens = 400 if intent == "tweet" else 150
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
                "max_tokens": max_tokens,
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


async def _tweet_reply(message: str) -> str:
    stations = await _fetch_station_payload()
    station_by_name = {str(s.get("name") or "").lower(): s for s in stations if isinstance(stations, list)}
    district_station = {
        district: station_by_name.get(name.lower())
        for district, name in DISTRICT_TO_STATION.items()
        if station_by_name.get(name.lower())
    }

    imd_rows = []
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(VPS_FEEDS)
            feeds = r.json()
        imd_rows = feeds.get("imd", {}).get("stations", []) if isinstance(feeds, dict) else []
    except Exception:
        imd_rows = []
    imd_by_district = {}
    for row in imd_rows if isinstance(imd_rows, list) else []:
        key = str(row.get("district") or row.get("district_proxy") or row.get("name") or "").strip().lower()
        if key and key not in imd_by_district:
            imd_by_district[key] = row

    lower_message = message.lower()
    direct_verify = lower_message.startswith("verify:") or lower_message.startswith("is this tweet") or lower_message.startswith("is the") or "#odishaflood" in lower_message

    rows = []
    route_mode = "tweet_summary"
    if direct_verify:
        route_mode = "single_tweet"
        raw_text = re.sub(r"^\s*verify:\s*", "", message, flags=re.I).strip() or message.strip()
        district = "Unknown"
        station_proximity = None
        for key, station_name in DISTRICT_TO_STATION.items():
            if key in raw_text.lower():
                district = key.title()
                station_proximity = station_name
                break
        if not station_proximity:
            for station_name in STATION_CODES:
                if station_name.lower() in raw_text.lower():
                    station_proximity = station_name
                    st = station_by_name.get(station_name.lower())
                    district = (st.get("district") if st else district) or district
                    break
        sev = 4 if _looks_like_flood_claim(raw_text) else 3
        rel = 3
        rows = [(district, raw_text[:160], sev, rel, raw_text, None, station_proximity)]
    else:
        try:
            tweet_limit = _tweet_limit_from_message(message)
            raw_rows = await _supabase_rest_get_async("social_signals", {
                "select": "district,summary,severity,reliability_score,text,timestamp,station_proximity",
                "platform": "eq.twitter",
                "order": "severity.desc.nullslast,reliability_score.desc.nullslast,timestamp.desc.nullslast",
            }, limit=tweet_limit)
            rows = [
                (
                    r.get("district"), r.get("summary"), r.get("severity"),
                    r.get("reliability_score"), r.get("text"), r.get("timestamp"),
                    r.get("station_proximity")
                )
                for r in raw_rows
            ] if raw_rows else []
        except Exception:
            return "No Twitter signals available — data source temporarily unavailable."

        if not rows:
            return "No Twitter signals available in social_signals."

        terms = _extract_query_terms(message)
        if terms:
            filtered = []
            for r in rows:
                hay = " ".join(str(x or "") for x in [r[0], r[1], r[4], r[6]]).lower()
                if any(term in hay for term in terms):
                    filtered.append(r)
            if filtered:
                rows = filtered
        route_mode, rows = route_tweet_query(message, rows)

    lines = []
    for district, summary, severity, reliability, text, timestamp, station_proximity in rows:
        district = district or "Unknown"
        summary = summary or text or "No summary"
        severity = int(severity or 0)
        reliability = int(reliability or 0)
        proximity = str(station_proximity or "").strip().lower()
        st = station_by_name.get(proximity) or district_station.get(str(district).lower())
        station_name = st.get("name") if st else (station_proximity or district)
        station_code = STATION_CODES.get(station_name, (str(station_name)[:3].upper() if station_name else "UNK"))
        wse = st.get("latest_wse") if st else None
        warning = st.get("warning_level") if st else None
        below_warning = bool(wse is not None and warning is not None and float(wse) < float(warning))
        status = st.get("alert_status", "UNKNOWN") if st else "UNKNOWN"
        imd_row = imd_by_district.get(str(district).lower()) or imd_by_district.get(str(st.get("district") if st else "").lower())
        wms_color = int(imd_row.get("wms_color") or 0) if isinstance(imd_row, dict) and imd_row.get("wms_color") is not None else 0
        weather_clear = wms_color <= 1
        live_count = sum(1 for s in stations if (s.get("data_age_hours") or 999) < 48) if isinstance(stations, list) else 0

        label = "MONITOR"
        if _looks_like_flood_claim(summary) and below_warning:
            label = "LIKELY FAKE"
        elif severity >= 4 and reliability >= 4 and ((wse is not None and warning is not None and float(wse) >= float(warning)) or wms_color >= 2 or not weather_clear):
            label = "VERIFIED"
        elif severity >= 4 and reliability >= 4 and below_warning and weather_clear:
            label = "MONITOR"
        elif direct_verify and _looks_like_flood_claim(summary) and below_warning and weather_clear:
            label = "LIKELY FAKE"

        wse_text = f"{float(wse):.2f}m" if wse is not None else "NA"
        if route_mode == "single_tweet":
            station_ref = f"{station_code} ({station_name})" if station_name else station_code
            weather_text = "Weather is CLEAR." if weather_clear else (f"IMD weather severity is {wms_color}." if wms_color else "Weather data unavailable.")
            return (
                f"{station_ref} gauge shows {wse_text}, which is {status}. "
                f"{weather_text} "
                f"No indication of rapid rise; all {live_count} live stations show normal status. "
                f"Verify traffic or infrastructure details from other sources, as gauge data doesn't support the claim."
            )
        sentence1 = f"[{label}] — {district} — {summary}."
        sentence2 = f"Gauge at {station_name} ({station_code}) is {wse_text} {status} and weather is {'CLEAR' if weather_clear else f'IMD {wms_color}' }."
        if label == "VERIFIED":
            sentence3 = "Severity and reliability are supported by gauge or weather conditions."
        elif label == "LIKELY FAKE":
            sentence3 = "The claim conflicts with gauge conditions because water level is below warning threshold."
        else:
            sentence3 = "Severity and reliability alone are insufficient as water levels are below warning levels and weather is clear."
        lines.append("\n".join([sentence1, sentence2, sentence3]))

    return "\n\n".join(lines)


# ──────────────────────────────────────────────
#  Routes
# ──────────────────────────────────────────────

@app.get("/api/stations")
async def api_stations():
    """Station data for dashboard, served from the local WSE snapshot only."""
    if not PULSE_SNAPSHOT_PATH.exists():
        return JSONResponse({"error": "snapshot unavailable"}, status_code=503)
    try:
        payload = json.loads(PULSE_SNAPSHOT_PATH.read_text(encoding="utf-8"))
    except Exception:
        return JSONResponse({"error": "snapshot unavailable"}, status_code=503)

    stations = payload.get("stations") if isinstance(payload, dict) else payload if isinstance(payload, list) else None
    if not isinstance(stations, list):
        return JSONResponse({"error": "snapshot unavailable"}, status_code=503)

    out = []
    for row in stations:
        item = dict(row or {})
        if item.get("latest_wse") is None:
            item["latest_wse"] = item.get("wse")
        if item.get("latest_timestamp") is None:
            item["latest_timestamp"] = item.get("last_updated")
        if item.get("alert_status") is None:
            item["alert_status"] = item.get("status") or "NO_DATA"
        age_min = item.get("data_age_minutes")
        if item.get("data_age_hours") is None:
            try:
                item["data_age_hours"] = round(float(age_min) / 60, 1) if age_min is not None else 999
            except Exception:
                item["data_age_hours"] = 999
        if item.get("wse_source") is None:
            item["wse_source"] = "stale" if item.get("stale") else "live"
        item.setdefault("forecast_8h", None)
        item.setdefault("forecast_24h", None)
        item.setdefault("forecast", [])
        item.setdefault("confidence_pct", None)
        if item.get("data_age_hours", 999) > 168:
            item["label"] = "No data available"
        else:
            item.setdefault("label", None)
        out.append(item)

    return out


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
    """WSE history for dashboard from local CSV snapshots only."""
    station_name = "Purusottampur" if station == "Purushottampur" else station
    cache_key = (station_name, 15)
    now = datetime.now(timezone.utc)
    cached = _chart_cache.get(cache_key)
    if cached and cached.get("expires_at") and cached["expires_at"] > now:
        data = dict(cached["data"])
    else:
        csv_name = station_name.lower().replace(" ", "_").replace("/", "-")
        csv_path = Path("/root/Sahayak/pipeline/data") / f"{csv_name}_wse.csv"

        if not csv_path.exists():
            return JSONResponse({"error": "no history available"}, status_code=404)

        try:
            df = pd.read_csv(csv_path, parse_dates=["timestamp"])
            df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
            df["value"] = pd.to_numeric(df["value"], errors="coerce")
            df = df.dropna(subset=["timestamp", "value"]).sort_values("timestamp")
        except Exception:
            return JSONResponse({"error": "no history available"}, status_code=500)

        if df.empty:
            return JSONResponse({"error": "no history available"}, status_code=404)

        latest_ts = df["timestamp"].max()
        cutoff = latest_ts - timedelta(days=15)
        df = df[df["timestamp"] >= cutoff].copy()

        thresholds = {"warning": None, "danger": None, "hfl": None}
        try:
            if PULSE_SNAPSHOT_PATH.exists():
                payload = json.loads(PULSE_SNAPSHOT_PATH.read_text(encoding="utf-8"))
                stations = payload.get("stations") if isinstance(payload, dict) else []
                for item in stations if isinstance(stations, list) else []:
                    if item.get("name") == station_name:
                        thresholds = {
                            "warning": item.get("warning_level"),
                            "danger": item.get("danger_level"),
                            "hfl": item.get("hfl"),
                        }
                        break
        except Exception:
            pass

        data = {
            "station": station_name,
            "timestamps": [ts.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") for ts in df["timestamp"].tolist()],
            "values": [float(v) for v in df["value"].tolist()],
            "history": [
                {
                    "timestamp": ts.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "wse": float(v),
                }
                for ts, v in zip(df["timestamp"].tolist(), df["value"].tolist())
            ],
            "thresholds": thresholds,
            "latest_timestamp": latest_ts.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        _chart_cache[cache_key] = {
            "expires_at": now + CHART_CACHE_TTL,
            "data": dict(data),
        }

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
    """Social signals from Supabase REST — max date only (latest day)."""
    signals = []

    try:
        rows = _supabase_rest_get("social_signals", {
            "select": "source,platform,district,raw_text,text,location,coordinates,severity,event_type,station_proximity,summary,reliability_score,credibility_flags,verified,timestamp,sender",
            "order": "timestamp.desc.nullslast",
        }, limit=200)
        if rows:
            max_ts = None
            for r in rows:
                ts = r.get("timestamp")
                if ts:
                    try:
                        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                        if max_ts is None or dt > max_ts:
                            max_ts = dt
                    except Exception:
                        pass
            if max_ts:
                max_day = max_ts.date()
                for r in rows:
                    ts = r.get("timestamp")
                    if not ts:
                        continue
                    try:
                        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                        if dt.date() == max_day:
                            signals.append({
                                "source": r.get("source"), "platform": r.get("platform"), "district": r.get("district"),
                                "text": r.get("raw_text") or r.get("text"), "location": r.get("location"),
                                "coordinates": r.get("coordinates"), "severity": r.get("severity"),
                                "event_type": r.get("event_type"), "station_proximity": r.get("station_proximity"),
                                "summary": r.get("summary"), "reliability_score": r.get("reliability_score"),
                                "credibility_flags": r.get("credibility_flags"), "verified": r.get("verified"),
                                "timestamp": str(ts) if ts else None,
                                "sender": r.get("sender"),
                            })
                    except Exception:
                        pass
        if signals:
            signals.sort(key=lambda s: (s.get("verified", False), s.get("severity", 0)), reverse=True)
            return signals
    except Exception:
        pass

    return []


@app.get("/api/sos/{station}")
async def api_sos(station: str):
    """SOS triage: WSE, forecast, HFL countdown, route risk, nearest boats."""
    if station == "active":
        return await api_sos_active()

    try:
        from triage_logic import triage, format_triage, haversine
    except ImportError:
        return JSONResponse({"error": "Triage module not available"}, status_code=500)

    try:
        snapshot = json.loads(PULSE_SNAPSHOT_PATH.read_text(encoding="utf-8")) if PULSE_SNAPSHOT_PATH.exists() else {}
    except Exception:
        snapshot = {}
    stations = snapshot.get("stations") if isinstance(snapshot, dict) else []
    station_name = "Purusottampur" if station == "Purushottampur" else station
    st = next((s for s in stations if s.get("name") == station_name), None)
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
            csv_name = station_name.lower().replace(" ", "_").replace("/", "-")
            csv_path = Path("/root/Sahayak/pipeline/data") / f"{csv_name}_wse.csv"
            chart_df = pd.read_csv(csv_path, parse_dates=["timestamp"])
            chart_df["timestamp"] = pd.to_datetime(chart_df["timestamp"], utc=True, errors="coerce")
            chart_df["value"] = pd.to_numeric(chart_df["value"], errors="coerce")
            chart_df = chart_df.dropna(subset=["timestamp", "value"]).sort_values("timestamp")
            vals = chart_df["value"].tolist()
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
        conn = psycopg2.connect(os.getenv("URI", ""), connect_timeout=3)
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
        conn = psycopg2.connect(os.getenv("URI", ""), connect_timeout=3)
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
                conn = psycopg2.connect(os.getenv("URI", ""), connect_timeout=3)
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

    lower_message = message.lower()
    if lower_message.startswith("verify:") or _looks_like_tweet_text(message):
        reply = await _tweet_reply(message)
        return {"reply": reply}

    if _message_has_router_signal(lower_message, ["tweet", "tweets", "summary"]):
        reply = await _tweet_reply(message)
        return {"reply": reply}

    if _message_requests_full_situation(message):
        return {"reply": await _situation_reply()}

    if _message_requests_gauge_weather(message):
        return {"reply": await _weather_reply(include_gauge=True)}

    intent = _detect_intent(message)
    logging.info(f"INTENT DETECTED: {intent}")
    if intent == "tweet":
        reply = await _tweet_reply(message)
        return {"reply": reply}
    if intent == "weather":
        return {"reply": await _weather_reply(include_gauge=False)}
    if intent == "radar":
        context = await _build_chat_context(intent)
    else:
        context = await _build_tool_context(message, intent)
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
    """Boat asset positions for Leaflet map markers. Served from local snapshot; DB fallback."""
    if BOATS_SNAPSHOT_PATH.exists():
        try:
            payload = json.loads(BOATS_SNAPSHOT_PATH.read_text(encoding="utf-8"))
            boats = payload.get("boats") if isinstance(payload, dict) else []
            if isinstance(boats, list) and boats:
                out = []
                for b in boats:
                    last_ping = b.get("last_ping")
                    if isinstance(last_ping, str) and last_ping:
                        try:
                            from datetime import datetime as _dt
                            last_ping = _dt.fromisoformat(last_ping.replace("Z", "+00:00"))
                        except Exception:
                            pass
                    out.append({
                        "call_sign": b.get("call_sign"),
                        "status": b.get("status"),
                        "lat": b.get("lat"),
                        "lon": b.get("lon"),
                        "last_ping": last_ping.isoformat().replace("+00:00", "Z") if hasattr(last_ping, "isoformat") else str(last_ping or ""),
                        "nearest_station": b.get("nearest_station"),
                    })
                return out
        except Exception:
            pass

    try:
        conn = psycopg2.connect(os.getenv("URI", ""), connect_timeout=3)
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
        return [
            {
                "call_sign": r.get("call_sign"),
                "status": r.get("status"),
                "lat": r.get("lat"),
                "lon": r.get("lon"),
                "last_ping": r.get("last_ping", ""),
                "nearest_station": r.get("nearest_station"),
            }
            for r in _read_boats_from_seed()
        ]

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


def _read_boats_from_seed() -> list[dict]:
    """Last-resort fallback: read boat_assets_rows.csv fixture."""
    csv_path = Path("/root/Sahayak/pipeline/fixtures/boat_assets_rows.csv")
    if not csv_path.exists():
        return []
    import csv as _csv
    try:
        with open(csv_path, newline="", encoding="utf-8") as f:
            reader = _csv.DictReader(f)
            boats = []
            for row in reader:
                boats.append({
                    "call_sign": row.get("call_sign", ""),
                    "status": row.get("status", "Safe"),
                    "lat": float(row["lat"]) if row.get("lat") else None,
                    "lon": float(row["lon"]) if row.get("lon") else None,
                    "last_ping": row.get("last_ping", ""),
                    "nearest_station": row.get("nearest_station", ""),
                })
            return boats
    except Exception:
        return []


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

    # Get nearest boats per station from local snapshot
    boat_map = {}
    try:
        if BOATS_SNAPSHOT_PATH.exists():
            boats_payload = json.loads(BOATS_SNAPSHOT_PATH.read_text(encoding="utf-8"))
            boats = boats_payload.get("boats") if isinstance(boats_payload, dict) else []
            for b in boats if isinstance(boats, list) else []:
                if b.get("nearest_station") and b.get("nearest_station") not in boat_map:
                    boat_map[b["nearest_station"]] = b.get("team_id")
        if not boat_map:
            conn = psycopg2.connect(os.getenv("URI", ""), connect_timeout=3)
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
VPS_FEEDS    = "http://127.0.0.1:8004/api/feeds"


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
        rows = _supabase_rest_get("sachet_rss_entries", {
            "select": "title,published_at,location_match",
            "order": "published_at.desc.nullslast",
        }, limit=200)
        current_titles = {str(a.get("title", "")).strip().lower() for a in current_alerts}
        today = datetime.now(timezone.utc).date()
        seen = set()
        for r in rows if isinstance(rows, list) else []:
            published_at = r.get("published_at")
            if not published_at:
                continue
            try:
                dt = datetime.fromisoformat(str(published_at).replace("Z", "+00:00"))
            except Exception:
                continue
            if dt.date() >= today:
                continue
            if dt.date() < today - timedelta(days=1):
                continue
            title = str(r.get("title") or "").strip().lower()
            if not title or title in current_titles or title in seen:
                continue
            if "forest fire" in title:
                continue
            seen.add(title)
            previous_day_alerts.append({
                "title": r.get("title"),
                "published_at": str(published_at),
                "location_match": r.get("location_match") or "",
                "out_of_zone": False,
            })
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
