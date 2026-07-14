# Phase 7 — QA / reinjection loop, disclosure checklist, citation gate

## What exists going in
- **Stage-level reinjection already works:** the dashboard's targeted
  send-backs with notes (`reject_to_script`, `refresh_research`,
  `reject_to_assets`, `reject_to_render` in
  the `State` class in `Frontend/reflex_dashboard/state.py`) feed
  `qa_feedback` back to the generating node. Extend this pattern; don't build
  a new mechanism.
- **Citation-check pattern to reuse:** `_fact_check_storyboard()` in
  `Backend/nodes/scripting/script_quality.py` — a cheap
  Gemini flash structured-output call comparing statements against evidence.
- `compliance_metadata` column + `ComplianceOverlay` + `stamp_metadata()`
  (node4, ~lines 452–461) already stamp "AI-Assisted".
- beats.json is the single source of truth for the video's content.

## What this phase must produce
1. **Beat-level reinjection at `QA_Final` (long-form):** per-beat controls on
   the QA card — a note box plus: *Redo visuals for this beat* (re-run Phase 4
   realization for that beat only, excluding prior sources), *Edit beat text*
   (opens the beat's spoken_text; NOTE: changing spoken words requires
   re-recording that section — surface that warning, set `Awaiting_Narration`),
   and *Tweak in Studio* (instruction text pointing at beats.json). After any
   change → `Pending_LongRender` re-render. v1 re-renders the whole video from
   the updated beats.json; per-beat partial rendering is explicitly out of
   scope.
2. **Citation-match gate:** a check that runs when a long-form video enters
   `QA_Final`: one Gemini flash structured call (mirror `_fact_check_storyboard`)
   comparing every beat's `spoken_text` against the `ResearchArtifact.claims`
   (+ data_points). Store issues in `visual_qa_result`-style JSON in a new
   `citation_qa_result` column; display on the QA card; block *Approve &
   Publish* while unresolved issues exist (owner can mark false-positives
   resolved). Log cost `stage='qa'`.
3. **YouTube synthetic/altered-content disclosure checklist:** health/finance
   is sensitive-topic territory. On the long-form QA card, a required
   checklist stored as structured JSON inside `compliance_metadata`:
   - `altered_content: yes/no` (did AI generate realistic scenes/voices? —
     with this pipeline normally *no*: real voice, stock footage, charts),
   - `ai_assistance_disclosed: bool` (description text includes AI-assist note),
   - `sources_cited: bool` (description lists the artifact's sources),
   - `medical_disclaimer: bool` (education-not-advice line present).
   All four must be checked before `Ready_To_Publish` is allowed for
   long-form. Surface the stored checklist in the existing Compliance tab.
4. **Description generator:** small helper producing the YouTube description
   from the artifact (title, summary, sources with titles/URLs — reuse
   `_readable_sources()` in `Backend/nodes/publisher/node6_publisher.py`),
   stored in the `caption` column for Phase 8 to use.

## Verification
1. Rejecting one beat's visuals refetches only that beat's assets and
   re-renders; other beats' files untouched.
2. Seed a deliberate wrong number in a beat → citation gate flags it and
   publish is blocked until resolved.
3. Approve flow refuses `Ready_To_Publish` until all four checklist items are
   set; `compliance_metadata` JSON contains them afterward.