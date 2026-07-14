# Remotion — Long-Form Video Renderer

## Studio Preview (hot-reload)
```bash
cd Backend/remotion && npm run dev
```
Opens Remotion Studio at http://localhost:3000. Select **LongVideo** from the composition dropdown.

## Point to a Real Video
To preview a pipeline-produced video, copy its `beats.json` from `Backend/assets/{id}/beats.json` into the Studio props editor, or edit the file directly in your editor — node4 reads `Backend/assets/{id}/beats.json` at render time.

## Animation Presets
Overlay elements can use these `animation` values in beats.json:
- `fade` — opacity fade-in over 0.3 s
- `pop_in` — spring scale + fade (0.15 s)
- `slide_up` — slide upward with easing (0.35 s)
- `shake` — horizontal shake (0.6 s)

Unknown values fall back to `fade`. See `src/animations.ts`.

## Verification Render
```bash
npx remotion render src/index.ts LongVideo out.mp4 --props=src/sampleLongProps.json
```

## File Layout
- `src/LongVideo.tsx` — main composition (1920×1080 @ 30fps)
- `src/Captions.tsx` — word-level captions layer
- `src/ChartOverlay.tsx` — animated pie/bar/line charts
- `src/animations.ts` — overlay entrance presets