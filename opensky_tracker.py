import json
import os
import time
from datetime import datetime, timedelta, timezone

import requests


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(BASE_DIR, ".env")
SUPABASE_ENV_PATHS = [
    os.path.join(BASE_DIR, "Supabase", ".env"),
    os.path.join(os.path.dirname(BASE_DIR), "Supabase", ".env"),
]
FIXTURES_DIR = os.path.join(BASE_DIR, "fixtures")
OUTPUT_PATH = os.path.join(FIXTURES_DIR, "aircraft_positions.json")
COOLDOWN_PATH = os.path.join(FIXTURES_DIR, "tracker_cooldown.json")
OPENSKY_URL = "https://opensky-network.org/api/states/all"
BBOX = {
    "lamin": 19.3,
    "lamax": 21.7,
    "lomin": 83.3,
    "lomax": 86.7,
}
MAX_POLL_AGE = timedelta(seconds=90)
REQUEST_TIMEOUT = 30
COOLDOWN_STEPS = [timedelta(minutes=5), timedelta(minutes=15), timedelta(hours=1), timedelta(hours=6)]
COOLDOWN_MAX = timedelta(hours=6)


def load_env_file(path):
    values = {}
    if not os.path.exists(path):
        return values

    with open(path, "r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip("\"'").strip()
    return values


def get_credentials():
    env_values = load_env_file(ENV_PATH)
    username = (
        os.getenv("OPENSKY_USER")
        or os.getenv("OPENSKY_CLIENT_ID")
        or env_values.get("OPENSKY_USER")
        or env_values.get("OPENSKY_CLIENT_ID")
        or env_values.get("clientId")
    )
    password = (
        os.getenv("OPENSKY_PASS")
        or os.getenv("OPENSKY_CLIENT_SECRET")
        or env_values.get("OPENSKY_PASS")
        or env_values.get("OPENSKY_CLIENT_SECRET")
        or env_values.get("clientSecret")
    )
    if not username or not password:
        raise RuntimeError("Missing OpenSky credentials in .env or environment")
    return username, password


def get_supabase_config():
    env_values = {}
    for path in SUPABASE_ENV_PATHS:
        env_values.update(load_env_file(path))

    url = os.getenv("SUPABASE_URL") or env_values.get("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY") or env_values.get("SUPABASE_KEY")
    if not url or not key:
        raise RuntimeError("Missing Supabase credentials in .env")
    return url, key


def read_existing_payload():
    if not os.path.exists(OUTPUT_PATH):
        return None
    with open(OUTPUT_PATH, "r", encoding="utf-8") as handle:
        return json.load(handle)


def is_recent(payload, max_age):
    if not payload or "fetched_at" not in payload:
        return False
    try:
        fetched_at = datetime.fromisoformat(payload["fetched_at"].replace("Z", "+00:00"))
    except ValueError:
        return False
    return datetime.now(timezone.utc) - fetched_at < max_age


def to_iso_timestamp(unix_ts):
    if unix_ts is None:
        return ""
    return datetime.fromtimestamp(unix_ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def kmh_from_mps(value):
    if value is None:
        return None
    return round(value * 3.6, 2)


def normalize_state_vector(state):
    lat = state[6]
    lon = state[5]
    if lat is None or lon is None:
        return None

    callsign = (state[1] or "").strip()
    return {
        "icao24": state[0],
        "callsign": callsign,
        "lat": lat,
        "lon": lon,
        "altitude_m": state[13],
        "velocity_kmh": kmh_from_mps(state[9]),
        "heading": state[10],
        "on_ground": bool(state[8]),
        "last_contact": to_iso_timestamp(state[4]),
    }


def read_cooldown() -> datetime | None:
    """Return datetime until which fetching should be skipped, or None."""
    if not os.path.exists(COOLDOWN_PATH):
        return None
    try:
        with open(COOLDOWN_PATH, "r") as f:
            data = json.load(f)
        return datetime.fromisoformat(data["until"])
    except Exception:
        return None


def write_cooldown(until: datetime, consecutive_failures: int) -> None:
    os.makedirs(FIXTURES_DIR, exist_ok=True)
    with open(COOLDOWN_PATH, "w") as f:
        json.dump({"until": until.isoformat(), "failures": consecutive_failures}, f)


def fetch_states(username, password):
    params = dict(BBOX)
    backoff_seconds = 1
    last_error = None

    for attempt in range(1, 4):
        try:
            response = requests.get(
                OPENSKY_URL,
                params=params,
                auth=(username, password),
                timeout=REQUEST_TIMEOUT,
            )
            if response.status_code == 429:
                last_error = f"429 Too Many Requests"
                raise requests.HTTPError("429 Too Many Requests", response=response)
            response.raise_for_status()
            return response.json()
        except requests.HTTPError as exc:
            last_error = exc
            # 429 — do not retry, set cooldown immediately
            if getattr(exc, "response", None) is not None and exc.response.status_code == 429:
                break
            if attempt == 3:
                break
            time.sleep(backoff_seconds)
            backoff_seconds *= 2
        except Exception as exc:
            last_error = exc
            if attempt == 3:
                break
            time.sleep(backoff_seconds)
            backoff_seconds *= 2

    raise RuntimeError(f"OpenSky request failed after {attempt} attempt(s): {last_error}")


def build_payload():
    username, password = get_credentials()
    response_payload = fetch_states(username, password)
    aircraft = []

    for state in response_payload.get("states") or []:
        normalized = normalize_state_vector(state)
        if normalized is not None:
            aircraft.append(normalized)

    fetched_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    payload = {
        "fetched_at": fetched_at,
        "bbox": dict(BBOX),
        "count": len(aircraft),
        "aircraft": aircraft,
    }

    if not aircraft:
        print("No aircraft in zone")

    return payload


def save_payload(payload):
    os.makedirs(FIXTURES_DIR, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)


def save_to_supabase(aircraft_list, fetched_at):
    if not aircraft_list:
        return

    try:
        from supabase import create_client

        supabase_url, supabase_key = get_supabase_config()
        client = create_client(supabase_url, supabase_key)
        rows = []
        for aircraft in aircraft_list:
            rows.append({
                "icao24": aircraft.get("icao24"),
                "callsign": aircraft.get("callsign"),
                "lat": aircraft.get("lat"),
                "lon": aircraft.get("lon"),
                "altitude_m": aircraft.get("altitude_m"),
                "velocity_kmh": aircraft.get("velocity_kmh"),
                "heading": aircraft.get("heading"),
                "on_ground": aircraft.get("on_ground"),
                "last_contact": aircraft.get("last_contact") or None,
                "fetched_at": fetched_at,
            })

        client.table("aircraft_positions").insert(rows).execute()
        print(f"Inserted {len(rows)} aircraft rows into Supabase")
    except Exception as exc:
        print(f"Supabase insert failed: {exc}")


def main():
    # Check cooldown before attempting fetch
    cooldown_until = read_cooldown()
    now = datetime.now(timezone.utc)
    if cooldown_until and now < cooldown_until:
        remaining = int((cooldown_until - now).total_seconds())
        print(f"Skipping fetch: rate-limit cooldown active for {remaining}s")
        return

    existing_payload = read_existing_payload()
    if is_recent(existing_payload, MAX_POLL_AGE):
        print("Skipping fetch: cached aircraft data is newer than 90 seconds")
        return

    try:
        payload = build_payload()
    except RuntimeError as exc:
        msg = str(exc)
        if "429" in msg or "Too Many Requests" in msg:
            # Escalating cooldown on 429
            current = read_cooldown()
            failures = 0
            if current:
                try:
                    with open(COOLDOWN_PATH, "r") as f:
                        data = json.load(f)
                    failures = data.get("failures", 0)
                except Exception:
                    pass
            failures += 1
            step = min(failures - 1, len(COOLDOWN_STEPS) - 1)
            delay = COOLDOWN_STEPS[step]
            until = now + delay
            write_cooldown(until, failures)
            print(f"Rate-limited by OpenSky (429). Cooldown until {until.isoformat()} (failure #{failures}, delay {delay})")
        else:
            print(f"Fetch failed: {exc}")
        return

    save_payload(payload)
    save_to_supabase(payload["aircraft"], payload["fetched_at"])
    # Clear cooldown on success
    if os.path.exists(COOLDOWN_PATH):
        os.remove(COOLDOWN_PATH)
    print(f"Saved {payload['count']} aircraft to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
