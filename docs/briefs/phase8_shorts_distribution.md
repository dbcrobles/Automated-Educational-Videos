# Phase 8 — Shorts extraction (re-render, not crop) + distribution fold-in

## What exists going in
- Published long-form videos with `beats.json` (element specs + per-beat
  `start`/`end`), `voiceover.mp3`, `captions.json`, and per-beat `hook_label`.
- **Vertical renderer to reuse:** `Backend/remotion/src/ShortVideo.tsx`
  (1080×1920) and, from Phase 6, the props-driven chart layout sizing.
- **Publisher to reuse:** `Backend/nodes/publisher/node6_publisher.py` —
  WoopSocial multi-platform post with per-platform captions.
  `publish_snapchat` / `publish_x` (~lines 64–74) are print-only stubs.
- Legacy short-form entry: the original topic → `Pending_Script` form in the
  dashboard's `add_video()`.

## Design rule (owner decision — do not crop)
Shorts are **re-rendered from element specs**, never cropped from the finished
16:9 MP4. Charts re-flow for vertical (legend below, larger fonts), overlays
reposition. Audio is the real narration sliced at beat boundaries.

## What this phase must produce
1. **DB columns** (via `migrate()`): `parent_video_id INTEGER`,
   `beat_order INTEGER`.
2. **Dashboard:** on Published long-form cards, a "Create Short from beat"
   picker listing beats by `hook_label`. Selecting one inserts a new video row
   (`format='short_derived'`, `parent_video_id`, `beat_order`,
   status `Pending_ShortRender`) — no LLM calls; the beat already carries
   everything.
3. **Short render worker** (extend node4 or a sibling module):
   - Slice narration: ffmpeg `-ss {beat.start} -to {beat.end}` from the
     parent's `voiceover.mp3`; slice `captions.json` words in-range,
     re-based to 0.
   - Build vertical props from the parent's beats.json for that beat:
     vertical chart layout (legend below the chart, font sizes up ~1.4×),
     overlays remapped to vertical-safe positions, `hook_label` as an opening
     title card (first ~2 s).
   - Render through a `ShortFromBeat` composition (new, but assembled from
     ShortVideo's existing pieces: Captions, ComplianceOverlay, chart
     component with vertical layout props). → `QA_Final` → existing publish
     flow.
4. **Retire the legacy short-form entry point:** remove the old topic →
   `Pending_Script` creation form from the dashboard (long-form + derived
   shorts are now the only entry paths). Leave the node1/2/3 *code* in place —
   research and stock-search functions are imported by Phases 2/4 — but the
   orchestrator no longer needs to poll statuses nothing can reach; trim
   `main.py` accordingly.
5. **Distribution slimming:** delete `publish_snapchat`/`publish_x` stubs and
   their dashboard toggles + DB usage. Shorts publish via existing WoopSocial
   path (YT Shorts / IG / TT / FB per account toggles). Long-form YouTube
   upload stays **manual** in v1 (final.mp4 + generated description from
   Phase 7 are on disk/Desktop bank) — do not build a YouTube Data API
   integration in this phase.

## Verification
1. Derive a short from a chart beat → output is 1080×1920, chart legend below,
   readable at phone size; audio matches that beat's narration exactly.
2. `hook_label` title card appears in the first 2 s; captions align.
3. Old creation form gone; a derived short publishes through WoopSocial;
   `grep -n "publish_snapchat\|publish_x" Backend Frontend -r` returns nothing.