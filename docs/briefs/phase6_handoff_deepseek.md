# Phase 6 handoff → DeepSeek v4 Flash (boilerplate only)

Core Phase 6 is implemented and verified (LongVideo composition, animations.ts,
node4 `Pending_LongRender` path, sample render passes). The items below are
low-risk boilerplate — do NOT touch pipeline logic or schemas.

## Relevant files (read only these)
- `Backend/remotion/src/LongVideo.tsx` — header comment documents the Studio workflow
- `Backend/remotion/src/animations.ts` — the four presets
- `README.md` — "Long-form editing workflow" section (source of truth for wording)
- `Backend/remotion/src/sampleLongProps.json` — sample props / captions

## Tasks
1. `Backend/remotion/README.md` (new, ≤40 lines): expand the root README's
   workflow section into a quick-reference for the owner — Studio launch
   command, how to point LongVideo at a real `Backend/assets/{id}/beats.json`,
   the four animation preset names, and the verification render command:
   `npx remotion render src/index.ts LongVideo out.mp4 --props=src/sampleLongProps.json`.
2. Optional: extend `captions` in `sampleLongProps.json` so every beat has
   continuous word coverage (keep timings inside each beat's start/end; do not
   change beats, elements, or chart values).

## Constraints
- No new dependencies, no TypeScript config changes, no test files.
- Keep every file under 800 lines.