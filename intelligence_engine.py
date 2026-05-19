"""
SahayakMap — Intelligence Rules Engine
=======================================
Reads CSVs from fetch_river_data.py and applies all 7 PRD scenarios
as actionable alert rules for Rajesh.

Every rule produces a structured Alert with:
  - priority   : 1 (critical) / 2 (warning) / 3 (watch)
  - title      : one-line summary for phone screen
  - detail     : what data triggered it + confidence
  - action     : exact recommended action for Rajesh
  - data_basis : which sources, how fresh

Install:
    pip install pandas numpy

Usage:
    python intelligence_engine.py              # run all rules once
    python intelligence_engine.py --loop       # run every 15 min
    python intelligence_engine.py --rule R1    # run single rule
"""

import io
import os
import sys
import json
import logging
import argparse
import time
import schedule
import pandas as pd
import numpy as np
import psycopg2
from dotenv import load_dotenv
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field, asdict
from typing import Optional
from glob import glob

load_dotenv()

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("intelligence.log", encoding="utf-8")
    ]
)
log = logging.getLogger("SahayakMap.Intelligence")

DATA_DIR    = "data"          # where fetch_river_data.py writes CSVs
ALERTS_FILE = "alerts.json"  # output — append-only alert log

DATABASE_URL = os.getenv("URI", "postgresql://postgres:Joodei12@localhost:5432/sahayakmap")

def get_db():
    return psycopg2.connect(DATABASE_URL, connect_timeout=3)


# ════════════════════════════════════════════════════════════════════
# STATION KNOWLEDGE BASE
# Everything Rajesh's system needs to know but isn't in the CSV
# ════════════════════════════════════════════════════════════════════

STATIONS = {
    "Naraj": {
        "river": "Mahanadi", "district": "Cuttack",
        "warning": 25.41, "danger": 26.41, "hfl": 27.61,
        "tier": 1,
        "downstream_of": ["Tikarpara", "Kantamal", "Hirakud"],
        "lead_time_hours": 6,        # Tikarpara rise → Naraj flood
        "controls_districts": ["Cuttack", "Jagatsinghpur", "Kendrapara"],
    },
    "Jenapur": {
        "river": "Brahmani", "district": "Jajpur",
        "warning": 22.00, "danger": 23.00, "hfl": 24.78,
        "tier": 1,
        "downstream_of": ["Rengali Reservoir"],
        "lead_time_hours": 10,
        "controls_districts": ["Jajpur", "Bhadrak"],
        "note": "PRD Scenario 1 — gauge vs 47 tweets blind spot"
    },
    "Anandpur": {
        "river": "Baitarani", "district": "Keonjhar",
        "warning": 37.44, "danger": 38.36, "hfl": 41.35,
        "tier": 1,
        "downstream_of": [],
        "lead_time_hours": 8,
        "controls_districts": ["Keonjhar", "Bhadrak"],
    },
    "Akhuapada": {
        "river": "Baitarani", "district": "Bhadrak",
        "warning": 17.83, "danger": 17.83, "hfl": 21.95,
        "tier": 1,
        "downstream_of": ["Anandpur"],
        "lead_time_hours": 0,
        "controls_districts": ["Bhadrak"],
    },
    "Tikarpara": {
        "river": "Mahanadi", "district": "Angul",
        "warning": 69.10, "danger": 70.10, "hfl": 74.98,
        "tier": 2,
        "downstream_of": [],
        "lead_time_hours": 6,        # this many hours before Naraj rises
        "controls_districts": ["Angul"],
    },
    "Kantamal": {
        "river": "Mahanadi", "district": "Boudh",
        "warning": 126.10, "danger": 127.10, "hfl": 130.64,
        "tier": 2,
        "downstream_of": [],
        "lead_time_hours": 8,
        "controls_districts": ["Boudh"],
    },
    "Salebhata": {
        "river": "Mahanadi", "district": "Bargarh",
        "warning": 107.81, "danger": 108.81, "hfl": 110.82,
        "tier": 2,
        "downstream_of": [],
        "lead_time_hours": 10,
        "controls_districts": ["Bargarh"],
    },
    "Purusottampur": {
        "river": "Rushikulya", "district": "Ganjam",
        "warning": 15.835, "danger": 16.835, "hfl": 19.655,
        "tier": 2,
        "downstream_of": [],
        "lead_time_hours": 0,
        "controls_districts": ["Ganjam"],
        "note": "PRD Scenario 6 — silent district proxy for Ganjam"
    },
    "Rengali Reservoir": {
        "river": "Brahmani", "district": "Angul",
        "warning": 123.00, "danger": 123.50, "hfl": 125.40,
        "tier": 2,
        "downstream_of": [],
        "lead_time_hours": 10,
        "controls_districts": ["Jajpur", "Bhadrak"],
        "note": "Dam release → Jenapur floods in ~10hrs"
    },
}

# Relief camps — Scenario 7 (yesterday's rescue = today's hazard)
RELIEF_CAMPS = [
    {
        "name": "Erasama School Camp",
        "district": "Jagatsinghpur",
        "elevation_masl": 8.0,       # metres above mean sea level
        "capacity": 340,
        "nearest_station": "Naraj",
        "flood_trigger_wse": 24.5,   # Naraj WSE at which camp is at risk
    },
    {
        "name": "Kendrapara Block Office",
        "district": "Kendrapara",
        "elevation_masl": 6.0,
        "capacity": 120,
        "nearest_station": "Naraj",
        "flood_trigger_wse": 25.0,
    },
]

# Road/Bridge critical points — Scenario 2
# TASK 2 — Tactical bridge naming
CRITICAL_ROUTES = [
    {
        "name": "NH-16 Jenapur Bridge",
        "bridge_name": "Jenapur Bridge (NH-16)",
        "district": "Jajpur",
        "nearest_station": "Jenapur",
        "submerged_at_wse": 21.50,
        "route_serves": "Bhubaneswar → Balasore supply convoy",
    },
    {
        "name": "Mundali Barrage Access",
        "bridge_name": "Mundali Barrage / NH-16 Access",
        "district": "Cuttack",
        "nearest_station": "Naraj",
        "submerged_at_wse": 25.00,
        "route_serves": "Cuttack → Dhenkanal supply route",
    },
    {
        "name": "Baitarani Bridge Route",
        "bridge_name": "Baitarani Bridge (NH-16)",
        "district": "Bhadrak",
        "nearest_station": "Akhuapada",
        "submerged_at_wse": 17.00,
        "route_serves": "Bhadrak → Balasore evacuation corridor",
    },
    {
        "name": "Devi River Boat Route",
        "bridge_name": None,
        "district": "Jagatsinghpur",
        "nearest_station": "Naraj",
        "viable_above_wse": 22.00,
        "route_serves": "Kendrapara → Jagatsinghpur redeployment",
    },
]

# Upstream → Downstream relationships for early warning
UPSTREAM_DOWNSTREAM = [
    {
        "upstream": "Tikarpara",
        "downstream": "Naraj",
        "lead_time_hours": 6,
        "trigger_wse_upstream": 69.10,  # warning level of upstream
    },
    {
        "upstream": "Anandpur",
        "downstream": "Akhuapada",
        "lead_time_hours": 8,
        "trigger_wse_upstream": 37.44,
    },
    {
        "upstream": "Rengali Reservoir",
        "downstream": "Jenapur",
        "lead_time_hours": 10,
        "trigger_wse_upstream": None,   # any large release triggers
    },
    {
        "upstream": "Kantamal",
        "downstream": "Naraj",
        "lead_time_hours": 8,
        "trigger_wse_upstream": 126.10,
    },
]


# ════════════════════════════════════════════════════════════════════
# ALERT DATA CLASS
# ════════════════════════════════════════════════════════════════════

@dataclass
class Alert:
    rule_id:     str
    priority:    int          # 1=Critical, 2=Warning, 3=Watch
    title:       str          # One line — what Rajesh sees on phone
    detail:      str          # Why — data basis in plain language
    action:      str          # Exact recommended action
    district:    str
    station:     str
    current_wse: Optional[float] = None
    danger_level: Optional[float] = None
    confidence:  float = 1.0  # 0.0–1.0
    data_age_min: int = 0     # how old is the triggering data
    timestamp:   str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def emoji(self):
        return {1: "🔴", 2: "🟡", 3: "🔵"}.get(self.priority, "⚪")

    def to_dict(self):
        d = asdict(self)
        d["emoji"] = self.emoji()
        return d

    # FIX 2C — format age as minutes/hours/days
    @staticmethod
    def format_age(minutes: int) -> str:
        if minutes < 60:
            return f"{int(minutes)}min old"
        elif minutes < 1440:
            h = int(minutes // 60)
            m = int(minutes % 60)
            return f"{h}h {m}min old"
        else:
            d = int(minutes // 1440)
            h = int((minutes % 1440) // 60)
            return f"{d}d {h}h old"

    def __str__(self):
        age_str = self.format_age(self.data_age_min)
        stale_prefix = "⚠️ STALE DATA — " if self.data_age_min > 4320 else ""
        return (
            f"\n{'='*60}\n"
            f"{self.emoji()} ALERT [{self.rule_id}] — Priority {self.priority}\n"
            f"📍 {self.district} | 📡 {self.station}\n"
            f"⚠️  {stale_prefix}{self.title}\n"
            f"📊 {self.detail}\n"
            f"✅ ACTION: {self.action}\n"
            f"🎯 Confidence: {int(self.confidence*100)}% | Data age: {age_str}\n"
            f"{'='*60}"
        )


# ════════════════════════════════════════════════════════════════════
# CSV LOADER — reads CSVs written by fetch_river_data.py
# ════════════════════════════════════════════════════════════════════

def load_station_csv(station: str, metric: str = "wse", recency_hours: Optional[int] = 48) -> Optional[pd.DataFrame]:
    """Load station CSV with optional recency filter."""
    safe = station.lower().replace(" ", "_").replace("/", "-")
    filename = os.path.join(DATA_DIR, f"{safe}_{metric}.csv")
    if not os.path.exists(filename):
        log.warning(f"No file: {filename}")
        return None
    try:
        df = pd.read_csv(filename, parse_dates=["timestamp"])
        df = df.dropna(subset=["value"]).sort_values("timestamp")
        # FIX BUG 2 — filter to only recent data (tz-naive comparison)
        if recency_hours and not df.empty:
            cutoff = datetime.utcnow() - timedelta(hours=recency_hours)
            if df["timestamp"].dt.tz is not None:
                cutoff = cutoff.replace(tzinfo=timezone.utc)
            df = df[df["timestamp"] >= cutoff]
        return df
    except Exception as e:
        log.error(f"Failed to load {filename}: {e}")
        return None


def get_latest(station: str, metric: str = "wse") -> Optional[dict]:
    """Return the most recent reading for a station."""
    df = load_station_csv(station, metric, recency_hours=48)
    # FIX 2B — skip if no data in last 48h
    if df is None or df.empty:
        log.info(f"SKIP {station}: no recent data (last 48h)")
        return None
    row = df.iloc[-1]
    age_min = int((datetime.utcnow() - row["timestamp"].to_pydatetime().replace(tzinfo=None)).total_seconds() / 60)
    return {
        "station":   station,
        "metric":    metric,
        "value":     row["value"],
        "timestamp": str(row["timestamp"]),
        "age_min":   age_min,
    }


def get_rise_rate(station: str, window_hours: int = 3) -> Optional[float]:
    """
    Calculate WSE rise rate in metres/hour over last N hours.
    Positive = rising, Negative = falling.
    """
    df = load_station_csv(station, "wse", recency_hours=48)
    if df is None or len(df) < 2:
        return None
    cutoff = df["timestamp"].max() - pd.Timedelta(hours=window_hours)
    window = df[df["timestamp"] >= cutoff]
    if len(window) < 2:
        return None
    time_diff_hours = (window["timestamp"].max() - window["timestamp"].min()).total_seconds() / 3600
    wse_diff = window["value"].iloc[-1] - window["value"].iloc[0]
    if time_diff_hours == 0:
        return None
    return round(wse_diff / time_diff_hours, 4)


def data_age_minutes(station: str, metric: str = "wse") -> int:
    """How many minutes ago was this station last updated?"""
    latest = get_latest(station, metric)
    if latest is None:
        return 9999
    return latest["age_min"]


# ════════════════════════════════════════════════════════════════════
# RULES ENGINE
# ════════════════════════════════════════════════════════════════════

class RulesEngine:

    def __init__(self):
        self.alerts: list[Alert] = []
        self._imd_data: dict | None = None

    def _load_imd(self) -> dict:
        """Load IMD nowcast data from fixtures/imd_nowcast.json (cached)."""
        if self._imd_data is not None:
            return self._imd_data
        imd_path = os.path.join("fixtures", "imd_nowcast.json")
        try:
            with open(imd_path) as f:
                self._imd_data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            self._imd_data = {}
        return self._imd_data

    def _imd_station_wms(self, station_name: str) -> int:
        """Get wms_color for a station from IMD data (0 if not found)."""
        imd = self._load_imd()
        stations = imd.get("imd", {}).get("stations", [])
        for s in stations:
            if s.get("name") == station_name:
                return s.get("wms_color", 1)
        return 0

    def _imd_district_wms(self, district: str) -> int:
        """Get max wms_color for a district from IMD data."""
        imd = self._load_imd()
        stations = imd.get("imd", {}).get("stations", [])
        max_wms = 0
        dl = district.lower()
        for s in stations:
            if s.get("district_proxy", "").lower() == dl:
                max_wms = max(max_wms, s.get("wms_color", 1))
        return max_wms

    # FIX 2A — skip duplicate alerts (same station+rule within 2h)
    def _alert_exists(self, station_name: str, rule_id: str) -> bool:
        try:
            conn = get_db()
            cur = conn.cursor()
            cur.execute("SELECT id FROM stations WHERE name = %s", [station_name])
            row = cur.fetchone()
            if not row:
                return False
            cur.execute(
                "SELECT id FROM alerts WHERE station_id = %s AND rule_id = %s"
                " AND created_at > NOW() - INTERVAL '2 hours'",
                [row[0], rule_id]
            )
            exists = cur.fetchone() is not None
            cur.close()
            conn.close()
            return exists
        except Exception:
            return False

    def add(self, alert: Alert):
        if self._alert_exists(alert.station, alert.rule_id):
            return
        self.alerts.append(alert)
        log.info(str(alert))

    # ── R1: THRESHOLD BREACH ─────────────────────────────────────────
    # PRD: "Rajesh does not know that Naraj is 1.2m above danger level"
    def rule_R1_threshold_breach(self):
        """Core alert: any station crosses warning or danger threshold."""
        for name, info in STATIONS.items():
            latest = get_latest(name, "wse")
            if latest is None:
                continue

            wse     = latest["value"]
            age     = latest["age_min"]
            warning = info.get("warning")
            danger  = info.get("danger")
            hfl     = info.get("hfl")
            river   = info["river"]
            district= info["district"]

            if hfl and wse >= hfl:
                self.add(Alert(
                    rule_id="R1-EXTREME",
                    priority=1,
                    title=f"{name} ({river}) has hit HIGHEST FLOOD LEVEL: {wse}m",
                    detail=f"HFL is {hfl}m. This is a historic flood event.",
                    action=f"MAXIMUM MOBILISATION. Evacuate all low-lying areas in {district} immediately. Request Army/Navy support.",
                    district=district, station=name,
                    current_wse=wse, danger_level=hfl,
                    confidence=0.95, data_age_min=age
                ))
            elif danger and wse >= danger:
                rise = get_rise_rate(name)
                rise_str = f"Rising at {rise:.2f}m/hr." if rise and rise > 0 else "Level stable or falling."
                self.add(Alert(
                    rule_id="R1-DANGER",
                    priority=1,
                    title=f"{name} ({river}) ABOVE DANGER LEVEL: {wse}m / Danger: {danger}m",
                    detail=f"Gap to HFL: {round((hfl or danger+2) - wse, 2)}m. {rise_str}",
                    action=f"Deploy rescue boats to {district}. Alert district collector. Pre-position evacuation teams.",
                    district=district, station=name,
                    current_wse=wse, danger_level=danger,
                    confidence=0.95, data_age_min=age
                ))
            elif warning and wse >= warning:
                rise = get_rise_rate(name)
                hrs_to_danger = None
                if rise and rise > 0 and danger:
                    hrs_to_danger = round((danger - wse) / rise, 1)
                time_str = f"At current rate, danger level in ~{hrs_to_danger}hrs." if hrs_to_danger else ""
                self.add(Alert(
                    rule_id="R1-WARNING",
                    priority=2,
                    title=f"{name} ({river}) at WARNING level: {wse}m / Warning: {warning}m",
                    detail=f"Danger level is {danger}m. Gap: {round(danger - wse, 2) if danger else 'N/A'}m. {time_str}",
                    action=f"Put rescue teams in {district} on standby. Monitor every 15 minutes.",
                    district=district, station=name,
                    current_wse=wse, danger_level=danger,
                    confidence=0.90, data_age_min=age
                ))

    # ── R2: RAPID RISE RATE ─────────────────────────────────────────
    # PRD: "rising at 0.3 metres per hour" — rate matters, not just level
    def rule_R2_rapid_rise(self):
        """Alert when WSE is rising dangerously fast even below warning."""
        RAPID_RISE_THRESHOLD = 0.25  # metres per hour
        for name, info in STATIONS.items():
            rise = get_rise_rate(name, window_hours=3)
            if rise is None or rise < RAPID_RISE_THRESHOLD:
                continue
            latest = get_latest(name, "wse")
            if latest is None:
                continue
            wse    = latest["value"]
            danger = info.get("danger")
            age    = latest["age_min"]
            if danger:
                hrs_to_danger = round((danger - wse) / rise, 1) if rise > 0 else 99
                self.add(Alert(
                    rule_id="R2-RAPID-RISE",
                    priority=2 if hrs_to_danger > 3 else 1,
                    title=f"{name} rising FAST: +{rise}m/hr — danger in ~{hrs_to_danger}hrs",
                    detail=f"Current WSE: {wse}m. Danger: {danger}m. Rise rate over last 3hrs: {rise}m/hr.",
                    action=f"Pre-position rescue assets in {info['district']} NOW. Do not wait for danger level.",
                    district=info["district"], station=name,
                    current_wse=wse, danger_level=danger,
                    confidence=0.85, data_age_min=age
                ))

    # ── R3: UPSTREAM EARLY WARNING ─────────────────────────────────
    # PRD Scenario 3: "boats are in wrong district" because forecast was wrong
    # Upstream gauge is the most reliable 6-hour predictor
    def rule_R3_upstream_warning(self):
        """
        Tikarpara rising → Naraj will flood in 6 hours.
        Also checks IMD: heavy rain at upstream → early warning even if WSE normal.
        """
        for link in UPSTREAM_DOWNSTREAM:
            upstream   = link["upstream"]
            downstream = link["downstream"]
            lead_hrs   = link["lead_time_hours"]
            trigger    = link["trigger_wse_upstream"]

            up_latest = get_latest(upstream, "wse")
            imd_trigger = False
            up_wse = None
            age = 0
            triggered_by = ""

            # Check WSE trigger
            if up_latest is not None:
                up_wse = up_latest["value"]
                age = up_latest["age_min"]
                if trigger and up_wse >= trigger:
                    triggered_by = "WSE"

            # Check IMD trigger (wms_color >= 3 = Alert/Warning)
            if not triggered_by and self._imd_station_wms(upstream) >= 3:
                triggered_by = "IMD"
                up_wse = up_wse or 0
                age = age or 0

            if not triggered_by:
                continue

            down_info  = STATIONS.get(downstream, {})
            down_danger= down_info.get("danger")
            down_dist  = down_info.get("district", downstream)

            if triggered_by == "IMD":
                self.add(Alert(
                    rule_id="R3-IMD-UPSTREAM",
                    priority=2,
                    title=f"IMD UPSTREAM WARNING: Heavy rain at {upstream}. Expect WSE rise at {downstream} in {lead_hrs}hrs.",
                    detail=(
                        f"IMD Alert/Warning issued for {upstream} (wms_color>=3). "
                        f"Historical lead time to {downstream}: {lead_hrs}hrs. "
                        f"WSE at {upstream}: {up_wse}m (trigger: {trigger}m)."
                    ),
                    action=(
                        f"Move rescue assets toward {down_dist} NOW. "
                        f"IMD warns of heavy rain at {upstream} — {downstream} likely to flood in ~{lead_hrs}hrs. "
                        f"Do not wait for the downstream gauge to confirm."
                    ),
                    district=down_dist, station=upstream,
                    current_wse=up_wse, danger_level=trigger,
                    confidence=0.75, data_age_min=age
                ))
            else:
                self.add(Alert(
                    rule_id="R3-UPSTREAM",
                    priority=2,
                    title=f"EARLY WARNING: {upstream} rising → {downstream} expected to flood in ~{lead_hrs}hrs",
                    detail=(
                        f"{upstream} WSE: {up_wse}m (trigger: {trigger}m). "
                        f"Historical lead time to {downstream}: {lead_hrs}hrs.",
                    ),
                    action=(
                        f"Move rescue assets toward {down_dist} NOW. "
                        f"You have {lead_hrs}hrs before {downstream} hits danger level ({down_danger}m). "
                        f"Do not wait for the downstream gauge to confirm."
                    ),
                    district=down_dist, station=upstream,
                    current_wse=up_wse, danger_level=trigger,
                    confidence=0.80, data_age_min=age
                ))

    # ── R4: TRIPLE RIVER CONFLUENCE ALERT ──────────────────────────
    # PRD: worst floods when Mahanadi + Brahmani + Baitarani ALL flood together
    def rule_R4_triple_confluence(self):
        """
        If Naraj + Jenapur + Anandpur are ALL above warning simultaneously
        → catastrophic delta flooding imminent.
        """
        mahanadi  = get_latest("Naraj", "wse")
        brahmani  = get_latest("Jenapur", "wse")
        baitarani = get_latest("Anandpur", "wse")

        if not all([mahanadi, brahmani, baitarani]):
            return

        m_above = mahanadi["value"]  >= STATIONS["Naraj"]["warning"]
        b_above = brahmani["value"]  >= STATIONS["Jenapur"]["warning"]
        bt_above= baitarani["value"] >= STATIONS["Anandpur"]["warning"]

        rivers_above = sum([m_above, b_above, bt_above])

        if rivers_above == 3:
            self.add(Alert(
                rule_id="R4-CONFLUENCE-CRITICAL",
                priority=1,
                title="TRIPLE RIVER CONFLUENCE — ALL THREE RIVERS ABOVE WARNING",
                detail=(
                    f"Mahanadi at Naraj: {mahanadi['value']}m (warning: {STATIONS['Naraj']['warning']}m) | "
                    f"Brahmani at Jenapur: {brahmani['value']}m (warning: {STATIONS['Jenapur']['warning']}m) | "
                    f"Baitarani at Anandpur: {baitarani['value']}m (warning: {STATIONS['Anandpur']['warning']}m). "
                    "All three rivers share the Odisha delta. Combined flooding imminent."
                ),
                action=(
                    "MAXIMUM ALERT. Request state EOC to mobilise ALL available assets. "
                    "Delta districts (Kendrapara, Jagatsinghpur, Bhadrak, Balasore) need immediate evacuation. "
                    "Contact SDMA for Army/Navy/Air Force support."
                ),
                district="Delta (Kendrapara/Jagatsinghpur/Bhadrak)",
                station="Naraj+Jenapur+Anandpur",
                confidence=0.95,
                data_age_min=max(mahanadi["age_min"], brahmani["age_min"], baitarani["age_min"])
            ))
        elif rivers_above == 2:
            self.add(Alert(
                rule_id="R4-CONFLUENCE-WARNING",
                priority=2,
                title=f"TWO RIVERS ABOVE WARNING — delta flooding risk elevated",
                detail=f"{rivers_above}/3 rivers above warning. Confluence flooding possible within 12hrs.",
                action="Pre-position assets in delta districts. Monitor third river hourly.",
                district="Odisha Delta",
                station="Multi-station",
                confidence=0.75,
                data_age_min=max(mahanadi["age_min"], brahmani["age_min"], baitarani["age_min"])
            ))

    # ── R5: RELIEF CAMP INUNDATION RISK ────────────────────────────
    # PRD Scenario 7: "yesterday's rescue is today's hazard"
    def rule_R5_camp_safety(self):
        """
        Project flood progression — will a relief camp be inundated
        in next 6, 12, or 24 hours?
        """
        for camp in RELIEF_CAMPS:
            station  = camp["nearest_station"]
            trigger  = camp["flood_trigger_wse"]
            latest   = get_latest(station, "wse")
            if latest is None:
                continue

            wse      = latest["value"]
            age      = latest["age_min"]
            rise     = get_rise_rate(station)

            if rise is None or rise <= 0:
                continue  # not rising

            hrs_to_trigger = (trigger - wse) / rise if rise > 0 else 999

            if wse >= trigger:
                self.add(Alert(
                    rule_id="R5-CAMP-NOW",
                    priority=1,
                    title=f"CAMP AT RISK NOW: {camp['name']} ({camp['district']})",
                    detail=(
                        f"Flood trigger WSE at {station}: {trigger}m. "
                        f"Current WSE: {wse}m — threshold already crossed. "
                        f"Camp elevation: {camp['elevation_masl']}m AMSL. "
                        f"Capacity: {camp['capacity']} persons."
                    ),
                    action=f"EVACUATE {camp['name']} IMMEDIATELY. {camp['capacity']} persons need relocation to higher ground.",
                    district=camp["district"], station=station,
                    current_wse=wse, danger_level=trigger,
                    confidence=0.90, data_age_min=age
                ))
            elif hrs_to_trigger <= 6:
                self.add(Alert(
                    rule_id="R5-CAMP-6HR",
                    priority=1,
                    title=f"CAMP RISK in ~{round(hrs_to_trigger,1)}hrs: {camp['name']}",
                    detail=(
                        f"Rising at {rise}m/hr. WSE: {wse}m → trigger: {trigger}m. "
                        f"{camp['capacity']} persons at {camp['name']}. "
                        f"30% model uncertainty — act early."
                    ),
                    action=(
                        f"Begin evacuation planning for {camp['name']} NOW. "
                        f"Identify alternative camp site above {camp['elevation_masl']+3}m AMSL. "
                        f"Do not wait for confirmation — cost of delay is lives."
                    ),
                    district=camp["district"], station=station,
                    current_wse=wse, danger_level=trigger,
                    confidence=0.70, data_age_min=age
                ))
            elif hrs_to_trigger <= 12:
                self.add(Alert(
                    rule_id="R5-CAMP-12HR",
                    priority=2,
                    title=f"CAMP WATCH 12hr: {camp['name']} — prepare contingency",
                    detail=(
                        f"At current rise rate ({rise}m/hr), camp at risk in ~{round(hrs_to_trigger,1)}hrs. "
                        f"Capacity: {camp['capacity']} persons."
                    ),
                    action=f"Identify evacuation route and alternate camp for {camp['name']}. No action needed yet — monitor every 30 min.",
                    district=camp["district"], station=station,
                    current_wse=wse, danger_level=trigger,
                    confidence=0.60, data_age_min=age
                ))

    # ── R6: ROUTE VIABILITY CHECK ───────────────────────────────────
    # PRD Scenario 2: "supply convoy about to hit a dead end"
    def rule_R6_route_viability(self):
        """Check if critical roads/bridges are still passable."""
        for route in CRITICAL_ROUTES:
            station = route["nearest_station"]
            latest  = get_latest(station, "wse")
            if latest is None:
                continue

            wse  = latest["value"]
            age  = latest["age_min"]
            name = route["name"]
            bridge = route.get("bridge_name", name)

            submerged_at = route.get("submerged_at_wse")
            viable_above = route.get("viable_above_wse")

            if submerged_at and wse >= submerged_at:
                self.add(Alert(
                    rule_id="R6-ROUTE-BLOCKED",
                    priority=1,
                    title=f"ROUTE RISK: {bridge} may be compromised",
                    detail=(
                        f"WSE at {station}: {wse}m. {bridge} submerges at {submerged_at}m. "
                        f"Serves: {route['route_serves']}. "
                        f"Activate alternative route protocol."
                    ),
                    action=(
                        f"DO NOT send convoy via {bridge}. "
                        f"Find alternate route immediately. "
                        f"Confirm with local police/ground team before rerouting."
                    ),
                    district=route["district"], station=station,
                    current_wse=wse, danger_level=submerged_at,
                    confidence=0.75, data_age_min=age
                ))
            elif viable_above and wse < viable_above:
                self.add(Alert(
                    rule_id="R6-ROUTE-NOT-VIABLE",
                    priority=2,
                    title=f"BOAT ROUTE NOT YET VIABLE: {name}",
                    detail=(
                        f"Boat route needs WSE above {viable_above}m. "
                        f"Current WSE at {station}: {wse}m. "
                        f"Serves: {route['route_serves']}."
                    ),
                    action=f"Use road transport instead of {name} for now. Reassess when WSE exceeds {viable_above}m.",
                    district=route["district"], station=station,
                    current_wse=wse, danger_level=viable_above,
                    confidence=0.80, data_age_min=age
                ))

    # ── R7: SILENT DISTRICT DETECTION ───────────────────────────────
    # PRD Scenario 6: "Ganjam has filed zero reports — which district is worse?"
    def rule_R7_silent_district(self):
        """
        If a station has stopped updating (data > 3hrs old),
        use upstream proxy to infer what's happening.
        """
        STALE_THRESHOLD_MIN = 180  # 3 hours

        for name, info in STATIONS.items():
            age = data_age_minutes(name, "wse")
            if age < STALE_THRESHOLD_MIN:
                continue

            district = info["district"]
            river    = info["river"]

            # Try to find proxy signal from upstream station
            upstream_signal = None
            for link in UPSTREAM_DOWNSTREAM:
                if link["downstream"] == name:
                    up_latest = get_latest(link["upstream"], "wse")
                    if up_latest:
                        upstream_signal = up_latest

            if upstream_signal:
                up_wse     = upstream_signal["value"]
                up_station = upstream_signal["station"]
                up_trigger = next(
                    (l["trigger_wse_upstream"] for l in UPSTREAM_DOWNSTREAM
                     if l["downstream"] == name), None
                )
                rising = get_rise_rate(up_station)
                inference = (
                    "UPSTREAM IS RISING — likely means communication loss due to flooding, NOT absence of flooding."
                    if (up_trigger and up_wse >= up_trigger) or (rising and rising > 0.1)
                    else "Upstream appears stable — possible equipment failure rather than flooding."
                )

                self.add(Alert(
                    rule_id="R7-SILENT-STATION",
                    priority=2,
                    title=f"DATA GAP: {name} ({district}) — no update for {age//60}hrs {age%60}min",
                    detail=(
                        f"Station {name} on {river} has not reported for {age} minutes. "
                        f"Proxy check: {up_station} WSE={up_wse}m. "
                        f"{inference}"
                    ),
                    action=(
                        f"Do NOT assume {district} is safe. "
                        f"Dispatch reconnaissance team or contact district collector directly. "
                        f"Use {up_station} as proxy — if it's rising, treat {district} as at risk."
                    ),
                    district=district, station=name,
                    confidence=0.60, data_age_min=age
                ))
            else:
                self.add(Alert(
                    rule_id="R7-SILENT-NO-PROXY",
                    priority=2,
                    title=f"DATA GAP: {name} ({district}) — {age//60}hrs {age%60}min, NO PROXY AVAILABLE",
                    detail=f"Station {name} silent. No upstream proxy data available. Cannot infer status.",
                    action=f"Treat {district} as UNKNOWN — highest risk category. Contact district collector immediately.",
                    district=district, station=name,
                    confidence=0.40, data_age_min=age
                ))

    # ── R8: EVENT-AWARE STALE DATA THRESHOLD ──────────────────────────
    # TASK 1 — Normal: 48h threshold. Active flood: 8h, Priority 1.
    def rule_R8_stale_data(self):
        """
        Dynamic stale-data threshold. 48h normally, drops to 8h
        when any station crosses warning level (active flood state).
        """
        # Check if system is in active flood state
        active_flood = False
        for sname, sinfo in STATIONS.items():
            wlevel = sinfo.get("warning")
            if wlevel is None:
                continue
            latest = get_latest(sname, "wse")
            if latest and latest["value"] >= wlevel:
                active_flood = True
                break

        threshold = 8 * 60 if active_flood else 48 * 60  # minutes

        for name in STATIONS:
            age = data_age_minutes(name, "wse")
            if age > threshold:
                if active_flood:
                    self.add(Alert(
                        rule_id="R8-COMM-BLACKOUT",
                        priority=1,
                        title=f"COMM-BLACKOUT: {name} silent for {age//60}h {age%60}min. Possible infrastructure failure. Deploy field check.",
                        detail=f"Active flood state detected. {name} gauge has not reported in {age//60}h {age%60}min.",
                        action=f"URGENT: Deploy field crew to {STATIONS[name]['district']}. Confirm gauge status. Use upstream/social signals in the meantime.",
                        district=STATIONS[name]["district"], station=name,
                        confidence=0.85, data_age_min=age
                    ))
                else:
                    self.add(Alert(
                        rule_id="R8-STALE-DATA",
                        priority=3,
                        title=f"STALE DATA: {name} — last reading {age//60}h {age%60}min ago",
                        detail=f"Any decisions based on {name} data may be outdated.",
                        action=f"Do not rely on {name} readings. Check if portal is down. Use upstream/social signals instead.",
                        district=STATIONS[name]["district"], station=name,
                        confidence=1.0, data_age_min=age
                    ))

    # ── R9: TRIPWIRE SOCIAL SCAN ─────────────────────────────────────
    # PRD Open Question #5: Naraj at 25.5m (below danger 26.41m) triggers
    # social media scan for Jajpur district to detect silent ground truth
    def rule_R9_tripwire_social_scan(self):
        """
        Trigger: Naraj WSE >= 25.5m OR IMD wms_color >= 3 for Jajpur.
        Scans Twitter dummy fixture for Jajpur district posts within last 45min.
        1-9 posts = Signal  |  10+ posts = Verified Crisis alert.
        """
        TRIPWIRE = 25.5
        naraj = get_latest("Naraj", "wse")
        trigger_wse = naraj is not None and naraj["value"] >= TRIPWIRE
        trigger_imd = self._imd_district_wms("Jajpur") >= 3
        triggered_by = []

        if trigger_wse:
            triggered_by.append(f"Naraj WSE {naraj['value']}m")
        if trigger_imd:
            triggered_by.append("IMD Warning for Jajpur")

        if not triggered_by:
            return

        naraj_val = naraj["value"] if naraj else 0
        naraj_age = naraj["age_min"] if naraj else 0
        trigger_detail = " | ".join(triggered_by)

        twitter_path = os.path.join("fixtures", "dummy_twitter.json")
        try:
            with open(twitter_path) as f:
                posts = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            log.warning("Cannot load dummy_twitter.json — skipping social scan")
            return

        now = datetime.utcnow()
        cutoff = now - timedelta(minutes=45)
        jajpur_posts = [
            p for p in posts
            if p.get("district", "").lower() == "jajpur"
            and datetime.fromisoformat(p["timestamp"]) >= cutoff
        ]
        count = len(jajpur_posts)

        if count >= 10:
            self.add(Alert(
                rule_id="R9-SOCIAL-VERIFIED",
                priority=1,
                title=f"VERIFIED CRISIS: {count} social posts confirm Jajpur flooding",
                detail=(
                    f"Trigger: {trigger_detail}. "
                    f"{count} social media posts from Jajpur in last 45min. "
                    f"Threshold of 10 crossed — verified ground crisis."
                ),
                action=(
                    "Deploy rescue teams to Jajpur immediately. "
                    "Social signals confirm ground flooding. "
                    "Coordinate with District Collector Jajpur."
                ),
                district="Jajpur",
                station="Naraj",
                current_wse=naraj_val,
                danger_level=TRIPWIRE,
                confidence=0.85,
                data_age_min=naraj_age
            ))
            log.info("VERIFIED CRISIS: Jajpur — %d social posts in 45min", count)
        elif count >= 1:
            self.add(Alert(
                rule_id="R9-SOCIAL-SIGNAL",
                priority=2,
                title=f"SOCIAL SIGNAL: {count} posts from Jajpur in 45min — escalating",
                detail=(
                    f"Trigger: {trigger_detail}. "
                    f"{count} posts detected. Need {(10 - count)} more in window "
                    f"to trigger Verified Crisis."
                ),
                action=(
                    "Monitor Jajpur social channels closely. "
                    "Pre-position assessment team. "
                    "If count reaches 10+, escalate to full crisis response."
                ),
                district="Jajpur",
                station="Naraj",
                current_wse=naraj_val,
                danger_level=TRIPWIRE,
                confidence=0.70,
                data_age_min=naraj_age
            ))
            log.info("SOCIAL SIGNAL: Jajpur — %d posts in 45min (need 10 for crisis)", count)

    # ── R10: IMD NOWCAST CROSS-REFERENCE ────────────────────────────────
    # TASK 5 — Cross-reference IMD warnings with WSE trend (last 48h)
    def rule_R10_imd_nowcast(self):
        """
        Trigger: wms_color >= 3 (Alert or Warning) at any station.
        Cross-reference with last 48h WSE trend.
        """
        imd_path = os.path.join("fixtures", "imd_nowcast.json")
        try:
            with open(imd_path) as f:
                feeds = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return

        stations = feeds.get("imd", {}).get("stations", [])
        for s in stations:
            wms = s.get("wms_color", 1)
            if wms < 3:
                continue

            name = s.get("name", "")
            wse_latest = get_latest(name, "wse")
            if not wse_latest:
                continue

            wse = wse_latest["value"]
            age = wse_latest["age_min"]
            category = s.get("warning_category", "Alert")

            rise = get_rise_rate(name, window_hours=48)
            rising = rise is not None and rise > 0.01

            if rising:
                self.add(Alert(
                    rule_id="R10-IMD-RISING",
                    priority=1,
                    title=f"IMD ALERT + RISING WSE at {name}: {category}. WSE {wse}m and climbing.",
                    detail=f"IMD wms_color={wms} ({category}). WSE at {name}: {wse}m. Rise rate: {rise:.3f}m/hr over 48h. Cross-confirmed threat.",
                    action=f"MAXIMUM PRIORITY: IMD alert + rising gauge at {name}. Pre-deploy rescue assets. Evacuate low-lying areas in {s.get('district_proxy','Odisha')}.",
                    district=s.get("district_proxy", "Odisha"), station=name,
                    current_wse=wse, danger_level=wse + 1.0,
                    confidence=0.90, data_age_min=age
                ))
            else:
                self.add(Alert(
                    rule_id="R10-IMD-STABLE",
                    priority=2,
                    title=f"IMD ALERT at {name}: {category}. WSE stable at {wse}m. Monitor closely.",
                    detail=f"IMD wms_color={wms} ({category}). WSE at {name}: {wse}m, stable. Valid until {s.get('valid_upto','?')}.",
                    action=f"Monitor {name} closely. IMD warning active but WSE stable — reassess if gauge starts rising.",
                    district=s.get("district_proxy", "Odisha"), station=name,
                    current_wse=wse, danger_level=wse + 1.0,
                    confidence=0.75, data_age_min=age
                ))

    def run_all(self) -> list[Alert]:
        self.alerts = []

        log.info("\n" + "="*60)
        log.info(f"SahayakMap Intelligence Run — {datetime.utcnow().isoformat()} UTC")
        log.info("="*60)

        self.rule_R1_threshold_breach()
        self.rule_R2_rapid_rise()
        self.rule_R3_upstream_warning()
        self.rule_R4_triple_confluence()
        self.rule_R5_camp_safety()
        self.rule_R6_route_viability()
        self.rule_R7_silent_district()
        self.rule_R8_stale_data()
        self.rule_R9_tripwire_social_scan()
        self.rule_R10_imd_nowcast()

        return self.alerts

    def rajesh_briefing(self):
        """
        The final output Rajesh sees on his phone.
        Top 3 alerts only. Plain language. Actionable.
        """
        alerts = self.run_all()

        # Sort: priority first, then confidence
        alerts.sort(key=lambda a: (a.priority, -a.confidence))
        top3 = alerts[:3]

        print("\n" + "="*60)
        print("  SAHAYAKMAP BRIEFING FOR RAJESH")
        print(f"  {datetime.utcnow().strftime('%d %b %Y  %H:%M UTC')}")
        print("="*60)

        if not top3:
            print("\n✅ ALL CLEAR — All monitored stations normal.\n")
        else:
            print(f"\n⚠️  {len(alerts)} alerts detected. Showing top {len(top3)}:\n")
            for i, alert in enumerate(top3, 1):
                print(f"{alert.emoji()} #{i}  {alert.title}")
                print(f"       → {alert.action}")
                print(f"       📊 {alert.detail[:100]}...")
                print(f"       🎯 Confidence: {int(alert.confidence*100)}%  |  Data: {Alert.format_age(alert.data_age_min)}\n")

        print(f"  Total alerts: {len(alerts)}  |  Run at: {datetime.utcnow().isoformat()}")
        print("="*60 + "\n")

        # Save all alerts to JSON log
        self._save_alerts(alerts)
        return alerts

    def _save_alerts(self, alerts: list[Alert]):
        existing = []
        if os.path.exists(ALERTS_FILE):
            try:
                with open(ALERTS_FILE) as f:
                    existing = json.load(f)
            except Exception:
                pass
        existing.extend([a.to_dict() for a in alerts])
        with open(ALERTS_FILE, "w") as f:
            json.dump(existing, f, indent=2, default=str)
        log.info(f"Saved {len(alerts)} alerts to {ALERTS_FILE}")


# ════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="SahayakMap Intelligence Engine")
    parser.add_argument("--loop",     action="store_true", help="Run every 15 minutes")
    parser.add_argument("--interval", type=int, default=15, help="Loop interval in minutes")
    parser.add_argument("--rule",     type=str, help="Run single rule e.g. R1, R4, R7")
    args = parser.parse_args()

    engine = RulesEngine()

    if args.rule:
        rule_fn = getattr(engine, f"rule_{args.rule.upper()}_threshold_breach", None) or \
                  getattr(engine, f"rule_{args.rule.upper()}_rapid_rise", None)
        if rule_fn:
            rule_fn()
        else:
            print(f"Unknown rule: {args.rule}. Available: R1 R2 R3 R4 R5 R6 R7 R8")
    elif args.loop:
        log.info(f"Starting scheduler — every {args.interval} minutes")
        schedule.every(args.interval).minutes.do(engine.rajesh_briefing)
        engine.rajesh_briefing()  # run immediately
        while True:
            schedule.run_pending()
            time.sleep(30)
    else:
        engine.rajesh_briefing()


if __name__ == "__main__":
    main()
