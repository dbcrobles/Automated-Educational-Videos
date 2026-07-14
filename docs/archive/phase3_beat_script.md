# Phase 3 — Script phase: single-call beat-tagged script

## What exists going in
- `research_artifact` column (Phase 2) validating against `ResearchArtifact`.
- **Prompt scaffolding to reuse:** `Backend/nodes/scripting/node1_scripting.py`
  (prompt text itself lives in `Backend/nodes/scripting/prompts.py` — put your
  beat-script prompt there too)
  — `generate_script()` shows how personas load from `accounts_config.json`
  (`system_instruction`), how revision notes (`qa_feedback`) and a previous
  draft are injected, and how structured output is requested from OpenAI
  (`_openai_storyboard`, with real token-cost accounting) with a Gemini
  fallback. The QA/repair loop in `run()` (issues → bounded auto-retry with
  `qa_feedback` → cost caps) is the pattern to copy.
- **Contract (Phase 1, done):** `Backend/schemas/beat.py` — `BeatScript`,
  `Beat`, `ElementCue`.

## What this phase must produce
1. **Worker:** `Backend/nodes/beat_script/node1b_beat_script.py`, `run()`
   polling `Pending_BeatScript`. **One LLM call per video** (default the same
   OpenAI model node1 uses, Gemini fallback; if the video's
   `use_degraded_model` flag is set, use `pipeline_config.json`'s
   `degraded_model`). Structured output = `BeatScript.model_json_schema()`.
2. **The prompt must instruct** (give the outline as instructions, not code):
   - Three sections: hook/intro 1–3 min; discussion 2–5 min that covers the
     artifact's `data_points`; conclusion 1–3 min that pays off the intro hook.
   - Beats of ~60–65 s each; per beat: `spoken_text` (natural spoken register,
     the owner's persona from `accounts_config.json`), `music_cue`,
     `hook_label` (standalone one-liner), and `elements`: exactly one primary
     (`chart` with `ref` = a real `DataPoint.id`, or `broll` with a concrete
     description) plus at most 1–2 obvious overlays (meme/text_callout).
   - Ground every factual sentence in `claims`; never invent numbers.
3. **Deterministic QA before accepting** (no extra LLM call):
   - `BeatScript` validates; total duration 180–600 s; word-rate sanity
     (~2.0–3.0 words/sec per beat vs `target_duration_sec`).
   - Every chart `ref` exists in the artifact's `data_points`; at least one
     data point is visualized.
   - On issues: bounded auto-retry with the issue list as `qa_feedback`
     (copy node1's retry pattern, max 3), respecting `log_cost` →
     `pause_for_cost` on `'hard'`.
4. **Persistence + dashboard:** store JSON in a new `beat_script` column
   (add to `migrate()`); status → `QA_BeatScript`. Dashboard card: render
   beats as readable sections (spoken text, duration, hook_label, element
   summary); *Approve →* `Pending_Storyboard`; *Rewrite with note* → back to
   `Pending_BeatScript` with `qa_feedback` (mirror `reject_to_script`).
5. Register the worker in `main.py`.

## Escalation test (do this, record it, build nothing further)
Run 3–5 real medical-economics topics end-to-end to `QA_BeatScript`. For each,
note in `docs/briefs/phase3_test_log.md`: (a) numbers/claims drifting from the
artifact, (b) conclusion failing to pay off the intro hook, (c) tonal
inconsistency across sections. **Split-call generation is built only if the
log shows these symptoms — and that would be a new brief, not this one.**

## Verification
`BeatScript.model_validate_json(row['beat_script'])` passes; all chart refs
resolve; `cost_events` has `stage='beat_script'` rows; test log committed.

## Out of scope
Split-call orchestration; counterpoint sections (one extra call, later, only
when a topic warrants); storyboard realization.