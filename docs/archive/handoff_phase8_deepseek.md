# Handoff: Phase 8 — ShortFromBeat.tsx (Remotion composition)

## Context (Python side is DONE — do not touch it)
`Backend/nodes/render_worker/short_from_beat.py` already slices the parent's
narration + captions, copies/preps the beat's element media into the short's
asset folder, and writes `assets/{id}/comp_short.json`. It renders with:

```
npx remotion render src/index.ts ShortFromBeat out.mp4 --props comp_short.json
```

Your job is ONLY the Remotion side, in `Backend/remotion/src/`:
1. Create `ShortFromBeat.tsx` (1080×1920 vertical).
2. Extend `ChartOverlay.tsx` with a `layoutMode?: "horizontal" | "vertical"`
   prop (default "horizontal", zero change to existing callers).
3. Register the composition in `Root.tsx` (see how `ShortVideo` / `LongVideo`
   are registered with `calculateMetadata` from props).

## Exact props contract (what comp_short.json contains)
```jsonc
{
  "fps": 30, "width": 1080, "height": 1920,
  "durationInFrames": 1830,               // beat length × fps (audio runs frame 0 → end)
  "assetBase": "42",                       // staticFile folder for this short's media
  "introCard": { "text": "One-line hook_label", "durationInFrames": 60 },
  "voiceoverSrc": "42/voiceover.mp3",      // already sliced to the beat
  "captions": [ { "word": "The", "start": 0.0, "end": 0.21 }, ... ],  // seconds, re-based to 0
  "elements": [                            // same shape LongVideo.tsx consumes
    { "kind": "chart", "role": "primary", "chart": { ...ChartSpec... },
      "start_offset_sec": 0, "duration_sec": null, "position": "full", "animation": "..." },
    { "kind": "meme", "role": "overlay", "src": "short_el_1.png",
      "position": "lower_third", ... }
  ],
  "layoutMode": "vertical",
  "accentColor": "#FFD447",
  "compliance": { "text": "AI-Assisted", "fullDuration": true }
}
```
Notes:
- Element `src` values are relative to `assetBase` (use
  `staticFile(`${assetBase}/${src}`)`), already normalized: mp4s pre-scaled to
  1080×1920, images copied as-is.
- Overlay positions were already remapped to vertical-safe values by Python
  (`upper_third` / `lower_third` / `center` / `full`).

## What ShortFromBeat must render (reuse, don't rewrite)
1. `<Audio src={staticFile(voiceoverSrc)} />` from frame 0.
2. Element stack for the whole duration — copy the per-element rendering
   pattern from `LongVideo.tsx` (primary background + overlays with
   `start_offset_sec` / `duration_sec` windows and animation presets from
   `animations.ts`), but at 1080×1920.
3. Chart elements render through `ChartOverlay` with `layoutMode="vertical"`.
4. `introCard`: for the first `introCard.durationInFrames` frames, overlay
   `introCard.text` as bold white text (Montserrat, the loaded font) centered
   on a dark 80%-opacity backdrop covering the frame; fade it out over the
   last ~10 frames. Audio/captions keep playing underneath.
5. Captions: reuse `Captions.tsx` word-by-word overlay (convert `start`/`end`
   seconds → frames like LongVideo does); place them in the lower third,
   sized for phone readability.
6. `ComplianceOverlay` with `compliance.text` for the full duration.

## ChartOverlay `layoutMode: "vertical"` requirements
- Legend moves BELOW the chart area (row-wrapped, centered) instead of the
  side placement.
- All font sizes × 1.4 (title, axis labels, legend).
- Chart drawing area uses the full 1080 width minus existing padding; keep
  the aspect sensible for a 9:16 canvas (chart ≈ upper 55–60% of the safe
  area, legend below).
- Default `layoutMode="horizontal"` must leave current LongVideo/ShortVideo
  rendering pixel-identical.

## Verification (run before declaring done)
1. `cd Backend/remotion && npx tsc --noEmit` passes.
2. `npx remotion compositions src/index.ts` lists `ShortFromBeat`.
3. Render a test with sample props (adapt `sampleLongProps.json`: one chart
   beat's elements + a few caption words) → output is 1080×1920, legend below
   the chart, hook_label card visible for the first 2 s.