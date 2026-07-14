# Phase 4 Handoff — DeepSeek UI Boilerplate Only

## Critical code already complete — do not rewrite it
- `Backend/nodes/storyboard/node3b_storyboard.py` realizes charts and 2–3 b-roll
  candidates, stores candidate source IDs for reliable re-fetch exclusion, writes
  `Backend/assets/{video_id}/beats.json`, checkpoints `beats_json`, then advances
  to `QA_Storyboard`.
- `Backend/nodes/asset_fetcher/node3_asset_fetcher.py` supports landscape-first
  stock lookup without changing the legacy default and does not use Veo here.
- `Frontend/reflex_dashboard/longform_state.py` is the Reflex mixin containing
  `approve_storyboard`, `reject_storyboard`, and `select_broll_candidate`.
  `State` inherits it; keep UI calls in the form `State.method(...)`.
- The runtime asset link is already prepared. A selected b-roll path such as
  `beats/beat_1_0_0.mp4` is previewable at
  `/storyboards/{video.id}/{el['src']}`; do not copy media into the frontend.
- Statuses, `VideoModel.storyboard_beats`, safe DB loading, database migration,
  worker registration, badges, and the in-progress exclusion are already wired.

## Your task: add only the storyboard card boilerplate

### 1. `Frontend/reflex_dashboard/panels.py`
Add `storyboard_panel(video: VideoModel)` beside `beat_script_panel()`. Return an
`rx.cond(video.status == "QA_Storyboard", ...)` containing:

- Header: `🖼️ Storyboard Review` and the number of beats.
- For every `video.storyboard_beats` entry, show `beat["hook_label"]` and
  `beat["spoken_text"]`.
- For every `beat["elements"]` entry:
  - `chart`: show `el["chart"]["title"]`, unit, and each point as
    `label: value`. A chart summary is sufficient; do not add chart rendering.
  - `broll`: show the selected clip with
    `rx.video(src=f"/storyboards/{video.id}/{el['src']}", controls=True)`,
    then `rx.radio` using `el["candidates"]`, `value=el["src"]`, and
    `on_change=lambda candidate: State.select_broll_candidate(
    video.id, beat["order"], candidate)`.
  - Any `realized == false`: show exactly
    `Unrealized — add in Remotion Studio`.
- Add this callout verbatim:
  `Fine-tune overlays in Remotion Studio: cd Backend/remotion && npm run dev`
- Add a rejection note textarea using
  `State.set_rejection_note(video.id, value)`, then buttons:
  - `✅ Approve → Narration` → `State.approve_storyboard(video.id)`
  - `↺ Refetch Visuals` → `State.reject_storyboard(video.id)`
  - `🗑 Delete` → `State.delete_video(video.id)`

Keep this as presentation code. Do not move handlers back into `state.py`, alter
the locked schemas, change `beats.json`, or add API calls.

### 2. `Frontend/reflex_dashboard/components.py`
- Import `storyboard_panel` from `.panels`.
- Render `storyboard_panel(video)` immediately after `beat_script_panel(video)`.

## Verification after the UI edit
```bash
PYTHONPATH="Backend:Frontend" .venv/bin/python -c "import reflex_dashboard.components; print('Frontend import: OK')"
.venv/bin/python -c "import ast; [ast.parse(open(f).read()) for f in ['Frontend/reflex_dashboard/panels.py','Frontend/reflex_dashboard/components.py']; print('Frontend AST: OK')"
wc -l Frontend/reflex_dashboard/panels.py Frontend/reflex_dashboard/components.py Frontend/reflex_dashboard/state.py Frontend/reflex_dashboard/longform_state.py
```
Every source file must remain under 800 lines.