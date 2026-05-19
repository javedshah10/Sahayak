"""
SahayakMap — SOS Triage Logic (Task 7)
=======================================
Nearest 3 boats + road risk + safe zone recommendation.
Integrated into telegram_bot.py for SOS response.

Usage:
    python triage_logic.py <lat> <lon>     # manual test
"""

import math
import csv as _csv
import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Dict, Optional

import psycopg2
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

DATABASE_URL = os.getenv("URI", "")

BOATS_SNAPSHOT_PATH = Path("/root/Sahayak/pipeline/snapshots/boats_latest.json")
BOATS_CSV_PATH = Path("/root/Sahayak/pipeline/fixtures/boat_assets_rows.csv")
_db_unavailable = False

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("SahayakMap.Triage")


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return distance in kilometres between two WGS84 coordinates."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return round(R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a)), 2)


def _load_boats_from_snapshot() -> list[dict]:
    """Load boats from local snapshot file. Falls back to CSV seed."""
    snapshot = None
    if BOATS_SNAPSHOT_PATH.exists():
        try:
            snapshot = json.loads(BOATS_SNAPSHOT_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass

    if isinstance(snapshot, dict) and snapshot.get("boats"):
        return snapshot["boats"]

    boats = []
    if BOATS_CSV_PATH.exists():
        try:
            with open(BOATS_CSV_PATH, newline="", encoding="utf-8") as f:
                reader = _csv.DictReader(f)
                for row in reader:
                    boats.append({
                        "call_sign": row.get("call_sign", ""),
                        "team_id": row.get("team_id", ""),
                        "lat": float(row["lat"]) if row.get("lat") else None,
                        "lon": float(row["lon"]) if row.get("lon") else None,
                        "status": row.get("status", "Safe"),
                        "nearest_station": row.get("nearest_station", ""),
                        "district": row.get("district", ""),
                        "last_ping": row.get("last_ping", ""),
                    })
        except Exception:
            pass
    return boats


def get_db():
    return psycopg2.connect(DATABASE_URL, connect_timeout=3)


def nearest_boats(lat: float, lon: float, limit: int = 5) -> List[Dict]:
    """Query boat_assets for Safe/Active boats with recent pings, sorted by distance.
    Falls back to local snapshot when DB is unavailable."""
    global _db_unavailable
    if not _db_unavailable and DATABASE_URL:
        try:
            conn = get_db()
            cur = conn.cursor()
            cur.execute("""
                SELECT team_id, call_sign, lat, lon, status, nearest_station, district, last_ping
                FROM boat_assets
                WHERE status IN ('Safe', 'Active', 'En Route')
                  AND last_ping > NOW() - INTERVAL '24 hours'
            """)
            boats = []
            for r in cur.fetchall():
                dist = haversine(lat, lon, r[2], r[3])
                boats.append({"team_id": r[0], "call_sign": r[1], "lat": r[2], "lon": r[3],
                               "status": r[4], "nearest_station": r[5], "district": r[6],
                               "last_ping": str(r[7])[:19], "distance_km": dist})
            cur.close()
            conn.close()
            if boats:
                _db_unavailable = False
                boats.sort(key=lambda b: b["distance_km"])
                return boats[:limit]
        except Exception as exc:
            log.warning("DB boat query failed: %s — using local snapshot", exc)
            _db_unavailable = True

    boats = []
    now = datetime.now(timezone.utc)
    for b in _load_boats_from_snapshot():
        b_lat = b.get("lat")
        b_lon = b.get("lon")
        if b_lat is None or b_lon is None:
            continue
        status = str(b.get("status") or "").strip()
        if status not in ("Safe", "Active", "En Route"):
            continue
        dist = haversine(lat, lon, b_lat, b_lon)
        boats.append({
            "team_id": b.get("team_id", ""),
            "call_sign": b.get("call_sign", ""),
            "lat": b_lat,
            "lon": b_lon,
            "status": status,
            "nearest_station": b.get("nearest_station", ""),
            "district": b.get("district", ""),
            "last_ping": str(b.get("last_ping", ""))[:19],
            "distance_km": dist,
        })

    if not boats:
        return []

    boats.sort(key=lambda b: b["distance_km"])
    return boats[:limit]


def road_risk_check(boat: Dict) -> Optional[Dict]:
    """Check road_risks table for elevated risk on boat's nearest station."""
    if _db_unavailable:
        return None
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            SELECT id, road_name, risk_level, station_proximity, notes
            FROM road_risks
            WHERE station_proximity = %s AND risk_level IN ('High', 'Very High')
        """, [boat["nearest_station"]])
        row = cur.fetchone()
        cur.close()
        conn.close()
        if row:
            return {"road_id": row[0], "road_name": row[1], "risk_level": row[2],
                    "station": row[3], "notes": row[4]}
    except Exception:
        pass
    return None


def nearest_safe_zone(district: str) -> Optional[Dict]:
    """Recommend nearest safe zone in the given district."""
    if _db_unavailable:
        return None
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            SELECT id, name, zone_type, district, lat, lon, capacity
            FROM safe_zones
            WHERE district = %s
            ORDER BY id LIMIT 1
        """, [district])
        row = cur.fetchone()
        cur.close()
        conn.close()
        if row:
            return {"id": row[0], "name": row[1], "type": row[2], "district": row[3],
                    "lat": row[4], "lon": row[5], "capacity": row[6]}
    except Exception:
        pass
    return None


def triage(sos_lat: float, sos_lon: float) -> Dict:
    """Full SOS triage: boats, road risks, safe zone."""
    boats = nearest_boats(sos_lat, sos_lon)
    result = {
        "sos_coordinates": (sos_lat, sos_lon),
        "boats_available": len(boats),
        "nearest_boats": boats[:3],
        "road_alerts": [],
        "safe_zone": None,
    }

    if len(boats) < 2:
        result["escalate"] = True
        result["escalate_reason"] = f"Only {len(boats)} boat(s) available — manual triage required"
    else:
        result["escalate"] = False

    for b in boats[:3]:
        risk = road_risk_check(b)
        if risk:
            result["road_alerts"].append({**risk, "boat": b["call_sign"]})

    if boats:
        zone = nearest_safe_zone(boats[0]["district"])
        if zone:
            result["safe_zone"] = zone

    return result


def format_triage(result: Dict) -> str:
    """Format triage result as a readable message for Telegram."""
    lines = [
        f"🆘 SOS at {result['sos_coordinates'][0]:.4f}, {result['sos_coordinates'][1]:.4f}",
    ]

    if result["nearest_boats"]:
        boat_strs = [f"{b['call_sign']} ({b['distance_km']}km)" for b in result["nearest_boats"]]
        lines.append(f"Nearest: {' | '.join(boat_strs)}")
    else:
        lines.append("No boats available within 2h window")

    for ra in result["road_alerts"]:
        lines.append(f"⚠️ {ra['road_name']} {ra['risk_level']} Risk on {ra['boat']} route")

    if result["safe_zone"]:
        sz = result["safe_zone"]
        lines.append(f"🏥 Recommend: {sz['name']} ({sz['type']}) — {sz['district']}")

    if result["escalate"]:
        lines.append(f"🔴 ESCALATE: {result['escalate_reason']}")

    return "\n".join(lines)


if __name__ == "__main__":
    lat = float(sys.argv[1]) if len(sys.argv) > 1 else 20.47
    lon = float(sys.argv[2]) if len(sys.argv) > 2 else 85.93
    result = triage(lat, lon)
    print(json.dumps(result, indent=2, default=str))
    print()
    print(format_triage(result))
