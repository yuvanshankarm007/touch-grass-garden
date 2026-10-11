# Touch Grass Garden (v3.0)

A plant milestone tracker that rewards you for going **outside**, not for opening the app.

- Detects the local season from your coordinates and the date
- Suggests what to sow this month, with the growing method and requirements for each crop
- Tracks each plant through growth milestones (sown -> germinated -> ... -> harvest)
- Builds a short "today's outdoor card" with a local open-weight model (Gemma via Ollama)
- Weather alerts and a best-time-outside window (rule-based, forecast cached for offline use)
- The streak counts **days you logged a check-in at your plants** - opening the app earns nothing
- Weekly outdoor goal (default 4 days) with a progress bar - only real check-ins count
- Photo log: attach a photo to each outdoor check-in and see it in the plant's timeline
- Growth timeline: chart and history of every check-in per plant
- Care reminders: watering due dates from `crops.json`, with a note when heavy rain is forecast
- Printable card: download a plain-text card with tick boxes, take it outside and close the laptop
- "If you see..." tips for common problems per crop (general starter advice, confirm locally)
- Card language: the local model writes the card in Hindi, Tamil, Telugu, Malayalam, Kannada, Bengali, Marathi, Spanish or French (quality varies by language; the offline fallback card is English only)
- Regional crop packs: drop a JSON file in `crop_packs/` (see `crop_packs/_template.json`) and pick it in the sidebar; pack crops add to or override the built-ins
- Photo descriptions (experimental): a local multimodal Gemma model describes a check-in photo. It is labelled as an unverified AI description and is never used for alerts or advice
- Garden recap: days outside, longest streak and per-plant totals, with a download button

## What changed in v3
- Fixed: the card no longer tells you to water a plant that is not due (the model only sees watering info when it is due)
- Fixed: the card no longer repeats the same bullet for each plant
- Fixed: "Generate today's card" now regenerates every time you click it
- Added: card language, regional crop packs, photo descriptions, garden recap

## Run it

1. Install Ollama and pull a small Gemma model: `ollama pull gemma3:4b`
2. `pip install -r requirements.txt`
3. `streamlit run app.py`
4. Set your latitude/longitude in the sidebar, add a plant, go outside.

If Ollama is not running, the app falls back to a rule-based card, so it never breaks in the field.

## Data

`crops.json` is the only source of crop facts. The model is told to use only that data and never to
invent facts. The starter data is tuned for warm/subtropical climates - edit `sow_months` and temps
for your region.

Everything except the forecast fetch works offline. When offline, the last saved forecast is used
and its age is shown. Your plant log (`garden_log.json`) never leaves your device.

## Development

- `pytest` runs the unit tests (crop data validation, season logic, streak, alerts, fallback card).
- `.github/workflows/ci.yml` runs the tests and a headless smoke test of the app on every push.
- `make_voiceover.py` generates demo narration with ElevenLabs from `narration.txt`.
