# Phase 6 — Remotion long-form assembly (LongVideo composition)

## Pre-step (once, before coding)
`cd Backend/remotion && npx skills add remotion-dev/skills` — install
Remotion's official Agent Skills and follow their conventions rather than
inventing patterns. (License note: Remotion free tier covers an individual —
fine for this project.)

## What exists going in
- `Backend/assets/{id}/beats.json` (Phase 4/5): realized beats with per-beat
  `start`/`end`, primary asset (`src` or `chart` spec), overlays, plus
  `voiceover.mp3` and `captions.json`.
- **Patterns to reuse from `Backend/remotion/src/`:** `ShortVideo.tsx`
  (TransitionSeries, per-scene props, music volume ducking, `staticFile`
  serving via node4's per-video symlinks), `ChartOverlay.tsx` (pie/bar/line
  renderers), `Captions.tsx`, `ComplianceOverlay.tsx`, and `Root.tsx` (zod
  schema + `calculateMetadata`).
- **Render orchestration to extend:** `Backend/nodes/render_worker/node4_render_worker.py`
  — `preprocess_clip`, `make_public_symlinks`, `render_remotion`, `pick_music`.

## What this phase must produce
1. **`LongVideo` composition (1920×1080, 30fps)** registered in `Root.tsx`
   with a zod schema mirroring beats.json. Per beat:
   - Primary layer: `OffthreadVideo` for broll `src`, or a **landscape chart
     layout** (adapt ChartOverlay: legend beside for bar/line is fine at 16:9;
     make sizes props-driven rather than hardcoded so Phase 8 can pass a
     vertical layout).
   - Overlay layers: absolutely-positioned per `position`
     (full/lower_third/…), windowed by `start_offset_sec`/`duration_sec`,
     animated by preset name.
2. **`animations.ts` preset map** — start with exactly four:
   `pop_in` (spring scale), `slide_up`, `fade`, `shake`. An overlay's
   `animation` string looks up here; unknown names fall back to `fade`.
   Adding presets later = adding entries here, nothing else.
3. **Remotion Studio flow:** `LongVideo`'s `defaultProps` should load a sample
   beats.json so `npm run dev` lets the owner open the composition, paste/point
   at a real video's beats.json in the props editor, and preview edits. The
   documented workflow: edit `Backend/assets/{id}/beats.json` (Studio props
   panel or editor), pipeline renders from that same file.
4. **Extend node4:** in `run()`, poll `Pending_LongRender` as well; for
   long-form videos build props directly from beats.json (+ `voiceoverSrc`,
   `captions`, `music` via existing `pick_music` keyed on a simple mapping
   from each beat's `music_cue` text to the four mood folders), symlink the
   video's asset dir (existing `make_public_symlinks`), and
   `npx remotion render src/index.ts LongVideo ...`. Success → `QA_Final`
   (reuse the existing status and dashboard preview card). No ffmpeg-fallback
   renderer for long-form — Remotion is required.
5. Keep `ShortVideo` untouched — Phase 8 reuses it.

## Contract
`LongVideo` consumes beats.json as written by Phases 4–5 (realization keys
included); it must not require fields those phases don't produce.

## Verification
1. `npx remotion render src/index.ts LongVideo out.mp4 --props=<sample beats.json>`
   succeeds on a 3-beat sample (chart beat + broll beat + overlay).
2. Output duration matches the narration within 1 s; chart values on screen
   match the DataPoint exactly.
3. `npm run dev` shows LongVideo in Studio with editable props.