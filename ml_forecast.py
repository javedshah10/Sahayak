"""
SahayakMap — ML Forecasting Module
====================================
Trains and runs Facebook Prophet models per station for WSE prediction.

Usage:
    python ml_forecast.py                          # train all stations
    python ml_forecast.py --station Naraj          # train single station
    python ml_forecast.py --predict Naraj          # predict +8/+24/+48hr
    python ml_forecast.py --retrain-stale          # only retrain if >30 days
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import pickle
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from prophet import Prophet
from prophet.serialize import model_to_dict, model_from_dict

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("SahayakMap.ML")

DATA_DIR = Path("data")
MODELS_DIR = Path("models")
MODELS_DIR.mkdir(parents=True, exist_ok=True)

STATIONS = [
    "Naraj", "Jenapur", "Anandpur", "Tikarpara", "Salebhata",
    "Kantamal", "Purusottampur", "Akhuapada", "Rengali Reservoir",
]

THRESHOLDS = {
    "Naraj":           {"warning": 25.41, "danger": 26.41, "hfl": 27.61},
    "Jenapur":         {"warning": 22.00, "danger": 23.00, "hfl": 24.78},
    "Anandpur":        {"warning": 37.44, "danger": 38.36, "hfl": 41.35},
    "Akhuapada":       {"warning": 17.83, "danger": 18.33, "hfl": 21.95},
    "Tikarpara":       {"warning": 91.00, "danger": 92.20, "hfl": None},
    "Kantamal":        {"warning": 79.00, "danger": 80.20, "hfl": None},
    "Salebhata":       {"warning": 49.40, "danger": 50.40, "hfl": None},
    "Purushottampur":  {"warning": 15.83, "danger": 16.83, "hfl": 19.65},
    "Rengali Reservoir": {"warning": None, "danger": None, "hfl": None},
}

# Fix 1-2-3: Tail quality, proxy fallback, variance guard
STALE_DAYS = 7
PROXY_MAP = {
    "Purusottampur": "Naraj",
    "Rengali Reservoir": "Jenapur",
    "Salebhata": "Naraj",
    "Kantamal": "Naraj",
    "Tikarpara": "Naraj",
}

def _tail_quality_check(df: pd.DataFrame) -> tuple:
    """Check if last 7 days of data is flat. Returns (is_flat, trimmed_df)."""
    if len(df) < 14:
        return False, df
    tail = df[df["ds"] >= df["ds"].max() - pd.Timedelta(days=STALE_DAYS)]
    if len(tail) < 3:
        return False, df
    std = tail["y"].std()
    is_flat = std < 0.05
    if is_flat:
        trimmed = df[df["ds"] < df["ds"].max() - pd.Timedelta(days=STALE_DAYS)]
        return True, trimmed if len(trimmed) >= 100 else df
    return False, df

def _load_fresh_csv(station: str) -> Optional[pd.DataFrame]:
    """Try local CSV first, then Supabase fallback for fresh data."""
    safe = station.lower().replace(" ", "_").replace("/", "-")
    path = DATA_DIR / f"{safe}_wse.csv"
    if path.exists():
        df = pd.read_csv(path, parse_dates=["timestamp"]).dropna(subset=["value","timestamp"]).sort_values("timestamp")
        if not df.empty:
            df = df.rename(columns={"timestamp":"ds","value":"y"})[["ds","y"]]
            df["ds"] = df["ds"].dt.tz_localize(None)
            return df
    try:
        import psycopg2, os
        from dotenv import load_dotenv
        load_dotenv()
        conn = psycopg2.connect(os.getenv("URI",""), connect_timeout=3)
        cur = conn.cursor()
        cur.execute(
            "SELECT g.timestamp,g.wse FROM gauge_readings g JOIN stations s ON s.id=g.station_id WHERE s.name=%s AND g.wse IS NOT NULL ORDER BY g.timestamp",
            [station])
        rows = cur.fetchall(); cur.close(); conn.close()
        if rows:
            df = pd.DataFrame(rows,columns=["ds","y"]); df["ds"] = pd.to_datetime(df["ds"])
            if df["ds"].dt.tz is not None: df["ds"] = df["ds"].dt.tz_localize(None)
            return df.sort_values("ds")
    except Exception: pass
    return None


def load_wse_data(station: str) -> Optional[pd.DataFrame]:
    """Load WSE data — CSV primary, Supabase fallback."""
    return _load_fresh_csv(station)


def train_model(station: str) -> Optional[Prophet]:
    """Train a Prophet model for a station."""
    df = load_wse_data(station)
    if df is None or len(df) < 100:
        log.warning("Insufficient data for %s (need >=100 rows)", station)
        return None

    log.info("Training %s on %d rows (%.2f years)", station, len(df),
             (df["ds"].max() - df["ds"].min()).days / 365.25)

    # Fix 1: Tail quality check — trim flat tail before training
    is_flat, df = _tail_quality_check(df)
    if is_flat:
        log.warning("WARN: %s tail flat — trimmed last %d days for retraining", station, STALE_DAYS)

    model = Prophet(
        yearly_seasonality=12,
        weekly_seasonality=False,
        daily_seasonality=False,
        changepoint_prior_scale=0.05,
        seasonality_prior_scale=10,
        interval_width=0.90,
    )
    model.add_seasonality(name="hourly_8hr", period=8 / 24, fourier_order=3)
    model.add_seasonality(name="yearly_monsoon", period=365.25, fourier_order=10)

    model.fit(df)

    safe = station.lower().replace(" ", "_").replace("/", "-")
    path = MODELS_DIR / f"{safe}_prophet.json"
    with open(path, "w") as f:
        json.dump({
            "model": model_to_dict(model),
            "station": station,
            "trained_at": datetime.utcnow().isoformat(),
            "rows": len(df),
            "date_range": [df["ds"].min().isoformat(), df["ds"].max().isoformat()],
            "tail_trimmed": is_flat,
        }, f)

    log.info("Model saved: %s", path)
    return model


def load_model(station: str) -> Optional[Tuple[Prophet, Dict[str, Any]]]:
    """Load a saved Prophet model with metadata."""
    safe = station.lower().replace(" ", "_").replace("/", "-")
    path = MODELS_DIR / f"{safe}_prophet.json"
    if not path.exists():
        return None

    with open(path) as f:
        data = json.load(f)

    model = model_from_dict(data["model"])
    return model, data


def model_age_days(station: str) -> Optional[float]:
    """How many days since this station's model was trained."""
    meta = load_model(station)
    if meta is None:
        return None
    _, data = meta
    trained = datetime.fromisoformat(data["trained_at"])
    return (datetime.utcnow() - trained).total_seconds() / 86400


def predict(station: str) -> Optional[Dict[str, Any]]:
    """Predict WSE at +8h/+24h/+48h with proxy fallback and variance guard."""
    result = load_model(station)
    if result is None:
        log.warning("No trained model for %s. Train first.", station)
        return None

    model, meta = result
    df = load_wse_data(station)
    tail_trimmed = meta.get("tail_trimmed", False)
    proxy_used = None
    low_confidence = False

    # Fix 2: Stale data proxy — use Tier 1 station's scaled forecast
    if df is None or df.empty or (df["ds"].max() < datetime.utcnow() - timedelta(days=STALE_DAYS)):
        proxy_station = PROXY_MAP.get(station)
        if proxy_station and proxy_station != station:
            proxy_result = load_model(proxy_station)
            proxy_df = load_wse_data(proxy_station)
            if proxy_result and proxy_df is not None and not proxy_df.empty:
                proxy_model, proxy_meta = proxy_result
                if proxy_df["ds"].max() >= datetime.utcnow() - timedelta(days=STALE_DAYS):
                    # Compute scale factor from historical means
                    s_mean = df["y"].mean() if df is not None and not df.empty else 1
                    p_mean = proxy_df["y"].mean() if not proxy_df.empty else 1
                    scale = s_mean / p_mean if p_mean > 0 else 1

                    proxy_last = proxy_df["ds"].max()
                    future = pd.DataFrame({"ds": [
                        proxy_last + timedelta(hours=h)
                        for h in range(8, 169, 8)
                    ]})
                    forecast = proxy_model.predict(future)
                    proxy_used = proxy_station
                    log.info("Using %s as proxy for %s (scale=%.3f)", proxy_station, station, scale)
                else:
                    low_confidence = True

    if proxy_used is None:
        if df is None or df.empty:
            return None
        last_date = df["ds"].max()
        future = pd.DataFrame({"ds": [
            last_date + timedelta(hours=h)
            for h in range(8, 169, 8)
        ]})
        forecast = model.predict(future)

    latest_actual = {"ds": str(df.iloc[-1]["ds"]) if not df.empty else "N/A",
                     "y": float(df.iloc[-1]["y"]) if not df.empty else 0}
    predictions = []
    forecast_curve = []
    detected_thresholds = []
    yhats = []
    f8h = f24h = f48h = None

    for hour_offset, (_, row) in enumerate(forecast.iterrows(), start=1):
        hour = hour_offset * 8
        val = round(float(row["yhat"]), 2)
        low = round(float(row["yhat_lower"]), 2)
        upp = round(float(row["yhat_upper"]), 2)
        if proxy_used:
            val = round(val * scale, 2)
            low = round(low * scale, 2)
            upp = round(upp * scale, 2)

        pred = {"timestamp": str(row["ds"]), "yhat": val, "yhat_lower": low, "yhat_upper": upp}
        predictions.append(pred)
        forecast_curve.append({"hour": hour, "wse": val, "lower": low, "upper": upp})
        yhats.append(val)

        # Backward compat keys
        if hour == 8:  f8h = val
        if hour == 24: f24h = val
        if hour == 48: f48h = val

        t = THRESHOLDS.get(station, {})
        if t.get("warning") and pred["yhat_upper"] >= t["warning"]:
            detected_thresholds.append({
                "threshold": "warning", "value": t["warning"],
                "prediction": pred["yhat_upper"], "timestamp": pred["timestamp"],
                "severity": "WARNING" if pred["yhat"] >= t["warning"] else "UPPER_BOUND_WARNING",
            })
        if t.get("danger") and pred["yhat_upper"] >= t["danger"]:
            detected_thresholds.append({
                "threshold": "danger", "value": t["danger"],
                "prediction": pred["yhat_upper"], "timestamp": pred["timestamp"],
                "severity": "DANGER" if pred["yhat"] >= t["danger"] else "UPPER_BOUND_DANGER",
            })

    # Fix 3: Forecast variance guard
    if len(yhats) >= 3 and np.std(yhats) < 0.05:
        low_confidence = True
        log.warning("WARN: %s forecast variance near-zero", station)

    return {
        "station": station,
        "trained_at": meta["trained_at"],
        "latest_actual": latest_actual,
        "predictions": predictions,
        "forecast": forecast_curve,
        "forecast_8h": f8h,
        "forecast_24h": f24h,
        "forecast_48h": f48h,
        "thresholds_detected": detected_thresholds,
        "confidence_interval": "90%",
        "tail_trimmed": tail_trimmed,
        "low_confidence": low_confidence,
        "proxy_used": proxy_used,
    }


def train_all(force: bool = False, max_age_days: int = 30):
    """Train or retrain models for all stations."""
    for station in STATIONS:
        if not force:
            age = model_age_days(station)
            if age is not None and age < max_age_days:
                log.info("Skipping %s (model is %.1f days old)", station, age)
                continue

        log.info("Training %s ...", station)
        try:
            train_model(station)
        except Exception as e:
            log.error("Failed to train %s: %s", station, e)

        time.sleep(1)


def main():
    parser = argparse.ArgumentParser(description="SahayakMap ML Forecasting")
    parser.add_argument("--station", type=str, help="Single station")
    parser.add_argument("--predict", type=str, help="Run prediction for station")
    parser.add_argument("--retrain-stale", action="store_true", help="Retrain models older than 30 days")
    parser.add_argument("--force", action="store_true", help="Force retrain all")
    args = parser.parse_args()

    if args.predict:
        result = predict(args.predict)
        if result:
            print(json.dumps(result, indent=2))
        return

    if args.station:
        train_model(args.station)
        return

    if args.retrain_stale:
        train_all(force=False, max_age_days=30)
        return

    train_all(force=args.force)


if __name__ == "__main__":
    main()
