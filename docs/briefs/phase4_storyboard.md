# Phase 4 — Storyboard: realize element cues into beats.json

## What exists going in
- `beat_script` column (Phase 3) validating against `BeatScript`; each beat
  has one primary `ElementCue` (chart or broll) + optional overlays.
- **Stock search to reuse:** `Backend/nodes/asset_fetcher/node3_asset_fetcher.py`
  — `_try_stock_query(keyword, dest, min_duration, used, rejected)` handles
  cache → Pexels portrait → Pexels broad → Pixabay → stock-still → validation.
  Note: for long-form we want **landscape**, so call `fetch_from_pexels(...,
  portrait=False)` first; a small param or wrapper is fine, don't fork the
  function.
- **Chart shape to reuse:** `ChartSpec` in `Backend/remotion/src/ChartOverlay.tsx`
  (chart_type, display_mode, title, unit, points, highlight, source_url,
  source_label). `ResearchArtifact.DataPoint` carries everything needed to
  fill one.

## What this phase must produce
1. **Worker:** `Backend/nodes/storyboard/node3b_storyboard.py`, `run()` polling
   `Pending_Storyboard`. For each beat element:
   - `chart`: resolve `ref` → `DataPoint` → build a ChartSpec-shaped dict
     (`chart_type`: 'line' if all labels are years else 'bar'; values copied
     exactly — never modified).
   - `broll`: stock search via node3's `_try_stock_query` (landscape-first),
     download to `Backend/assets/{video_id}/beats/beat_{order}_{n}.mp4`,
     fetch 2–3 candidates per broll cue so the owner can pick.
   - `image`/`meme`/`sticker`/`text_callout`: do NOT auto-fetch; carry the cue
     through unrealized with `"realized": false` (the owner adds/edits these in
     Remotion Studio — that's the design, not a gap).
2. **Output = `Backend/assets/{video_id}/beats.json`** — the single source of
   truth Remotion will render from (Phase 6) and the file the owner edits in
   Remotion Studio. Shape: the `BeatScript` JSON, where each element gains
   realization fields: `src` (relative asset path) or `chart` (ChartSpec dict),
   `candidates` (alternate broll paths), `realized` (bool). Store the same
   JSON in a new `beats_json` column too (add to `migrate()`), so the DB
   remains the recovery checkpoint.
3. **Dashboard `QA_Storyboard` card:** per beat show the primary asset
   (thumbnail or chart summary) with a candidate picker (radio per broll
   candidate writes the choice back to beats.json), plus a note explaining the
   Studio step: `cd Backend/remotion && npm run dev` to fine-tune overlays.
   *Approve →* `Awaiting_Narration`. *Refetch visuals with note* → back to
   `Pending_Storyboard` excluding prior source IDs (mirror node3's
   `[VISUAL_REPLACEMENT]` / `rejected_sources` mechanism).
4. Log any paid calls (`stage='storyboard'`); Veo fallback is **disabled** for
   long-form b-roll (cost control — stock or owner-provided only).
5. Register the worker in `main.py`.

## Contract
`beats.json` must remain loadable by `BeatScript.model_validate` after
stripping the realization fields (i.e., realization only ADDS keys).

## Verification
1. A video with a chart cue + broll cue reaches `QA_Storyboard` with
   `beats.json` present; the chart dict's values exactly match the
   `DataPoint`; broll files exist and pass node3's `validate_clip`.
2. Overlay cues appear in beats.json with `realized: false`.
3. Re-fetch with a note produces different source IDs.

## Out of scope
Remotion compositions and animation presets (Phase 6); narration (Phase 5).