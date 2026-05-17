"""
SahayakMap — Telegram Asset Tracking Bot
=========================================
Hybrid WSE-linked polling via Notifier (proxied Telegram routing).
Teams report location via inline keyboard.
Dead man's switch: no response in 30min during Danger → Priority 1 alert.

Usage:
    python telegram_bot.py              # daemon mode
    python telegram_bot.py --test-msg   # send test message and exit
    python telegram_bot.py --once       # check WSE state only
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import requests

_TG_DIR = str(Path(__file__).parent / "Telegram")
sys.path.insert(0, _TG_DIR)
from notifications import Notifier
from config_loader import NotificationSettings

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("SahayakMap.Telegram")

STATE_FILE = Path("telegram_state.json")
VPS_STATIONS_URL = "https://www.joodei.org/sahayak-data/data/stations"
CHAT_ID = str(os.getenv("chat_id", ""))

LAST_UPDATE_ID = 0
notifier: Optional[Notifier] = None

TEAMS = {
    "ALPHA":  {"leader": "Rajesh",  "district": "Cuttack"},
    "BRAVO":  {"leader": "Amit",    "district": "Jajpur"},
    "CHARLIE":{"leader": "Deepak",  "district": "Kendrapara"},
}


def state() -> dict:
    return json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {}

def save(s: dict):
    STATE_FILE.write_text(json.dumps(s, indent=2, default=str))


def get_wse_state() -> str:
    try:
        r = requests.get(VPS_STATIONS_URL, timeout=10)
        stations = r.json()
    except Exception:
        log.warning("VPS unreachable — assuming NORMAL")
        return "NORMAL"
    worst = "NORMAL"
    for s in stations:
        wse = s.get("latest_wse")
        if wse is None: continue
        warn, dang = s.get("warning_level"), s.get("danger_level")
        if warn is None: continue
        if dang and wse >= dang: return "DANGER"
        if wse >= warn and worst != "DANGER": worst = "WARNING"
    return worst


def send(text: str) -> bool:
    """Send a message via Notifier (handles proxy routing)."""
    if not notifier: return False
    return notifier.info(text)


def poll(poll_text: str):
    """Send a poll to teams with status keyboard instructions."""
    global LAST_UPDATE_ID
    if not send(poll_text):
        log.warning("Poll not sent — Telegram not configured")

    s = state()
    s["last_poll_sent_at"] = datetime.utcnow().isoformat()
    save(s)
    LAST_UPDATE_ID = notifier.latest_update_id() if notifier else 0


def check_responses():
    """Read Telegram updates to capture team replies (safe/loc/sos)."""
    global LAST_UPDATE_ID
    if not notifier: return
    s = state()

    updates = notifier.fetch_updates(offset=LAST_UPDATE_ID + 1, timeout=15, limit=50)
    for u in updates:
        uid = u.get("update_id", 0)
        if uid <= LAST_UPDATE_ID: continue
        LAST_UPDATE_ID = max(LAST_UPDATE_ID, uid)
        msg = u.get("message") or u.get("edited_message") or {}
        text = (msg.get("text") or "").strip().lower()
        chat = str(msg.get("chat", {}).get("id", ""))
        if chat != CHAT_ID: continue

        user = (msg.get("from") or {}).get("first_name", "user")
        location = msg.get("location")

        # Match user to team
        team = None
        for t, info in TEAMS.items():
            if info["leader"].lower() in user.lower():
                team = t
                break
        if not team:
            team = user

        # GPS coordinates from text like "20.47,85.93"
        coord_match = re.match(r"^\s*([\d.-]+)\s*[,;]\s*([\d.-]+)\s*$", text)
        if coord_match:
            lat, lon = coord_match.groups()
            s.setdefault("responses", {})[team] = {"status": "located", "location": f"{lat},{lon}", "time": datetime.utcnow().isoformat()}
            save(s)
            log.info("%s location: %s,%s", team, lat, lon)
        elif location:
            lat, lon = location.latitude, location.longitude
            s.setdefault("responses", {})[team] = {"status": "located", "location": f"{lat:.4f},{lon:.4f}", "time": datetime.utcnow().isoformat()}
            save(s)
            log.info("%s GPS: %.4f,%.4f", team, lat, lon)
        elif "safe" in text:
            s.setdefault("responses", {})[team] = {"status": "safe", "time": datetime.utcnow().isoformat()}
            save(s)
            log.info("%s ALL SAFE", team)
        elif "sos" in text or "help" in text or "need support" in text:
            s.setdefault("responses", {})[team] = {"status": "sos", "time": datetime.utcnow().isoformat()}
            save(s)
            log.warning("SOS from %s", team)
            send(f"🔴 SOS ALERT: Team {team} requesting support at {TEAMS.get(team,{}).get('district','?')}.")
        elif "loc" in text or "share" in text or "location" in text:
            send(f"📍 {team} — Send your GPS coordinates (e.g. 20.47,85.93) or tap location share on your phone.")


def run():
    global notifier, LAST_UPDATE_ID
    cfg = NotificationSettings()
    notifier = Notifier(cfg)

    if not notifier.enabled:
        log.warning("Telegram not configured — set bot_token + chat_id in Telegram/.env")
        return

    LAST_UPDATE_ID = notifier.latest_update_id()
    log.info("Bot ready | route: %s | last_update: %s", notifier.route_label, LAST_UPDATE_ID)
    send("✅ SahayakMap bot online. WSE state: " + get_wse_state())

    while True:
        try:
            ws = get_wse_state()
            s = state()
            now = datetime.utcnow()

            if ws == "DANGER":
                last = s.get("last_poll_sent_at")
                if not last or (now - datetime.fromisoformat(last)) > timedelta(hours=2):
                    poll(f"🚨 DANGER — All teams report status NOW:\n📍 Share GPS | ✅ Safe | 🆘 SOS")
                # Dead man's check
                if last and s.get("last_poll_state") == "DANGER":
                    elapsed = (now - datetime.fromisoformat(last)).total_seconds()
                    if elapsed > 1800:
                        for t in TEAMS:
                            resp = s.get("responses", {})
                            if t not in resp or resp[t].get("status") != "safe":
                                loc = resp.get(t, {}).get("location", "unknown")
                                send(f"🔇 TEAM DARK: {t} not responding. Last: {loc}. Elapsed: {elapsed//60:.0f}min.")
                                log.warning("DEAD MAN: %s dark %.0f min", t, elapsed / 60)
                s["last_poll_state"] = "DANGER"
                save(s)
                check_responses()
                time.sleep(300)

            elif ws == "WARNING":
                last = s.get("last_poll_sent_at")
                if not last or (now - datetime.fromisoformat(last)) > timedelta(hours=6):
                    poll(f"⚠️ WARNING — Report status:\n📍 Share GPS | ✅ Safe | 🆘 SOS")
                    s["last_poll_state"] = "WARNING"
                    save(s)
                check_responses()
                time.sleep(600)

            else:
                check_responses()
                time.sleep(900)

        except KeyboardInterrupt:
            log.info("Shutdown")
            break
        except Exception as e:
            log.error("Loop error: %s", e)
            time.sleep(60)


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--once", action="store_true")
    p.add_argument("--test-msg", action="store_true")
    p.add_argument("--force", action="store_true")
    args = p.parse_args()

    cfg = NotificationSettings()
    notifier = Notifier(cfg)

    if args.once:
        log.info("WSE State: %s | Route: %s", get_wse_state(), notifier.route_label if notifier else "none")
    elif args.test_msg:
        ok = send("🧪 SahayakMap test message. All systems operational.")
        log.info("Test msg sent: %s | Route: %s", ok, notifier.route_label if notifier else "none")
    else:
        run()
