"""
SahayakMap — Geocoded Social Signal Agent v2
==============================================
Token-saving pipeline with gauge/IMD validation,
fake post detection, LLM classification, and full audit trail.

Usage:
    python social_agent.py --once       # single run
    python social_agent.py --loop       # daemon (15 min intervals)
    python social_agent.py --test       # verify config
"""

import hashlib, json, logging, os, re, time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import psycopg2
import requests
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("URI", "")
GROQ_API = os.getenv("GROQ_API", "")
OPENROUTER_KEY = os.getenv("OPENROUTER_API_KEY", "")
TWITTER_BEARER = os.getenv("TWITTER_BEARER_TOKEN", "")
LLM_PROVIDERS = [
    {
        "name": "meta-llama/llama-4-scout-17b-16e-instruct",
        "url": "https://api.groq.com/openai/v1/chat/completions",
        "headers": lambda: {"Authorization": f"Bearer {GROQ_API}"},
        "enabled": lambda: bool(GROQ_API),
    },
    {
        "name": "llama-3.3-70b-versatile",
        "url": "https://api.groq.com/openai/v1/chat/completions",
        "headers": lambda: {"Authorization": f"Bearer {GROQ_API}"},
        "enabled": lambda: bool(GROQ_API),
    },
    {
        "name": "mistralai/mistral-7b-instruct",
        "url": "https://openrouter.ai/api/v1/chat/completions",
        "headers": lambda: {"Authorization": f"Bearer {OPENROUTER_KEY}"},
        "enabled": lambda: bool(OPENROUTER_KEY),
    },
    {
        "name": "meta-llama/llama-3-8b-instruct",
        "url": "https://openrouter.ai/api/v1/chat/completions",
        "headers": lambda: {"Authorization": f"Bearer {OPENROUTER_KEY}"},
        "enabled": lambda: bool(OPENROUTER_KEY),
    },
]

EXTRACT_SYSTEM_PROMPT = "Disaster intelligence parser for Odisha flood ops. Message may be in Odia, Hindi, Bengali or English — translate internally. If the message has no clear connection to Odisha flood operations, return severity=1 and reliability=1. Return JSON only: {location:string|null,coordinates:[lat,lon]|null,severity:1-5,event_type:string,station_proximity:string|null,summary:string(max 15 words),reliability_score:1-5,credibility_flags:[string],language_detected:string}"
CLASSIFY_SYSTEM_PROMPT = "Classify this flood signal for EOC log. Return JSON only: {category:'infrastructure'|'rescue'|'evacuation'|'road_closure'|'bridge'|'social_unrest'|'other',priority:'P1_critical'|'P2_high'|'P3_medium'|'P4_low',action_required:string(max 10 words),assigned_to:'Rajesh'|'EOC'|'district_collector'|'monitor'}"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("SahayakMap.Social.v2")

ODISHA_BBOX = (19.3, 21.7, 83.3, 86.7)

STATION_QUERIES = [
    ("NAR", "", "submerged OR breach OR trapped OR Mundali OR Mahanadi OR Cuttack -is:retweet lang:en"),
    ("JEN", "", "Jenapur OR NH16 OR bridge OR rising OR Jajpur flood -is:retweet lang:en"),
    ("ANA", "", "Baitarani OR Anandpur OR Keonjhar flood OR trapped -is:retweet lang:en"),
    ("AKH", "", "Akhuapada OR Bhadrak flood OR stranded OR embankment -is:retweet lang:en"),
    ("TIK", "", "Tikarpara OR Angul flood OR submerged OR overflow -is:retweet lang:en"),
    ("KAN", "", "Kantamal OR Boudh breach OR flood OR rising -is:retweet lang:en"),
    ("SAL", "", "Salebhata OR Bargarh submerged OR embankment -is:retweet lang:en"),
    ("PUR", "", "Purusottampur OR Ganjam OR Rushikulya flood OR stranded -is:retweet lang:en"),
    ("REN", "", "Rengali OR reservoir OR breach OR Angul flood -is:retweet lang:en"),
]

KEYWORDS = [
    "submerged","breach","stuck","rescue","flood","trapped","washed out",
    "overflow","stranded","NH-16","SH-42","SH-24","Naraj","Jenapur",
    "Anandpur","Akhuapada","Tikarpara","Kantamal","Salebhata",
    "Purusottampur","Mahanadi","Brahmani","Baitarani","Cuttack",
    "Jajpur","Bhadrak","Keonjhar","Angul","Boudh","Bargarh","Ganjam"
]

ODISHA_ANCHORS = [
    "odisha", "odia", "mahanadi", "brahmani", "baitarani",
    "cuttack", "bhubaneswar", "jajpur", "bhadrak", "angul",
    "boudh", "bargarh", "ganjam", "keonjhar", "jenapur",
    "naraj", "akhuapada", "tikarpara", "kantamal",
    "salebhata", "purusottampur", "rengali", "ndrf odisha",
    "odisha flood", "odisha rescue", "rushikulya", "anandpur",
    "nh16", "rengali reservoir"
]

ALLOWED_LANGUAGES = {"en", "hi", "or", "bn", "te"}

STATION_TO_DISTRICT = {
    "NAR": "Cuttack",
    "JEN": "Jajpur",
    "ANA": "Keonjhar",
    "AKH": "Bhadrak",
    "TIK": "Angul",
    "KAN": "Boudh",
    "SAL": "Bargarh",
    "PUR": "Ganjam",
    "REN": "Angul",
}

KNOWN_STATION_CODES = set(STATION_TO_DISTRICT.keys())
ODISHA_SPECIFIC = ODISHA_ANCHORS
INDIA_FLOOD_TERMS = ["india", "indian"]
FLOOD_KEYWORDS = [k.lower() for k in KEYWORDS]


def get_db():
    return psycopg2.connect(DATABASE_URL, connect_timeout=3)


def hash_text(s): return hashlib.sha256(s.encode()).hexdigest()[:16]


# ═══════════ DEDUP ═══════════════════════════════════
def tweet_exists(tweet_id: str) -> bool:
    try:
        conn=get_db(); cur=conn.cursor()
        cur.execute("SELECT id FROM social_signals WHERE tweet_id=%s", [tweet_id])
        r=cur.fetchone(); cur.close(); conn.close()
        return r is not None
    except: return False


def tweet_recent_dup(text: str) -> bool:
    try:
        conn=get_db(); cur=conn.cursor()
        cur.execute("SELECT id FROM social_signals WHERE content_hash=%s AND fetched_at > NOW() - INTERVAL '2 hours'", [hash_text(text)])
        r=cur.fetchone(); cur.close(); conn.close()
        return r is not None
    except: return False


# ═══════════ KEYWORD GATE ════════════════════════════
def keyword_match(text: str or None) -> bool:
    if not text: return False
    txt=text.lower()
    if "forest fire" in txt: return False
    return any(k.lower() in txt for k in KEYWORDS)


def passes_anchor(text: str or None, station_code: str) -> bool:
    if station_code in KNOWN_STATION_CODES:
        return True
    if not text:
        return False
    t = text.lower()
    if any(anchor in t for anchor in ODISHA_SPECIFIC):
        return True
    if any(india_term in t for india_term in INDIA_FLOOD_TERMS):
        if any(flood_keyword in t for flood_keyword in FLOOD_KEYWORDS):
            return True
    return False


def has_allowed_language(tweet: Dict) -> bool:
    lang = (tweet.get("lang") or "").lower()
    return lang in ALLOWED_LANGUAGES


# ═══════════ TWITTER FETCH ═══════════════════════════
def fetch_tweets_for_station(code: str, coords: str, query: str) -> List[Dict]:
    """Fetch tweets using X v2-compatible keyword queries."""
    if not TWITTER_BEARER:
        return _dummy_tweets(code, query)

    try:
        resp = requests.get(
            "https://api.twitter.com/2/tweets/search/recent",
            headers={"Authorization": f"Bearer {TWITTER_BEARER}"},
            params={
                "query": query,
                "tweet.fields": "created_at,author_id,lang,geo,public_metrics",
                "user.fields": "created_at",
                "expansions": "author_id,geo.place_id",
                "max_results": 10
            },
            timeout=15
        )
        if resp.status_code != 200:
            log.warning("Twitter API non-200 for %s: %s %s", code, resp.status_code, resp.text[:300])
            return []
        tweets = resp.json().get("data", [])
        log.info("Twitter API %s: %d tweets", code, len(tweets))
        return tweets
    except Exception as e:
        log.warning("Twitter fetch failed for %s: %s", code, e)
        return _dummy_tweets(code, query)


def _dummy_tweets(code: str, query: str) -> List[Dict]:
    """Dummy tweets for testing (uses local fixtures)."""
    path = Path("fixtures/dummy_twitter.json")
    if not path.exists(): return []
    try:
        all_tweets = json.loads(path.read_text())
        return [{"id": t.get("id",""), "text": t.get("text",""), "created_at": t.get("timestamp",""),
                 "author_id": t.get("id","")[:5], "lang": "en"} for t in all_tweets[:3]]
    except: return []


# ═══════════ CLUSTER CHECK ═══════════════════════════
def count_cluster_tweets(station_coords: str, hours: int = 2) -> int:
    """Count tweets within same station bbox (10km) in last N hours."""
    try:
        conn=get_db(); cur=conn.cursor()
        cur.execute("""SELECT COUNT(*) FROM social_signals
            WHERE station_proximity=%s AND fetched_at > NOW() - INTERVAL '%s hours'""",
            [station_coords, str(hours)])
        n=cur.fetchone()[0]; cur.close(); conn.close()
        return n
    except: return 0


# ═══════════ LLM CALLS ═══════════════════════════════
_SOCIAL_SIGNAL_COLUMNS = None


def get_social_signal_columns() -> set:
    global _SOCIAL_SIGNAL_COLUMNS
    if _SOCIAL_SIGNAL_COLUMNS is not None:
        return _SOCIAL_SIGNAL_COLUMNS
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'social_signals'
        """)
        _SOCIAL_SIGNAL_COLUMNS = {r[0] for r in cur.fetchall()}
        cur.close()
        conn.close()
    except Exception:
        _SOCIAL_SIGNAL_COLUMNS = set()
    return _SOCIAL_SIGNAL_COLUMNS


def post_json_llm(provider: Dict, system_prompt: str, user_content: str, max_tokens: int) -> Dict:
    payload = {
        "model": provider["name"],
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        "temperature": 0.1,
        "max_tokens": max_tokens,
    }
    return requests.post(
        provider["url"],
        headers=provider["headers"](),
        json=payload,
        timeout=15,
    )


def extract_json_content(resp: requests.Response, model_name: str) -> Dict:
    resp.raise_for_status()
    raw = resp.json()["choices"][0]["message"]["content"]
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            return json.loads(match.group())
        raise ValueError(f"no JSON content from model {model_name}")


def keyword_fallback_extract(text: str) -> Dict:
    extract = _local_extract(text)
    score = sum(1 for keyword in KEYWORDS if keyword.lower() in text.lower())
    extract["severity"] = max(1, min(5, score or 1))
    return extract


def call_llm_extract(text: str) -> Tuple[Dict, str, str]:
    """Structured extraction with Groq/OpenRouter rotation and keyword fallback."""
    last_error = None
    for provider in LLM_PROVIDERS:
        if not provider["enabled"]():
            continue
        for attempt in range(3):
            try:
                resp = post_json_llm(provider, EXTRACT_SYSTEM_PROMPT, text, 300)
                return extract_json_content(resp, provider["name"]), provider["name"], "extracted"
            except ValueError as e:
                last_error = e
                log.warning("LLM extract empty/no-JSON on %s", provider["name"])
                break
            except requests.HTTPError as e:
                last_error = e
                status = e.response.status_code if e.response is not None else None
                if status == 429:
                    log.warning("LLM extract rate-limited on %s", provider["name"])
                    break
                if status in (500, 503) and attempt < 2:
                    log.warning("LLM extract retry on %s: %s", provider["name"], e)
                    time.sleep(2 ** attempt)
                    continue
                log.warning("LLM extract failed on %s: %s", provider["name"], e)
                break
            except Exception as e:
                last_error = e
                log.warning("LLM extract failed on %s: %s", provider["name"], e)
                break
        time.sleep(2)
    if last_error:
        log.warning("LLM extract exhausted all models: %s", last_error)
    return keyword_fallback_extract(text), "keyword_fallback", "keyword_fallback"


def call_llm_classify(extract: Dict) -> Tuple[Dict, Optional[str]]:
    """Classification with the same provider rotation; no keyword fallback."""
    last_error = None
    for provider in LLM_PROVIDERS:
        if not provider["enabled"]():
            continue
        for attempt in range(3):
            try:
                resp = post_json_llm(provider, CLASSIFY_SYSTEM_PROMPT, json.dumps(extract), 200)
                return extract_json_content(resp, provider["name"]), provider["name"]
            except ValueError as e:
                last_error = e
                log.warning("LLM classify empty/no-JSON on %s", provider["name"])
                break
            except requests.HTTPError as e:
                last_error = e
                status = e.response.status_code if e.response is not None else None
                if status == 429:
                    log.warning("LLM classify rate-limited on %s", provider["name"])
                    break
                if status in (500, 503) and attempt < 2:
                    log.warning("LLM classify retry on %s: %s", provider["name"], e)
                    time.sleep(2 ** attempt)
                    continue
                log.warning("LLM classify failed on %s: %s", provider["name"], e)
                break
            except Exception as e:
                last_error = e
                log.warning("LLM classify failed on %s: %s", provider["name"], e)
                break
        time.sleep(2)
    if last_error:
        log.warning("LLM classify exhausted all models: %s", last_error)
    return {}, None


def _local_extract(text: str) -> Dict:
    lower = text.lower()
    station = None
    for s in ["Naraj","Jenapur","Anandpur","Akhuapada","Tikarpara","Kantamal","Salebhata","Purusottampur","Rengali Reservoir"]:
        if s.lower() in lower: station = s; break
    sev = 4 if any(w in lower for w in ["trapped","stranded","rescue","breach"]) else 3 if any(w in lower for w in ["submerged","flooded","overflow"]) else 2
    return {"location":station or "Odisha","coordinates":None,"severity":sev,"event_type":"flood","station_proximity":station,"summary":text[:80],"reliability_score":2,"credibility_flags":["single_source"],"language_detected":"unknown"}


# ═══════════ VALIDATION ══════════════════════════════
def validate_against_gauge(extract: Dict) -> Dict:
    """Check if severity contradicts actual WSE data."""
    if extract.get("severity",0) < 4: return extract
    station = extract.get("station_proximity")
    if not station: return extract
    try:
        conn=get_db(); cur=conn.cursor()
        cur.execute("""SELECT g.wse, s.warning_level FROM gauge_readings g
            JOIN stations s ON s.id=g.station_id WHERE s.name=%s
            ORDER BY g.timestamp DESC LIMIT 1""", [station])
        r=cur.fetchone(); cur.close(); conn.close()
        if r and r[1] and r[0] < r[1]:
            extract.setdefault("credibility_flags",[]).append("contradicts_gauge")
            extract["reliability_score"] = max(1, extract.get("reliability_score",2)-1)
    except: pass
    return extract


def validate_against_imd(extract: Dict) -> Dict:
    """Check IMD nowcast for station. Boost/demote accordingly."""
    if extract.get("severity",0) < 4: return extract
    station = extract.get("station_proximity")
    if not station: return extract
    try:
        feeds = requests.get("https://www.joodei.org/api/feeds", timeout=10).json()
        for s in feeds.get("imd",{}).get("stations",[]):
            if s.get("name") == station and s.get("wms_color",1) < 3:
                extract.setdefault("credibility_flags",[]).append("no_imd_support")
                extract["reliability_score"] = max(1, extract.get("reliability_score",2)-1)
                break
    except: pass
    return extract


def validate_coordinates(extract: Dict) -> Dict:
    """Check if coordinates are within Odisha bbox."""
    coords = extract.get("coordinates")
    if not coords or not isinstance(coords, list) or len(coords)<2:
        return extract
    lat, lon = coords[0], coords[1]
    if lat is None or lon is None: return extract
    if lat < 19.3 or lat > 21.7 or lon < 83.3 or lon > 86.7:
        extract.setdefault("credibility_flags",[]).append("implausible_location")
        extract["reliability_score"] = max(1, extract.get("reliability_score",2)-1)
    return extract


# ═══════════ VERIFIED CRISIS ═══════════════════════════════
def check_verified_crisis(extract: Dict, station_code: str, imd_wms: int) -> bool:
    severity = extract.get("severity", 0)
    reliability = extract.get("reliability_score", 2)
    contradicts_gauge = "contradicts_gauge" in extract.get("credibility_flags", [])
    if contradicts_gauge:
        return False
    if imd_wms >= 3:
        return severity >= 3 and reliability >= 3
    if imd_wms == 2:
        return severity >= 4 and reliability >= 4
    return False


# ═══════════ INSERT ══════════════════════════════════
def insert_signal(source: str, tweet: Dict, extract: Dict, station_code: str,
                  processing_status: str, skip_reason: str = None,
                  classification: Dict = None, is_verified: bool = False,
                  llm_model_used: str = "keyword_fallback"):
    try:
        conn=get_db(); cur=conn.cursor()
        district = STATION_TO_DISTRICT.get(station_code, "Odisha")
        if station_code not in STATION_TO_DISTRICT:
            logging.error(f"No district mapped for {station_code} — defaulting to Odisha")
        text = (tweet.get("text") or tweet.get("full_text") or "").strip()
        if not text:
            text = f"[No text — station: {station_code}]"
        insert_data = {
            "text": text,
            "raw_text": text,
        }
        coords = extract.get("coordinates")
        la, lo = (coords[0],coords[1]) if isinstance(coords,list) and len(coords)>=2 else (None,None)
        columns = get_social_signal_columns()
        include_llm_model = "llm_model_used" in columns
        insert_columns = [
            "source","platform","district","tweet_id","text","raw_text","location","coordinates","severity",
            "event_type","station_proximity","summary","reliability_score",
            "credibility_flags","verified","content_hash","fetched_at","timestamp",
            "coordinates_source","language_detected","category","priority",
            "action_required","assigned_to","processed_at","processing_status","skip_reason"
        ]
        values_sql = [
            "%s","%s","%s","%s","%s","%s","%s","point(%s,%s)","%s",
            "%s","%s","%s","%s",
            "%s","%s","%s","NOW()","%s",
            "%s","%s","%s","%s",
            "%s","%s","NOW()","%s","%s"
        ]
        params = [
            source, "twitter", district, tweet.get("id",""), insert_data["text"], insert_data["raw_text"],
            extract.get("location"), la, lo,
            extract.get("severity",2), extract.get("event_type","flood"),
            extract.get("station_proximity"), extract.get("summary",""),
            extract.get("reliability_score",2),
            json.dumps(extract.get("credibility_flags",[])),
            is_verified, hash_text(text),
            tweet.get("created_at", datetime.now(timezone.utc).isoformat()),
            extract.get("coordinates_source","unknown"),
            extract.get("language_detected","unknown"),
            classification.get("category") if classification else None,
            classification.get("priority") if classification else None,
            classification.get("action_required") if classification else None,
            classification.get("assigned_to") if classification else None,
            processing_status, skip_reason
        ]
        if include_llm_model:
            insert_columns.append("llm_model_used")
            values_sql.append("%s")
            params.append(llm_model_used)
        cur.execute(
            f"""INSERT INTO social_signals
            ({",".join(insert_columns)})
            VALUES({",".join(values_sql)})""",
            params
        )
        conn.commit()
        rowid = cur.fetchone()[0] if cur.description else None
        cur.close(); conn.close()
        if is_verified: log.info("VERIFIED: %s | %s", station_code, extract.get("summary","")[:50])
        return rowid
    except Exception as e:
        log.error("Insert failed: %s", e)


def log_skipped(tweet_id: str, reason: str):
    """Log skipped tweet for audit trail."""
    try:
        conn=get_db(); cur=conn.cursor()
        cur.execute("""INSERT INTO social_signals
            (source,platform,district,tweet_id,raw_text,severity,fetched_at,timestamp,processing_status,skip_reason,content_hash)
            VALUES('twitter','twitter','Odisha',%s,%s,0,NOW(),NOW(),'skipped',%s,%s)""",
            [tweet_id, "", reason, hash_text(tweet_id)])
        conn.commit(); cur.close(); conn.close()
    except: pass


# ═══════════ MAIN LOOP ═══════════════════════════════
def run():
    total_processed = 0
    total_skipped = 0

    for station_code, coords, query in STATION_QUERIES:
        log.info("Scanning %s: %s", station_code, query[:60])
        tweets = fetch_tweets_for_station(station_code, coords, query)

        for tweet in tweets[:5]:  # max 5 per station
            tid = tweet.get("id","")
            tweet_text = tweet.get("text") or tweet.get("full_text")

            if tweet_text is None or not tweet_text.strip():
                logging.warning(f"Skipping tweet {tweet.get('id')} - no text")
                log_skipped(tweet.get("id"), "empty_text")
                total_skipped += 1; continue

            # Step 1: Dedup
            if tweet_exists(tid):
                logging.info(f"SKIP tweet {tid} — duplicate")
                total_skipped += 1; continue

            # Step 2: Keyword gate
            if not keyword_match(tweet_text):
                logging.info(f"SKIP tweet {tid} — no_keyword")
                log_skipped(tid, "no_keyword")
                total_skipped += 1; continue
            if not passes_anchor(tweet_text, station_code):
                logging.info(f"SKIP tweet {tid} — no_odisha_anchor")
                log_skipped(tid, "no_odisha_anchor")
                total_skipped += 1; continue
            if not has_allowed_language(tweet):
                logging.info(f"SKIP tweet {tid} — wrong_language")
                log_skipped(tid, "wrong_language")
                total_skipped += 1; continue

            # Step 3: LLM extraction
            extract, llm_model_used, processing_status = call_llm_extract(tweet_text)
            severity = extract.get("severity")
            try:
                severity = int(severity)
                if severity < 1 or severity > 5:
                    severity = 1
            except (TypeError, ValueError):
                severity = 1
            extract["severity"] = severity

            reliability_score = extract.get("reliability_score")
            try:
                reliability_score = int(reliability_score)
                if reliability_score < 1 or reliability_score > 5:
                    reliability_score = 1
            except (TypeError, ValueError):
                reliability_score = 1
            extract["reliability_score"] = reliability_score

            # Step 4: Validation
            extract = validate_against_gauge(extract)
            extract = validate_against_imd(extract)
            extract = validate_coordinates(extract)

            # Boost: cluster check
            cluster_count = count_cluster_tweets(station_code)
            if cluster_count >= 3: extract["reliability_score"] = min(5, extract.get("reliability_score",2)+1)

            # Verified crisis check
            imd_wms = 1
            try:
                feeds = requests.get("https://www.joodei.org/api/feeds", timeout=10).json()
                for s in feeds.get("imd",{}).get("stations",[]):
                    if s.get("name") == extract.get("station_proximity",""):
                        imd_wms = s.get("wms_color",1); break
            except: pass
            verified = check_verified_crisis(extract, station_code, imd_wms)

            # LLM classification
            classification = {}
            classify_model_used = None
            if verified and (GROQ_API or OPENROUTER_KEY):
                classification, classify_model_used = call_llm_classify(extract)
                if classify_model_used:
                    llm_model_used = classify_model_used

            if extract.get("severity", 0) <= 1 and extract.get("reliability_score", 0) <= 1:
                logging.info(f"SKIP tweet {tid} — low_quality")
                log_skipped(tid, "low_quality")
                total_skipped += 1; continue

            # Insert
            insert_signal("twitter", tweet, extract, station_code,
                         "classified" if verified and classification else processing_status,
                         classification=classification, is_verified=verified,
                         llm_model_used=llm_model_used)
            total_processed += 1
            log.info("  %s | sev=%d | rel=%d | verified=%s", station_code,
                     extract.get("severity",0), extract.get("reliability_score",2), verified)

    log.info("Done: %d processed, %d skipped", total_processed, total_skipped)


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--once", action="store_true")
    p.add_argument("--test", action="store_true")
    args = p.parse_args()

    if args.test:
        log.info("Twitter: %s", "configured" if TWITTER_BEARER else "not configured (dummy)")
        log.info("Groq: %s", "configured" if GROQ_API else "not configured")
        log.info("OpenRouter: %s", "configured" if OPENROUTER_KEY else "not configured")
        log.info("DB: %s", DATABASE_URL[:40] + "...")
        log.info("Stations: %d", len(STATION_QUERIES))
        log.info("Test OK")
    else:
        run()
