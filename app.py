"""Touch Grass Garden v3 - a plant milestone tracker that rewards going OUTSIDE, not opening the app."""
import datetime as dt
import pathlib

import pandas as pd
import streamlit as st

import garden

VERSION = "3.0"

st.set_page_config(page_title="Touch Grass Garden", page_icon="🌱", layout="centered")

log = garden.load_log()
today = dt.date.today()

# ---------------- sidebar: settings + add plant ----------------
with st.sidebar:
    st.header("Settings")
    lat = st.number_input("Latitude", value=20.0, format="%.4f", help="Set your own location")
    lon = st.number_input("Longitude", value=78.0, format="%.4f")
    model = st.text_input("Local model (Ollama)", value="gemma3:4b")
    language = st.selectbox("Card language", garden.LANGUAGES,
                            help="The local model writes the card in this language. Quality varies by language.")
    packs = garden.list_packs()
    pack = st.selectbox("Crop pack", ["Built-in starter"] + packs,
                        help="Regional crop packs live in the crop_packs/ folder.")
    goal = st.number_input("Weekly outdoor goal (days)", min_value=1, max_value=7,
                           value=int(log["settings"]["weekly_goal"]))
    if goal != log["settings"]["weekly_goal"]:
        log["settings"]["weekly_goal"] = int(goal)
        garden.save_log(log)

try:
    crops = garden.load_crops(None if pack == "Built-in starter" else pack)
except Exception as e:  # bad pack file: fall back to the starter data
    st.sidebar.error(f"Could not load pack '{pack}': {e}")
    crops = garden.load_crops()

plants = [p for p in log["plants"] if p["crop_id"] in crops]
if len(plants) < len(log["plants"]):
    st.sidebar.warning(f"{len(log['plants']) - len(plants)} plant(s) use crops missing from this pack and are hidden.")

with st.sidebar:
    st.header("Plant something")
    season, system = garden.season_for(lat, lon, today)
    suggestions = garden.crops_for_month(crops, today.month)
    st.caption(f"Good to sow this month: {', '.join(c['name'] for c in suggestions) or 'nothing in the data'}")
    with st.form("add_plant", clear_on_submit=True):
        crop_id = st.selectbox("Crop", options=list(crops), format_func=lambda k: crops[k]["name"])
        nickname = st.text_input("Nickname (optional)", placeholder="e.g. Balcony pot 1")
        sown = st.date_input("Sown on", value=today, max_value=today)
        if st.form_submit_button("Add plant"):
            garden.add_plant(log, crop_id, nickname or crops[crop_id]["name"], sown)
            garden.save_log(log)
            st.rerun()
    st.caption(f"Touch Grass Garden v{VERSION}")

st.title("🌱 Touch Grass Garden")
st.caption("The best session is a 30-second one. Read the card, then go outside.")

# ---------------- streak, weekly goal, badges ----------------
streak = garden.outdoor_streak(log, today)
total_days = len(garden.checkin_dates(log))
c1, c2, c3 = st.columns(3)
c1.metric("Days-outside streak", streak)
c2.metric("Total days outside", total_days)
c3.metric("Plants growing", len(plants))

week_days, week_goal = garden.weekly_progress(log, today)
st.progress(min(week_days / week_goal, 1.0), text=f"This week: {week_days} of {week_goal} days outside")
if week_days >= week_goal:
    st.success("Weekly goal reached - nice work.")
earned = garden.badges(log)
if earned:
    st.success("Badges: " + "  |  ".join(earned))
st.caption("Streaks and goals only count when you log a check-in made at your plants. Opening this app earns nothing.")

# ---------------- weather ----------------
weather, fetched_at, from_cache = garden.fetch_weather(lat, lon)
alerts, crop_alerts, window = [], [], None
if weather:
    alerts = garden.weather_alerts(weather["daily"])
    crop_alerts = garden.crop_weather_alerts(weather["daily"], plants, crops)
    window = garden.best_window(weather["hourly"], today)
    if from_cache:
        st.warning(f"Offline - using the forecast saved at {fetched_at}.")
else:
    st.info("No internet and no saved forecast yet. The card still works from your plant data.")
rain_today = any(a.startswith("Today") and "heavy rain" in a for a in alerts)

# ---------------- today's card ----------------
st.subheader("Today's outdoor card")
st.write(f"**Season:** {season} _({system})_")
if window:
    st.write(f"**Best time outside:** {window}")
for a in alerts:
    st.warning(a)
for a in crop_alerts:
    st.warning(a)

plants_info = []
for p in plants:
    crop = crops[p["crop_id"]]
    idx = garden.expected_stage_index(p, crop, today)
    notes = [c["note"] for c in log["checkins"] if c["plant_id"] == p["id"] and c["note"]]
    plants_info.append({
        "name": p["nickname"],
        "day": (today - dt.date.fromisoformat(p["sown"])).days,
        "stage": crop["stages"][idx]["name"],
        "look_for": crop["stages"][idx]["look_for"],
        "care": garden.water_status(log, p, crop, today, rain_today)["text"],
        "last_note": notes[-1] if notes else "",
    })

card_text = None
if not plants:
    st.info("Add your first plant in the sidebar. Tip: radish and methi give a first harvest in about 30 days.")
else:
    for info in plants_info:
        if "due" in info["care"].lower():
            st.info(f"💧 {info['name']}: {info['care']}")
    key = f"card-{today}-{len(log['checkins'])}-{len(plants)}-{language}"
    clicked = st.button("Generate today's card")
    if clicked or key in st.session_state:
        if clicked or key not in st.session_state:
            with st.spinner("Asking the local model..."):
                text, used = garden.ask_gemma(
                    garden.build_card_prompt(season, plants_info, alerts, window, language), model)
            if not used:
                text = garden.fallback_card(plants_info, alerts, window)
                st.caption("Local model not reachable - showing the rule-based card (English only).")
            st.session_state[key] = text
        card_text = st.session_state[key]
        st.markdown(card_text)
    st.download_button(
        "Download a printable card (take it outside, close the laptop)",
        data=garden.printable_card(today, season, window, alerts, plants_info, card_text),
        file_name=f"touch-grass-card-{today}.txt",
        mime="text/plain",
    )

# ---------------- plants ----------------
st.subheader("Your plants")
for p in plants:
    crop = crops[p["crop_id"]]
    ms = garden.milestones(p, crop)
    obs = garden.observed_stage_index(log, p, crop)
    exp = garden.expected_stage_index(p, crop, today)
    with st.expander(f"{p['nickname']} - {crop['name']} (sown {p['sown']})", expanded=True):
        st.progress(obs / (len(ms) - 1), text=f"Seen so far: {ms[obs]['name']}")
        if exp > obs:
            st.caption(f"By the calendar it should be around '{ms[exp]['name']}' - go and look!")
        water = garden.water_status(log, p, crop, today, rain_today)
        st.caption(("💧 " if water["due"] else "✅ ") + water["text"])

        t_check, t_miles, t_time, t_help = st.tabs(["Check in", "Milestones", "Timeline", "If you see..."])

        with t_check:
            st.markdown(
                f"**Needs:** {crop['sun']} | {crop['water']} | {crop['soil']}  \n**Method:** {crop['method']}"
            )
            with st.form(f"checkin-{p['id']}", clear_on_submit=True):
                st.markdown("**I went outside and looked at it**")
                seen = st.selectbox("What stage do you see?", [m["name"] for m in ms], index=obs, key=f"s{p['id']}")
                note = st.text_input("Note (optional)", key=f"n{p['id']}")
                watered = st.checkbox("I watered it today", key=f"w{p['id']}")
                photo = st.file_uploader("Photo (optional)", type=["jpg", "jpeg", "png"], key=f"p{p['id']}")
                if st.form_submit_button("Log my outdoor check-in"):
                    saved = None
                    if photo is not None:
                        saved = garden.save_photo(photo.getvalue(), pathlib.Path(photo.name).suffix)
                    garden.add_checkin(log, p["id"], seen, note, photo=saved, watered=watered)
                    garden.save_log(log)
                    st.rerun()
            confirm_delete = st.checkbox(
                "Confirm delete this plant and all its check-ins",
                key=f"confirm-delete-plant-{p['id']}",
            )
            if st.button("Delete plant", key=f"delete-plant-{p['id']}", disabled=not confirm_delete):
                garden.delete_plant(log, p["id"])
                garden.save_log(log)
                st.rerun()

        with t_miles:
            for i, m in enumerate(ms):
                mark = "✅" if i <= obs else "⬜"
                st.write(f"{mark} {m['name']} - expected around {m['expected']:%d %b}")
                st.caption(m["look_for"])

        with t_time:
            rows = garden.plant_timeline(log, p, crop)
            if not rows:
                st.caption("No check-ins yet. Go outside, look, and log your first one.")
            else:
                if len(rows) >= 2:
                    df = pd.DataFrame({"Stage seen (0 = sown)": [r["index"] for r in rows]},
                                      index=[r["date"] for r in rows])
                    st.line_chart(df)
                for r in reversed(rows):
                    extra = " - watered" if r["watered"] else ""
                    st.markdown(f"**{r['date']}** - {r['stage']}{extra}" + (f"  \n_{r['note']}_" if r["note"] else ""))
                    if st.button("Delete check-in", key=f"delete-checkin-{r['id']}"):
                        garden.delete_checkin(log, r["id"])
                        garden.save_log(log)
                        st.rerun()
                    path = garden.PHOTO_DIR / r["photo"] if r["photo"] else None
                    if path and path.exists():
                        st.image(str(path), width=180)
                        if r["photo_note"]:
                            st.caption(f"🔎 {r['photo_note']}")
                        elif st.button("Describe this photo (experimental, local model)", key=f"v-{r['photo']}"):
                            with st.spinner("Looking at the photo with the local model..."):
                                desc, used = garden.ask_gemma_about_photo(
                                    path.read_bytes(), p["nickname"], crop["name"], r["stage"], model)
                            if used:
                                garden.set_photo_note(log, r["photo"], desc)
                                garden.save_log(log)
                                st.rerun()
                            else:
                                st.warning("The local model could not describe this photo. "
                                           "Use a multimodal model such as gemma3:4b and make sure Ollama is running.")

        with t_help:
            st.caption("General starter advice - confirm with a local agricultural extension service.")
            for item in crop["problems"]:
                st.markdown(f"**{item['sign']}**  \n{item['action']}")

# ---------------- recap ----------------
if plants:
    st.subheader("Your garden so far")
    recap = garden.season_recap(log, crops, today)
    r1, r2 = st.columns(2)
    r1.metric("Days outside", recap["days_outside"])
    r2.metric("Longest streak", recap["best_streak"])
    for rp in recap["plants"]:
        st.write(f"**{rp['name']}** ({rp['crop']}) - day {rp['day']}, reached *{rp['stage']}*, "
                 f"{rp['checkins']} check-ins, {rp['waterings']} waterings, {rp['photos']} photos")
    st.download_button("Download recap", data=garden.recap_text(recap),
                       file_name=f"touch-grass-recap-{today}.txt", mime="text/plain")
