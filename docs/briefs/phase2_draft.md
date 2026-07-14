# Phase 2 — Draft phase: two research paths, one artifact

## What exists going in
- **Automated researcher (DONE — already extracted):** `Backend/nodes/research/researcher.py`
  holds `_build_research_dossier()` and its helpers (`_deep_research`,
  `_audit_currentness`, `_normalize_dossier`, `_research_quality_issues`, the
  `ResearchDossier` Pydantic models). Prompt text lives in
  `Backend/nodes/research/prompts.py`. It runs 4 Gemini passes
  (scout → curate → deep dive → currentness audit) and already logs spend via
  `database.add_script_cost`. `node1_scripting.py` imports from it — do NOT
  move these functions again; import them.
- **Converter (Phase 1, done):** `Backend/schemas/research_artifact.from_dossier(dossier, topic)`
  turns a `ResearchDossier` dict into a `ResearchArtifact`.
- **Dashboard creation form:** `add_video()` in
  `Frontend/reflex_dashboard/state.py` (State class) inserts rows with
  status `Pending_Script` (the legacy short-form entry — leave it working).
  The dashboard is split across three files: `state.py` (State + models +
  `PIPELINE_STAGES`/`STATUS_META`), `components.py` (`status_badge`, cards),
  and `reflex_dashboard.py` (tabs + app).

## What this phase must produce
1. **DB columns** (add to the `migrations` list in `database.migrate()`):
   `("format", "TEXT DEFAULT 'short'")` and `("research_artifact", "TEXT")`.
2. **Research worker:** `Backend/nodes/research/node0_research.py` with a
   `run()` polling `fetch_videos_by_status('Pending_Research')`.
   - Import the researcher from `Backend/nodes/research/researcher.py`
     (the extraction step is already done — this is now just an import).
   - Worker calls the researcher, converts via `from_dossier()`, stores JSON in
     `research_artifact`, keeps the raw dossier in `research_dossier` (reuse),
     sets status `QA_Research`.
   - Log spend with `log_cost(..., stage='research')`; on `'hard'` return,
     `pause_for_cost()` and continue to the next video.
   - Register `node0_research.run()` in the `main.py` loop.
3. **Manual paste path (dashboard):** a "Long-form video" creation section:
   topic input + choice of *Automated research* (→ `Pending_Research`) or
   *Paste Deep Research export* (a text area). The paste path makes ONE
   Gemini `gemini-3.5-flash` structured-output call with
   `response_schema=ResearchArtifact` (mirror the pattern in `add_video`'s
   batch-split call in `state.py`), sets `origin='manual_deep_research'`,
   stores the JSON, sets status `QA_Research`. Log its cost too
   (`stage='research'`). Do NOT integrate any Gemini deep-research/Interactions API.
4. **QA_Research card (dashboard):** show claims (text + linked sources) and
   data points (label, unit, values); buttons: *Approve →* set
   `Pending_BeatScript`; *Re-run research* (automated path) or *Re-paste*
   (manual). Add the new statuses to `PIPELINE_STAGES`/`STATUS_META` in
   `state.py` and `status_badge()` in `components.py`, plus `Paused_Cost`
   badge and a card that shows the three choices
   (continue / degrade / stop-and-keep — continue and stop can just set status;
   degrade sets a `use_degraded_model` flag column for later stages).
   New state fields/handlers go in `state.py`; new card UI goes in
   `components.py`; keep every file under 800 lines.

## Contract
`research_artifact` column must validate against
`schemas.research_artifact.ResearchArtifact` for BOTH paths.

## Verification
1. Create a long-form video via the automated path → row reaches `QA_Research`,
   `ResearchArtifact.model_validate_json(row['research_artifact'])` passes,
   `cost_events` has `stage='research'` rows.
2. Paste a sample Deep Research text → same checks, `origin='manual_deep_research'`.
3. A legacy short-form video still flows `Pending_Script → QA_Script` untouched.
4. `wc -l` on every touched file stays under 800 lines.

## Out of scope
Beat-script generation (Phase 3); GPT Researcher (deliberately deferred — the
existing researcher was audited as sufficient).