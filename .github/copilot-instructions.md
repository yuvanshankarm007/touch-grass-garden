# Touch Grass Garden – rules for Copilot
- Core logic lives in garden.py with NO Streamlit/UI code. app.py is UI only.
- crops.json (+ crop_packs/) is the ONLY source of crop facts. Never hardcode crop advice.
- Weather alerts are rule-based. The LLM must never decide or write alerts.
- The streak and weekly goal count ONLY logged check-ins, never app opens.
- Everything except the forecast fetch must work offline. No new cloud services.
- User data (garden_log.json, photos/) never leaves the device and is never committed.
- Every change to garden.py needs a pytest test in tests/test_garden.py.
- Keep the offline fallback card working when Ollama is not running.
- Keep pull requests small: one issue, one change.
