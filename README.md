# Automated Educational Videos

An automated pipeline that turns a topic into an owner-narrated, chart-driven
long-form YouTube video (3–10 min landscape), then derives vertical shorts
(YouTube Shorts / Instagram Reels / TikTok) from its beats — with human QA
gates at every creative step.

## Architecture

**Long-form (primary workflow):**
```
Topic (dashboard) → Node 0 Research (Gemini, or paste a Deep Research export) → QA
→ Node 1b Beat Script → QA → Node 3b Storyboard (stock b-roll + charts) → QA
→ Owner narration upload + local Whisper alignment
→ Node 4 Long Render (Remotion 1920×1080) → Node 5 Citation QA → Final QA
→ Node 6 Publish (WoopSocial) → Published
→ From any published long video: derive vertical shorts per beat (no LLM calls)
```

**Filler shorts (tucked-away option):** the legacy fully-automated short
pipeline (AI script → stock assets → vertical render) is still wired in for
weeks when long-form can't fill the schedule. Use the collapsed "📱 Filler
short" row on the dashboard.

- **Backend/main.py** — sequential orchestrator, polls the SQLite DB every 10 s.
- **Backend/nodes/** — one folder per pipeline worker.
- **Backend/remotion/** — React/Remotion video composition (word-level captions, transitions, Ken Burns, music, compliance overlay).
- **Backend/assets/{id}/** — per-video intermediates (narration.*, voiceover.mp3, timing.json, captions.json, beats.json, final.mp4).
- **Frontend/** — Reflex dashboard for creating videos, QA review, retries, and account settings.

## Running it

Double-click **`Launch_Video_Generator.command`** (or the `Video Generator`
shortcut on the Desktop). It starts the backend orchestrator and the dashboard,
then opens http://localhost:3000 when ready. Closing the window shuts both down.
Logs: `Backend/orchestrator.log` and `Frontend/dashboard.log`.

Ports: dashboard UI on **3000**, Reflex backend on **8010** (pinned in
`Frontend/rxconfig.py` because Docker Desktop tends to occupy 8000).

## Setup (one-time)

1. Python: `python3 -m venv .venv && source .venv/bin/activate && pip install -r Backend/requirements.txt -r Frontend/requirements.txt`
2. Remotion: `cd Backend/remotion && npm install`
3. Music library (CC0 tracks): `python3 Backend/scripts/fetch_music.py`
4. Create `.env` in the project root with: `GEMINI_API_KEY`, `OPENAI_API_KEY`, `PEXELS_API_KEY`, `PIXABAY_API_KEY`, `WOOPSOCIAL_API_KEY`. Without OpenAI, scripting falls back to Gemini 3.5 Flash.

> Note: the project path contains spaces, which breaks the venv's direct
> console scripts (`pip`, `reflex`). Always use `python -m pip` /
> `python -m reflex` instead — the launcher already does.

Manual run (instead of the launcher):
- Backend: `cd Backend && python3 main.py`
- Dashboard: `cd Frontend && python -m reflex run` (http://localhost:3000)

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
- Derived shorts target >60 s so they qualify for TikTok Creator Rewards.
- Sources are cited in YouTube descriptions (YMYL/health-information best practice).

## Docs

- `docs/briefs/README.md` — project conventions and session rules (living doc).
- `docs/archive/` — completed phase briefs, handoffs, and test logs.