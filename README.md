# Automated Educational Videos

An automated pipeline that turns a topic into a published short-form educational video (YouTube Shorts / Instagram Reels / TikTok), with human QA gates.

## Architecture

```
Topic (dashboard) → Node 1 Script (Gemini) → QA gate → Node 2 Voice (ElevenLabs)
→ Node 3 Assets (Pexels/Pixabay/Veo) → Node 4 Render (Remotion + FFmpeg)
→ QA gate → Node 5 Publish (WoopSocial) → Published
```

- **Backend/main.py** — sequential orchestrator, polls the SQLite DB every 10 s.
- **Backend/nodes/** — one folder per pipeline worker.
- **Backend/remotion/** — React/Remotion video composition (word-level captions, transitions, Ken Burns, music, compliance overlay).
- **Backend/assets/{id}/** — per-video intermediates (voiceover.mp3, timing.json, captions.json, scene_N.mp4, final.mp4).
- **Frontend/** — Reflex dashboard for creating videos, QA review, retries, and account settings.

## Setup

1. Python: `python3 -m venv .venv && source .venv/bin/activate && pip install -r Backend/requirements.txt -r Frontend/requirements.txt`
2. Remotion: `cd Backend/remotion && npm install`
3. Music library (CC0 tracks, one-time): `python3 Backend/scripts/fetch_music.py`
4. Create `.env` in the project root with: `GEMINI_API_KEY`, `ELEVENLABS_API_KEY`, `PEXELS_API_KEY`, `PIXABAY_API_KEY`, `WOOPSOCIAL_API_KEY`.
5. Run backend: `python3 Backend/main.py`
6. Run dashboard: `cd Frontend && reflex run` (opens on http://localhost:3000)

## Compliance / Monetization notes

- Every video is stamped "AI-Assisted" on-screen and in file metadata (platform AI-disclosure rules).
- Voices are randomized per video and matched to the script's mood — avoids the "mass-produced content" demonetization flag (YouTube, July 2025 policy).
- Target narration length is 65–100 s so videos qualify for TikTok Creator Rewards (>60 s).
- Sources are cited in YouTube descriptions (YMYL/health-information best practice).