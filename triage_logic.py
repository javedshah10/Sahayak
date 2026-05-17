"""
SahayakMap — SOS Triage Logic (Task 7)
=======================================
Nearest 3 boats + road risk + safe zone recommendation.
Integrated into telegram_bot.py for SOS response.

Usage:
    python triage_logic.py <lat> <lon>     # manual test
"""

import math
import json
import logging
import os
import sys
from typing import List, Dict, Optional

import psycopg2
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

DATABASE_URL = os.getenv("URI", "")

if not DATABASE_URL:
    raise RuntimeError("Set URI in .env for Supabase connection")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("SahayakMap.Triage")


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return distance in kilometres between two WGS84 coordinates."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return round(R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a)), 2)


def get_db():
    return psycopg2.connect(DATABASE_URL)


def nearest_boats(lat: float, lon: float, limit: int = 5) -> List[Dict]:
    """Query boat_assets for Safe/Active boats with recent pings, sorted by distance."""
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
    boats.sort(key=lambda b: b["distance_km"])
    return boats[:limit]


def road_risk_check(boat: Dict) -> Optional[Dict]:
    """Check road_risks table for elevated risk on boat's nearest station."""
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
