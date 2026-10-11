import datetime as dt
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import garden  # noqa: E402

TODAY = dt.date(2026, 10, 11)


def make_log():
    log = {"plants": [], "checkins": []}
    garden.add_plant(log, "radish", "Pot 1", TODAY - dt.timedelta(days=10))
    return log, log["plants"][0], garden.load_crops()["radish"]


def test_every_crop_has_valid_stages():
    for crop in garden.load_crops().values():
        stages = crop["stages"]
        assert stages[0]["at"] == 0.0 and stages[-1]["at"] == 1.0
        assert [s["at"] for s in stages] == sorted(s["at"] for s in stages)
        assert crop["sow_months"] and all(1 <= m <= 12 for m in crop["sow_months"])


def test_season_systems():
    assert "Kharif" in garden.season_for(20, 78, TODAY)[0]
    assert garden.season_for(50, 10, TODAY)[0] == "Autumn"
    assert garden.season_for(-30, 150, TODAY)[0] == "Spring"  # southern hemisphere flips


def test_expected_stage_advances_with_time():
    log, plant, crop = make_log()
    early = garden.expected_stage_index(plant, crop, TODAY - dt.timedelta(days=10))
    later = garden.expected_stage_index(plant, crop, TODAY + dt.timedelta(days=25))
    assert early == 0 and later == len(crop["stages"]) - 1


def test_streak_counts_outdoor_checkins_only():
    log, plant, _ = make_log()
    assert garden.outdoor_streak(log, TODAY) == 0  # no check-ins, opening the app earns nothing
    for d in (0, 1, 2):
        garden.add_checkin(log, plant["id"], "Sown", "", TODAY - dt.timedelta(days=d))
    assert garden.outdoor_streak(log, TODAY) == 3
    garden.add_checkin(log, plant["id"], "Sown", "", TODAY - dt.timedelta(days=5))
    assert garden.outdoor_streak(log, TODAY) == 3  # the gap breaks the chain


def test_streak_survives_until_end_of_today():
    log, plant, _ = make_log()
    garden.add_checkin(log, plant["id"], "Sown", "", TODAY - dt.timedelta(days=1))
    assert garden.outdoor_streak(log, TODAY) == 1  # yesterday still counts, you have all day


def test_weather_alerts_are_rule_based():
    daily = {"time": ["a", "b"], "temperature_2m_max": [39, 30], "temperature_2m_min": [22, 4],
             "precipitation_sum": [12, 0], "wind_speed_10m_max": [10, 45]}
    text = " ".join(garden.weather_alerts(daily))
    assert "heavy rain" in text and "very hot" in text and "cold night" in text and "strong wind" in text
    calm = {"time": ["a"], "temperature_2m_max": [28], "temperature_2m_min": [18],
            "precipitation_sum": [0], "wind_speed_10m_max": [10]}
    assert garden.weather_alerts(calm) == []


def test_crop_weather_alerts_use_crop_temp_limits():
    daily = {"time": ["a", "b"], "temperature_2m_max": [39, 28], "temperature_2m_min": [8, 12],
             "precipitation_sum": [0, 0], "wind_speed_10m_max": [10, 10]}
    crops = garden.load_crops()
    tomato = crops["tomato"]
    plants = [{"id": "1", "crop_id": "tomato", "nickname": "Tomato"}]
    alerts = " ".join(garden.crop_weather_alerts(daily, plants, crops))
    assert f"below Tomato's minimum ({tomato['temp_min']:.0f} C)" in alerts
    assert f"above Tomato's maximum ({tomato['temp_max']:.0f} C)" in alerts


def test_crop_weather_alerts_skip_when_inside_crop_limits():
    daily = {"time": ["a"], "temperature_2m_max": [24], "temperature_2m_min": [12],
             "precipitation_sum": [0], "wind_speed_10m_max": [10]}
    plants = [{"id": "1", "crop_id": "tomato", "nickname": "Tomato"}]
    assert garden.crop_weather_alerts(daily, plants, garden.load_crops()) == []


def test_best_window_picks_longest_comfortable_run():
    hours = [f"2026-10-11T{h:02d}:00" for h in range(24)]
    temps = [20 if h < 9 else 36 for h in range(24)]  # comfortable until 09:00, then too hot
    hourly = {"time": hours, "temperature_2m": temps,
              "precipitation_probability": [0] * 24, "wind_speed_10m": [5] * 24}
    assert garden.best_window(hourly, TODAY) == "05:00-09:00"
    hot = dict(hourly, temperature_2m=[40] * 24)
    assert garden.best_window(hot, TODAY) is None


def test_fallback_card_works_without_the_model():
    info = [{"name": "Pot 1", "look_for": "Look for shoots."}]
    card = garden.fallback_card(info, ["Today: heavy rain."], "06:00-09:00")
    assert "Pot 1" in card and "06:00-09:00" in card and "phone away" in card


def test_every_crop_has_water_interval_and_problem_tips():
    for crop in garden.load_crops().values():
        assert crop["water_every_days"] >= 1
        assert len(crop["problems"]) >= 2
        assert all(p["sign"] and p["action"] for p in crop["problems"])


def test_weekly_progress_counts_distinct_days_this_week():
    log, plant, _ = make_log()
    monday = TODAY - dt.timedelta(days=TODAY.weekday())
    for d in (0, 0, 1, 3):  # two check-ins on one day still count as one day
        garden.add_checkin(log, plant["id"], "Sown", "", monday + dt.timedelta(days=d))
    garden.add_checkin(log, plant["id"], "Sown", "", monday - dt.timedelta(days=2))  # last week
    assert garden.weekly_progress(log, monday + dt.timedelta(days=4), goal=4) == (3, 4)


def test_water_status_due_and_rain_note():
    log, plant, crop = make_log()  # radish, sown 10 days ago, never watered
    status = garden.water_status(log, plant, crop, TODAY)
    assert status["due"] and "not watered since sowing" in status["text"]
    assert "rain" in garden.water_status(log, plant, crop, TODAY, rain_expected=True)["text"].lower()
    garden.add_checkin(log, plant["id"], "Sown", "", TODAY, watered=True)
    assert not garden.water_status(log, plant, crop, TODAY)["due"]


def test_timeline_orders_checkins_and_keeps_photo():
    log, plant, crop = make_log()
    garden.add_checkin(log, plant["id"], "Germinated", "b", TODAY, photo="x.jpg")
    garden.add_checkin(log, plant["id"], "Sown", "a", TODAY - dt.timedelta(days=3))
    rows = garden.plant_timeline(log, plant, crop)
    assert [r["note"] for r in rows] == ["a", "b"] and rows[1]["photo"] == "x.jpg" and rows[1]["index"] == 1


def test_printable_card_has_checkbox_and_space_to_write():
    info = [{"name": "Pot 1", "day": 3, "stage": "Germinated", "look_for": "Shoots.", "care": "Watering due."}]
    text = garden.printable_card(TODAY, "Kharif", "06:00-09:00", [], info, "- do a thing")
    assert "[ ] Pot 1" in text and "What I saw" in text and "do a thing" in text


def test_prompt_forbids_filler_and_includes_care():
    info = [{"name": "Pot 1", "day": 3, "stage": "Germinated", "look_for": "Shoots.",
             "care": "Watering due.", "last_note": ""}]
    prompt = garden.build_card_prompt("Kharif", info, [], "06:00-09:00")
    assert "no greeting" in prompt and "Name: Pot 1" in prompt and "Watering due." in prompt


def test_prompt_language_and_watering_rules():
    info = [{"name": "Pot 1", "day": 3, "stage": "Germinated", "look_for": "Shoots.",
             "care": "Next watering in about 2 day(s).", "last_note": ""}]
    english = garden.build_card_prompt("Kharif", info, [], "06:00-09:00")
    assert "entire card in" not in english
    assert "no watering needed today" in english and "Next watering" not in english  # hint never reaches the model
    hindi = garden.build_card_prompt("Kharif", info, [], "06:00-09:00", language="Hindi")
    assert "entire card in Hindi" in hindi
    assert "Do not repeat the same bullet" in english


def test_regional_pack_merges_and_overrides(tmp_path, monkeypatch):
    import json
    monkeypatch.setattr(garden, "PACK_DIR", tmp_path)
    base = garden.load_crops()
    new_crop = dict(id="ragi", name="Ragi", template="leafy", sow_months=[6], days_to_harvest=100, sun="Full sun",
                    water="Low", soil="Any", method="Broadcast", temp_min=15, temp_max=35, water_every_days=4,
                    problems=[{"sign": "a", "action": "b"}, {"sign": "c", "action": "d"}])
    override = dict(new_crop, id="tomato", name="Tomato (regional)")
    (tmp_path / "south.json").write_text(json.dumps({"crops": [new_crop, override]}))
    (tmp_path / "_template.json").write_text("{}")
    assert garden.list_packs() == ["south"]
    merged = garden.load_crops("south")
    assert "ragi" in merged and merged["tomato"]["name"] == "Tomato (regional)"
    assert len(merged) == len(base) + 1 and merged["ragi"]["stages"][0]["name"] == "Sown"


def test_bad_pack_is_rejected(tmp_path, monkeypatch):
    import json
    import pytest
    monkeypatch.setattr(garden, "PACK_DIR", tmp_path)
    (tmp_path / "bad.json").write_text(json.dumps({"crops": [{"id": "x", "template": "leafy"}]}))
    with pytest.raises(ValueError):
        garden.load_crops("bad")


def test_prepare_image_shrinks_large_photos():
    import io
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (3000, 2000), "green").save(buf, "PNG")
    out = Image.open(io.BytesIO(garden.prepare_image(buf.getvalue())))
    assert max(out.size) <= 1024 and out.format == "JPEG"


def test_photo_note_saved_on_matching_checkin():
    log, plant, crop = make_log()
    garden.add_checkin(log, plant["id"], "Sown", "", TODAY, photo="a.jpg")
    garden.add_checkin(log, plant["id"], "Sown", "", TODAY, photo="b.jpg")
    garden.set_photo_note(log, "b.jpg", "Green leaves.")
    rows = garden.plant_timeline(log, plant, crop)
    assert [r["photo_note"] for r in rows] == [None, "Green leaves."]


def test_longest_streak_and_recap():
    log, plant, crop = make_log()
    for d in (0, 1, 2, 5, 6):
        garden.add_checkin(log, plant["id"], "Germinated", "", TODAY - dt.timedelta(days=d), photo="p.jpg", watered=True)
    assert garden.longest_streak(log) == 3
    recap = garden.season_recap(log, {"radish": crop}, TODAY)
    assert recap["days_outside"] == 5 and recap["plants"][0]["waterings"] == 5 and recap["plants"][0]["photos"] == 5
    assert "Days outside: 5" in garden.recap_text(recap)
