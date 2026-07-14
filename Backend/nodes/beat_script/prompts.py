"""Beat-script prompt builder for the long-form pipeline."""
import json


def revision_block(qa_feedback, previous_draft):
    """Mirror node1's revision injection so retries carry the editor's note."""
    block = ""
    if qa_feedback and qa_feedback.strip():
        block = f"""

    ⚠️  REVISION REQUEST (from human editor or QA — you MUST address this):
    "{qa_feedback.strip()}"
    Fix exactly what was flagged. Do not repeat the approach that caused the issue.
"""
    if previous_draft:
        block += f"""
    Revise this previous beat script instead of starting over:
    {previous_draft}
"""
    return block


def beat_script_prompt(topic, artifact_json, persona, revision, data_point_ids):
    """Build the single-call prompt that produces a BeatScript.

    The prompt is instruction-only (no code). It tells the LLM to produce three
    sections (intro / discussion / conclusion), ~60–65 s beats, exactly one
    primary element per beat, and to ground every factual sentence in the
    artifact's claims — never inventing numbers.
    """
    return f"""
    Task: Write a beat-tagged script for a 3–10 minute long-form YouTube video about: "{topic}".

    You are narrating in this persona:
    {persona}

    {revision}

    Here is the verified research artifact you MUST ground every factual sentence in.
    Never invent numbers. Every chart ref must be one of these data-point IDs: {json.dumps(data_point_ids)}.
    {artifact_json}

    STRUCTURE — three sections:
    1. Hook / Intro (1–3 min): open with a concrete human consequence or surprising number from the
       artifact. Establish the question the video answers. The hook must be specific and evidence-backed.
    2. Discussion (2–5 min): cover the artifact's data_points. Each beat should advance the argument —
       mechanism, comparison, or trade-off. Use charts (ref = a real DataPoint.id) when numbers clarify
       the point; use b-roll (concrete description) otherwise.
    3. Conclusion (1–3 min): pay off the intro hook directly. Return to the opening consequence or
       question and resolve it with what the evidence showed. Do not introduce new data.

    BEAT RULES:
    - Each beat is ~60–65 seconds of spoken narration (target_duration_sec 60–65).
    - spoken_text: natural spoken register in the persona's voice. Use contractions, varied sentence
      length, no stage directions, no markdown. This is exactly what the owner will narrate.
    - hook_label: a standalone one-liner that captures the beat's takeaway — it must make sense on its
      own (it becomes a short's title).
    - music_cue: a short direction, e.g. "low tension, building" or "warm resolve".
    - elements: exactly ONE primary element per beat, plus at most 1–2 overlays.
      * Primary must be either:
        - kind="chart" with ref = a real DataPoint.id from the artifact (use charts when the beat
          discusses comparable numbers), OR
        - kind="broll" with a concrete, filmable description (2–5 words, e.g. "hospital billing desk close-up").
      * Overlays (optional, 0–2): kind="meme" or "text_callout" with a concrete description. These sit
        on top of the primary visual. Use sparingly — only when a callout genuinely aids comprehension.
    - At least one beat MUST visualize a data point (chart with a valid ref).
    - Ground every factual sentence in the artifact's claims. If a number appears in spoken_text, it must
      come from a claim or data_point in the artifact. Do not round, convert, or paraphrase numbers loosely.

    DURATION:
    - Total duration must be 180–600 seconds (3–10 min).
    - Word rate per beat should be ~2.0–3.0 words/sec vs target_duration_sec. A 60-second beat has
      roughly 120–180 spoken words.

    OUTPUT: a single JSON object matching the BeatScript schema. The `beats` array is ordered by `order`
    (0, 1, 2, …). Each beat's `section` is "intro", "discussion", or "conclusion". The intro beats come
    first, discussion in the middle, conclusion last.
    """