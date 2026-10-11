"""Core logic for the Touch Grass garden tracker. No UI code here."""
import base64
import io
import json
import datetime as dt
import pathlib
import uuid

import requests

BASE = pathlib.Path(__file__).parent
CROPS_FILE = BASE / "crops.json"
LOG_FILE = BASE / "garden_log.json"
WEATHER_CACHE = BASE / "weather_cache.json"
PHOTO_DIR = BASE / "photos"
PACK_DIR = BASE / "crop_packs"
LANGUAGES = ["English", "Hindi", "Tamil", "Telugu", "Malayalam", "Kannada", "Bengali", "Marathi", "Spanish", "French"]
REQUIRED_CROP_KEYS = ["id", "name", "template", "sow_months", "days_to_harvest", "sun", "water", "soil",
                      "method", "temp_min", "temp_max", "water_every_days", "problems"]
OLLAMA_URL = "http://localhost:11434/api/generate"


# ---------- data ----------
def list_packs():
    """Names of optional regional crop packs in crop_packs/ (files starting with _ are ignored)."""
    if not PACK_DIR.exists():
        return []
    return sorted(p.stem for p in PACK_DIR.glob("*.json") if not p.stem.startswith("_"))


def load_crops(pack=None):
    """Load the built-in crops, optionally merged with a regional pack (pack crops override by id)."""
    data = json.loads(CROPS_FILE.read_text(encoding="utf-8"))
    templates = dict(data["stage_templates"])
    raw = {c["id"]: c for c in data["crops"]}
    if pack:
        pdata = json.loads((PACK_DIR / f"{pack}.json").read_text(encoding="utf-8"))
        templates.update(pdata.get("stage_templates", {}))
        for c in pdata.get("crops", []):
            missing = [k for k in REQUIRED_CROP_KEYS if k not in c]
            if missing:
                raise ValueError(f"Pack '{pack}': crop '{c.get('id', '?')}' is missing: {', '.join(missing)}")
            if c["template"] not in templates:
                raise ValueError(f"Pack '{pack}': crop '{c['id']}' uses unknown template '{c['template']}'")
            raw[c["id"]] = c
    crops = {}
    for c in raw.values():
        c = dict(c)
        c["stages"] = templates[c["template"]]
        crops[c["id"]] = c
    return crops


def load_log():
    log = {"plants": [], "checkins": []}
    if LOG_FILE.exists():
        log = json.loads(LOG_FILE.read_text(encoding="utf-8"))
    log.setdefault("plants", [])
    log.setdefault("checkins", [])
    log.setdefault("settings", {})
    log["settings"].setdefault("weekly_goal", 4)
    return log


def save_log(log):
    LOG_FILE.write_text(json.dumps(log, indent=2), encoding="utf-8")


def add_plant(log, crop_id, nickname, sown):
    log["plants"].append(
        {"id": uuid.uuid4().hex[:8], "crop_id": crop_id, "nickname": nickname, "sown": sown.isoformat()}
    )


def add_checkin(log, plant_id, stage_seen, note, when=None, photo=None, watered=False):
    when = when or dt.date.today()
    log["checkins"].append(
        {"date": when.isoformat(), "plant_id": plant_id, "stage_seen": stage_seen, "note": note,
         "photo": photo, "watered": bool(watered)}
    )


def save_photo(data, suffix):
    """Save an uploaded photo under photos/ and return its file name."""
    suffix = suffix.lower()
    if suffix not in (".jpg", ".jpeg", ".png"):
        suffix = ".jpg"
    PHOTO_DIR.mkdir(exist_ok=True)
    name = f"{uuid.uuid4().hex[:10]}{suffix}"
    (PHOTO_DIR / name).write_bytes(data)
    return name


# ---------- season ----------
def season_for(lat, lon, today):
    """Return (season_name, system_name). Uses the Indian agricultural calendar
    inside the subcontinent's bounding box, otherwise four seasons by hemisphere."""
    m = today.month
    if 6 <= lat <= 37 and 68 <= lon <= 98:
        if 6 <= m <= 10:
            return "Kharif (monsoon crop season)", "Indian agricultural calendar"
        if m >= 11 or m <= 3:
            return "Rabi (cool crop season)", "Indian agricultural calendar"
        return "Zaid (hot, dry summer season)", "Indian agricultural calendar"
    if abs(lat) < 23.5:
        return ("Wet season" if m in (5, 6, 7, 8, 9, 10) else "Dry season"), "Tropical wet/dry"
    northern = ["Winter", "Winter", "Spring", "Spring", "Spring", "Summer",
                "Summer", "Summer", "Autumn", "Autumn", "Autumn", "Winter"]
    s = northern[m - 1]
    if lat < 0:
        flip = {"Winter": "Summer", "Summer": "Winter", "Spring": "Autumn", "Autumn": "Spring"}
        s = flip[s]
    return s, "Four seasons"


def crops_for_month(crops, month):
    return [c for c in crops.values() if month in c["sow_months"]]


# ---------- growth milestones ----------
def milestones(plant, crop):
    sown = dt.date.fromisoformat(plant["sown"])
    out = []
    for s in crop["stages"]:
        out.append({**s, "expected": sown + dt.timedelta(days=round(s["at"] * crop["days_to_harvest"]))})
    return out


def expected_stage_index(plant, crop, today):
    sown = dt.date.fromisoformat(plant["sown"])
    frac = max(0, (today - sown).days) / crop["days_to_harvest"]
    idx = 0
    for i, s in enumerate(crop["stages"]):
        if s["at"] <= frac:
            idx = i
    return idx


def observed_stage_index(log, plant, crop):
    names = [s["name"] for s in crop["stages"]]
    best = 0
    for c in log["checkins"]:
        if c["plant_id"] == plant["id"] and c["stage_seen"] in names:
            best = max(best, names.index(c["stage_seen"]))
    return best


# ---------- outdoor streak ----------
def checkin_dates(log):
    return sorted({dt.date.fromisoformat(c["date"]) for c in log["checkins"]})


def outdoor_streak(log, today):
    """Consecutive days with at least one outdoor check-in, ending today or yesterday."""
    days = set(checkin_dates(log))
    d = today if today in days else today - dt.timedelta(days=1)
    n = 0
    while d in days:
        n += 1
        d -= dt.timedelta(days=1)
    return n


def outdoor_calendar_grid(log, today, weeks=12):
    """Return a week-by-week grid of outdoor check-ins for calendar heatmaps."""
    if weeks <= 0:
        return []
    days = set(checkin_dates(log))
    start = today - dt.timedelta(days=today.weekday()) - dt.timedelta(weeks=weeks - 1)
    names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    rows = []
    for week in range(weeks):
        week_start = start + dt.timedelta(weeks=week)
        for weekday, name in enumerate(names):
            day = week_start + dt.timedelta(days=weekday)
            rows.append({
                "date": day.isoformat(),
                "week": week,
                "week_label": week_start.strftime("%d %b"),
                "weekday": name,
                "filled": 1 if day in days else 0,
            })
    return rows


def badges(log):
    total = len(checkin_dates(log))
    steps = [(1, "First steps outside"), (3, "3 days outside"), (7, "A week outside"), (30, "30 days outside")]
    return [name for need, name in steps if total >= need]


# ---------- weather (online fetch, offline cache) ----------
def fetch_weather(lat, lon):
    """Returns (data, fetched_at_iso, from_cache). Falls back to cache when offline."""
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": lat, "longitude": lon, "timezone": "auto", "forecast_days": 3,
        "hourly": "temperature_2m,precipitation_probability,wind_speed_10m",
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,wind_speed_10m_max",
    }
    try:
        r = requests.get(url, params=params, timeout=8)
        r.raise_for_status()
        data = r.json()
        stamp = dt.datetime.now().isoformat(timespec="minutes")
        WEATHER_CACHE.write_text(json.dumps({"fetched_at": stamp, "data": data}), encoding="utf-8")
        return data, stamp, False
    except Exception:
        if WEATHER_CACHE.exists():
            c = json.loads(WEATHER_CACHE.read_text(encoding="utf-8"))
            return c["data"], c["fetched_at"], True
        return None, None, True


def weather_alerts(daily):
    """Plain rule-based alerts for today and tomorrow. The LLM never decides these."""
    alerts = []
    for i, label in enumerate(["Today", "Tomorrow"]):
        if i >= len(daily["time"]):
            break
        tmax, tmin = daily["temperature_2m_max"][i], daily["temperature_2m_min"][i]
        rain, wind = daily["precipitation_sum"][i], daily["wind_speed_10m_max"][i]
        if rain is not None and rain >= 10:
            alerts.append(f"{label}: heavy rain expected ({rain:.0f} mm). Check drainage and cover seedlings.")
        if tmax is not None and tmax >= 38:
            alerts.append(f"{label}: very hot ({tmax:.0f} C). Water early and shade young plants.")
        if tmin is not None and tmin <= 5:
            alerts.append(f"{label}: cold night ({tmin:.0f} C). Cover tender plants.")
        if wind is not None and wind >= 40:
            alerts.append(f"{label}: strong wind ({wind:.0f} km/h). Support climbers and tall plants.")
    return alerts


def crop_weather_alerts(daily, plants, crops):
    """Per-crop temperature alerts for today and tomorrow based on temp_min/temp_max."""
    alerts = []
    for i, label in enumerate(["Today", "Tomorrow"]):
        if i >= len(daily["time"]):
            break
        tmax, tmin = daily["temperature_2m_max"][i], daily["temperature_2m_min"][i]
        for plant in plants:
            crop = crops.get(plant["crop_id"])
            if not crop:
                continue
            name = plant.get("nickname") or crop["name"]
            if tmin is not None and tmin < crop["temp_min"]:
                alerts.append(
                    f"{label} night {tmin:.0f} C is below {name}'s minimum ({crop['temp_min']:.0f} C). Cover it."
                )
            if tmax is not None and tmax > crop["temp_max"]:
                alerts.append(
                    f"{label} {tmax:.0f} C is above {name}'s maximum ({crop['temp_max']:.0f} C). Give shade."
                )
    return alerts


def best_window(hourly, today):
    """Longest run of comfortable daylight hours today. Returns 'HH:00-HH:00' or None."""
    good = []
    for t, temp, pp, wind in zip(hourly["time"], hourly["temperature_2m"],
                                 hourly["precipitation_probability"], hourly["wind_speed_10m"]):
        stamp = dt.datetime.fromisoformat(t)
        if stamp.date() != today or not (5 <= stamp.hour <= 18):
            continue
        ok = temp is not None and temp <= 32 and (pp or 0) <= 30 and (wind or 0) <= 25
        good.append((stamp.hour, ok))
    best, cur = [], []
    for h, ok in good:
        if ok:
            cur.append(h)
            if len(cur) > len(best):
                best = cur[:]
        else:
            cur = []
    if not best:
        return None
    return f"{best[0]:02d}:00-{best[-1] + 1:02d}:00"


# ---------- local LLM (Gemma via Ollama) ----------
def ask_gemma(prompt, model="gemma3:4b"):
    """Returns (text, used_llm). Falls back to None text if Ollama is not running."""
    try:
        r = requests.post(OLLAMA_URL, json={"model": model, "prompt": prompt, "stream": False}, timeout=90)
        r.raise_for_status()
        return r.json().get("response", "").strip(), True
    except Exception:
        return None, False


def build_card_prompt(season, plants_info, alerts, window, language="English"):
    lines = [
        "Write today's outdoor card for a gardener. Output ONLY the card, with no greeting or intro.",
        "Format: 3 to 4 bullet points starting with '- ', then one final line.",
        "RULES: Use ONLY the facts below. Never invent facts. Use each plant's exact name.",
        "Each bullet must be a physical action outdoors, using the 'look for' text for that plant.",
        "Do not repeat the same bullet for different plants. If plants share the same advice, combine them in one bullet.",
        "NEVER mention watering unless a plant's care says 'Watering due'.",
        "The final line must tell the person to put the phone away and go look at their plants.",
        "Keep it under 70 words.",
        f"Season: {season}",
        f"Best time outside today: {window or 'no comfortable window today'}",
        "Weather alerts: " + (" | ".join(alerts) if alerts else "none"),
        "Plants:",
    ]
    if language and language != "English":
        lines.insert(1, f"Write the entire card in {language}. Keep plant names exactly as given.")
    for p in plants_info:
        care = p.get("care", "none")
        if "due" not in care.lower():
            care = "no watering needed today"
        lines.append(
            f"- Name: {p['name']} | day {p['day']} | expected stage: {p['stage']} | "
            f"look for: {p['look_for']} | care: {care} | last note: {p['last_note'] or 'none'}"
        )
    return "\n".join(lines)


def fallback_card(plants_info, alerts, window):
    """Rule-based card used when the local model is unavailable."""
    out = []
    if window:
        out.append(f"Go out between {window} - the weather is comfortable.")
    for a in alerts:
        out.append(a)
    for p in plants_info:
        out.append(f"{p['name']}: {p['look_for']}")
        if p.get("care") and "due" in p["care"].lower():
            out.append(f"{p['name']}: {p['care']}")
    out.append("Now put the phone away and go look at your plants.")
    return "\n".join(f"- {x}" for x in out)


# ---------- weekly outdoor goal ----------
def weekly_progress(log, today, goal=None):
    """(days_outside_this_week, goal). Week runs Monday to today."""
    goal = goal or log.get("settings", {}).get("weekly_goal", 4)
    start = today - dt.timedelta(days=today.weekday())
    days = {d for d in checkin_dates(log) if start <= d <= today}
    return len(days), goal


# ---------- care reminders ----------
def last_watered(log, plant):
    dates = [dt.date.fromisoformat(c["date"]) for c in log["checkins"]
             if c["plant_id"] == plant["id"] and c.get("watered")]
    return max(dates) if dates else None


def water_status(log, plant, crop, today, rain_expected=False):
    """Returns {'due': bool, 'text': str}. Interval comes from crops.json (water_every_days)."""
    interval = crop.get("water_every_days", 3)
    last = last_watered(log, plant)
    ref = last or dt.date.fromisoformat(plant["sown"])
    days_left = (ref + dt.timedelta(days=interval)) - today
    if days_left.days <= 0:
        since = f"last watered {ref:%d %b}" if last else "not watered since sowing"
        text = f"Watering due ({since})."
        if rain_expected:
            text += " Heavy rain is forecast today - check the soil first and skip if it is already wet."
        return {"due": True, "text": text}
    return {"due": False, "text": f"Next watering in about {days_left.days} day(s)."}


# ---------- growth timeline ----------
def plant_timeline(log, plant, crop):
    names = [s["name"] for s in crop["stages"]]
    rows = []
    for c in sorted(log["checkins"], key=lambda c: c["date"]):
        if c["plant_id"] != plant["id"]:
            continue
        idx = names.index(c["stage_seen"]) if c["stage_seen"] in names else 0
        rows.append({"date": c["date"], "stage": c["stage_seen"], "index": idx, "note": c.get("note", ""),
                     "photo": c.get("photo"), "photo_note": c.get("photo_note"), "watered": c.get("watered", False)})
    return rows


# ---------- printable card ----------
def printable_card(today, season, window, alerts, plants_info, card_text=None):
    lines = [f"TOUCH GRASS GARDEN - {today:%A %d %B %Y}", "", f"Season: {season}",
             f"Best time outside: {window or 'no comfortable window today'}"]
    if alerts:
        lines += ["", "WEATHER"] + [f"  * {a}" for a in alerts]
    if card_text:
        lines += ["", "TODAY", card_text.strip()]
    lines += ["", "AT EACH PLANT"]
    for p in plants_info:
        lines += [f"[ ] {p['name']} (day {p['day']}, expected: {p['stage']})",
                  f"    Look for: {p['look_for']}"]
        if p.get("care"):
            lines.append(f"    Care: {p['care']}")
        lines += ["    What I saw: ______________________________________", ""]
    lines.append("Now put the phone away and go look at your plants.")
    return "\n".join(lines)


# ---------- photo description with a local vision model (experimental) ----------
def prepare_image(data, max_side=1024):
    """Shrink a photo before sending it to the local model so it stays fast."""
    from PIL import Image
    img = Image.open(io.BytesIO(data)).convert("RGB")
    img.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    return buf.getvalue()


def ask_gemma_about_photo(data, plant_name, crop_name, stage, model="gemma3:4b"):
    """Ask a local multimodal Gemma model to describe a photo. Returns (text, used_llm)."""
    prompt = (
        f"This is a photo of a {crop_name} plant called '{plant_name}', expected around the '{stage}' stage. "
        "In 2 or 3 short sentences, describe only what you can actually see (leaf colour, spots, insects, "
        "growth). Do not diagnose with certainty. If you are unsure, say so. "
        "End with: 'This is an unverified AI description.'"
    )
    try:
        img = base64.b64encode(prepare_image(data)).decode()
        r = requests.post(OLLAMA_URL, json={"model": model, "prompt": prompt, "images": [img], "stream": False},
                          timeout=180)
        r.raise_for_status()
        text = r.json().get("response", "").strip()
        return (text or None), bool(text)
    except Exception:
        return None, False


def set_photo_note(log, photo, text):
    for c in log["checkins"]:
        if c.get("photo") == photo:
            c["photo_note"] = text


# ---------- garden recap ----------
def longest_streak(log):
    days = checkin_dates(log)
    best = run = 0
    prev = None
    for d in days:
        run = run + 1 if prev and (d - prev).days == 1 else 1
        best = max(best, run)
        prev = d
    return best


def season_recap(log, crops, today):
    plants = []
    for p in log["plants"]:
        crop = crops.get(p["crop_id"])
        if not crop:
            continue
        mine = [c for c in log["checkins"] if c["plant_id"] == p["id"]]
        plants.append({
            "name": p["nickname"], "crop": crop["name"],
            "day": (today - dt.date.fromisoformat(p["sown"])).days,
            "stage": crop["stages"][observed_stage_index(log, p, crop)]["name"],
            "checkins": len(mine),
            "waterings": sum(1 for c in mine if c.get("watered")),
            "photos": sum(1 for c in mine if c.get("photo")),
        })
    return {"days_outside": len(checkin_dates(log)), "best_streak": longest_streak(log), "plants": plants}


def recap_text(recap):
    lines = [f"Days outside: {recap['days_outside']} | Longest streak: {recap['best_streak']}"]
    for p in recap["plants"]:
        lines.append(f"- {p['name']} ({p['crop']}): day {p['day']}, reached '{p['stage']}', "
                     f"{p['checkins']} check-ins, {p['waterings']} waterings, {p['photos']} photos")
    return "\n".join(lines)
