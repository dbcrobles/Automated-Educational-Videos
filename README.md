# Automated Educational Videos

An automated pipeline that turns a topic into a published short-form educational video (YouTube Shorts / Instagram Reels / TikTok), with human QA gates.

## Architecture

```
Topic (dashboard) → Node 1 Research (Gemini) + Script (GPT-5.6 Luna) → QA gate
→ Owner narration upload + local Whisper alignment → Node 3 Assets + visual QA (stock/stills/Veo + Gemini)
→ Node 4 Render (Remotion + FFmpeg)
→ QA gate → Node 5 Publish (WoopSocial) → Published
```

- **Backend/main.py** — sequential orchestrator, polls the SQLite DB every 10 s.
- **Backend/nodes/** — one folder per pipeline worker.
- **Backend/remotion/** — React/Remotion video composition (word-level captions, transitions, Ken Burns, music, compliance overlay).
- **Backend/assets/{id}/** — per-video intermediates (narration.*, voiceover.mp3, timing.json, captions.json, scene_N.mp4, final.mp4).
- **Frontend/** — Reflex dashboard for creating videos, QA review, retries, and account settings.

## Setup

1. Python: `python3 -m venv .venv && source .venv/bin/activate && pip install -r Backend/requirements.txt -r Frontend/requirements.txt`
2. Remotion: `cd Backend/remotion && npm install`
3. Music library (CC0 tracks, one-time): `python3 Backend/scripts/fetch_music.py`
4. Create `.env` in the project root with: `GEMINI_API_KEY`, `OPENAI_API_KEY`, `PEXELS_API_KEY`, `PIXABAY_API_KEY`, `WOOPSOCIAL_API_KEY`. Without OpenAI, scripting falls back to Gemini 3.5 Flash.
5. Run backend: `python3 Backend/main.py`
6. Run dashboard: `cd Frontend && reflex run` (opens on http://localhost:3000)

## Long-form editing workflow (Remotion Studio)

- `Backend/assets/{id}/beats.json` is the single source of truth for a long-form
  video: the storyboard writes it, the owner edits it, and node4 renders from it.
- To preview/edit: `cd Backend/remotion && npm run dev`, open the **LongVideo**
  composition (loads a bundled sample), then paste a real video's beats.json
  contents into the `beats` prop in the props editor — or edit the file directly
  in your editor. Swap b-roll by setting an element's `src` to another entry in
  its `candidates` list; overlay `animation` accepts `pop_in`, `slide_up`,
  `fade`, `shake` (see `src/animations.ts`).
- When the video reaches `Pending_LongRender`, node4 renders that same
  beats.json through LongVideo (1920×1080 @ 30fps) → `QA_Final`.

## Compliance / Monetization notes

- Every video is stamped "AI-Assisted" on-screen and in file metadata (platform AI-disclosure rules).
- Narration is recorded by the channel owner and aligned locally; no cloud speech service is used.
- Target narration length is 65–100 s so videos qualify for TikTok Creator Rewards (>60 s).
- Sources are cited in YouTube descriptions (YMYL/health-information best practice).
