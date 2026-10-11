"""Turn narration.txt into voiceover.mp3 with ElevenLabs text-to-speech.

Usage:
    export ELEVENLABS_API_KEY=your_key
    export ELEVENLABS_VOICE_ID=a_voice_id_from_your_account   # optional
    python make_voiceover.py

Edit narration.txt first: replace every [BRACKETED] part with what really happened.
The script refuses to run while any brackets remain.
"""
import os
import pathlib
import sys

import requests

text = pathlib.Path(__file__).with_name("narration.txt").read_text(encoding="utf-8").strip()
if "[" in text or "]" in text:
    sys.exit("narration.txt still has [BRACKETED] placeholders. Replace them with your real results first.")

key = os.environ.get("ELEVENLABS_API_KEY")
if not key:
    sys.exit("Set ELEVENLABS_API_KEY first.")

voice_id = os.environ.get("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")
r = requests.post(
    f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
    headers={"xi-api-key": key, "Content-Type": "application/json", "Accept": "audio/mpeg"},
    json={"text": text, "model_id": "eleven_multilingual_v2"},
    timeout=120,
)
if r.status_code != 200:
    sys.exit(f"ElevenLabs returned {r.status_code}: {r.text[:300]}")
pathlib.Path("voiceover.mp3").write_bytes(r.content)
print("Saved voiceover.mp3")
