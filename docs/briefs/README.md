# Phase Briefs — read this first (every GLM-5.2 Act session)

## What this project is
A config-driven pipeline that turns a research topic into a **3–10 minute,
owner-narrated (real voice, no TTS), chart-driven landscape YouTube video**
(Fireship pacing × RealLifeLore data-viz), then extracts vertical shorts from
its beats. Backend = Python workers polling SQLite by status (`Backend/main.py`);
Frontend = Reflex dashboard (`Frontend/reflex_dashboard/reflex_dashboard.py`);
rendering = Remotion (`Backend/remotion/`). The legacy short-form pipeline
(nodes 1–6) stays functional until Phase 8 folds it in — do not break it.

## File layout (refactored — look here first)
- `Backend/nodes/research/researcher.py` — the automated researcher (4 Gemini
  passes) + `ResearchDossier` models. Prompts in `Backend/nodes/research/prompts.py`.
- `Backend/nodes/scripting/node1_scripting.py` — Node 1 orchestrator only
  (`generate_script`, `run`). QA/repair helpers in `script_quality.py`;
  storyboard prompt text in `Backend/nodes/scripting/prompts.py`.
- `Frontend/reflex_dashboard/state.py` — State class, `VideoModel`,
  `PIPELINE_STAGES`, `STATUS_META` (single source of truth for statuses).
- `Frontend/reflex_dashboard/components.py` — `status_badge`, video cards,
  research panel. `reflex_dashboard.py` — tabs + `app` only.

## Session rules
1. **Confirm the active model out loud in your first message** (the owner sets
   it by hand; it should be GLM-5.2 for these briefs).
2. **Extend, don't replace.** Reuse the referenced existing functions.
3. **One brief per session.** Do not start the next phase's work.
4. **The schemas are the contract**: `Backend/schemas/research_artifact.py` and
   `Backend/schemas/beat.py`. Do not change them; if a brief seems to require a
   schema change, stop and flag it to the owner instead.
5. **Log every paid API call** via `database.log_cost(video_id, usd, stage,
   provider=, model=, tokens_in=, tokens_out=)`. If it returns `'hard'`, call
   `database.pause_for_cost(video_id, stage)` and stop processing that video
   (never delete anything). `'soft'` is informational only.
6. Run the brief's **Verification** section before declaring done.
7. **Code hygiene is binding**: keep every source file under 800 lines. If
   your change would push a file past it, split it (state/components/prompts
   pattern above) as part of the same session. Put long prompt strings in the
   module's `prompts.py`, never inline. Run `wc -l` on touched files before
   declaring done.
8. **Tool discipline**: if the same tool call fails twice in a row, stop and
   re-read the file/tool format before retrying. Avoid terminal commands
   expected to take >25 seconds; if a command produces no output for ~25s,
   abandon it and take a different approach.
9. **Offer a git commit + push after each completed brief.**

## Long-form status flow (add statuses only as your phase needs them)
```
Pending_Research → QA_Research → Pending_BeatScript → QA_BeatScript
→ Pending_Storyboard → QA_Storyboard → Awaiting_Narration
→ Pending_LongRender → QA_Final → Ready_To_Publish → Published
(any stage may enter Paused_Cost or Failed)
```
New statuses must be added to `PIPELINE_STAGES` / `STATUS_META` (in
`Frontend/reflex_dashboard/state.py`) and `status_badge()` (in
`Frontend/reflex_dashboard/components.py`) so cards render correctly.

## Key shared code (Phase 1, already written — import, don't rewrite)
- `Backend/schemas/` — `ResearchArtifact` (+ `from_dossier()`), `Beat`,
  `BeatScript`, `ElementCue` (layered visuals: one primary + overlays).
- `Backend/database/database.py` — `log_cost`, `cost_status`, `pause_for_cost`,
  `cost_events` table; `Backend/pipeline_config.json` holds the $2.50 soft /
  $4.00 hard video-level tiers and the `degraded_model`.

## Brief order
| Phase | File | Depends on |
|---|---|---|
| 2 | `phase2_draft.md` | Phase 1 |
| 3 | `phase3_beat_script.md` | Phase 2 |
| 4 | `phase4_storyboard.md` | Phase 3 |
| 5 | `phase5_narration.md` | Phase 4 |
| 6 | `phase6_remotion_longform.md` | Phase 5 |
| 7 | `phase7_qa_reinjection.md` | Phase 6 |
| 8 | `phase8_shorts_distribution.md` | Phase 7 |