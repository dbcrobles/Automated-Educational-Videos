"""Storyboard prompt builders (moved verbatim from node1_scripting.py)."""
import json

VIBES = [
    "Paradox reveal: open with a result that appears impossible, then resolve it step by step.",
    "Evidence case file: present clues, eliminate the obvious explanation, and land on the strongest finding.",
    "Human-impact lens: follow one relatable person, then widen out to the system and the data.",
    "Escalating stakes: move from a small everyday consequence to the surprising larger consequence.",
    "Then-versus-now timeline: use sharp turning points to show how the situation changed.",
    "Myth versus mechanism: state the common belief fairly, then reveal what actually drives the outcome.",
    "Side-by-side comparison: contrast two choices or systems using concrete numbers and consequences.",
    "Reverse countdown: rank three evidence-backed findings, saving the most counter-intuitive for last."
]


def revision_block(qa_feedback, previous_draft):
    block = ""
    if qa_feedback and qa_feedback.strip():
        block = f"""

    ⚠️  REVISION REQUEST (from human editor — you MUST address this):
    "{qa_feedback.strip()}"
    Specifically correct or improve what the editor described above.
    Do not repeat the same approach that caused the rejection.
"""
    if previous_draft:
        block += f"""
    Revise this previous storyboard instead of starting over:
    {previous_draft}
"""
    return block


def storyboard_prompt(topic, revision, selected_vibe, dossier, catalog, cta_text):
    return f"""
    Task: Write a master storyboard for a 65-100 second mobile-optimized video about: "{topic}".
    {revision}
    Story Structure Constraint: {selected_vibe}

    Here is the verified research dossier you MUST use to build the script:
    {json.dumps(dossier, indent=2)}

    Here is the complete rights-cleared local media catalog available to this video:
    {json.dumps(catalog, indent=2)}

    Content Philosophy:
    Sound unmistakably like the account persona in the system instruction. Use the assigned story structure
    without changing the persona's ethics or vocabulary. Avoid generic setup, fake controversy, unnamed
    authorities, hype, and robotic transitions. Every sentence must advance the argument or story.

    Formatting Rules & Pipeline Constraints:
    1. Narration: Write exactly what the voice should speak. Use natural contractions, varied sentence length,
       clean pronunciation, and no stage directions. A scene's words must fit its assigned duration.
    2. Intentional Duration: Assign `duration_seconds` from 2-12 seconds per scene. Scene 1 is a special
       2-3 second hook beat with no more than 8 spoken words. Its first word starts the hook immediately—no
       greeting, topic label, throat-clearing, or delayed setup. The scene durations MUST
       total 65-100 seconds. Use 2-3.5s scenes for punchy facts or pattern interrupts, 4-7s for explanation,
       and 8-12s sparingly for the central mechanism, emotional turn, or climax. Include at least one short
       scene and one 7s+ scene; do not make every scene nearly equal.
    3. Scene Visual Types: Stock remains the fallback for every scene. `visual_search_queries` is an
       ordered list of 1-3 literal searches. A scene may also use one chart, one licensed-media excerpt,
       or both when they genuinely clarify the narration.
    4. Stock Video Queries: `visual_search_queries` entries must each be 2-5 concrete words. Scene 1's primary
       query must show the hook's concrete consequence or action—not a generic establishing shot.
       Each query must be 2-5 concrete words describing a filmable subject in motion, such as
       "nurse walking hospital" or "hands counting cash". Never include labels, slashes, camera instructions,
       abstractions, brand names, or prose. Query 1 is the ideal visual; queries 2-3 are progressively broader,
       visually related fallbacks and may become cutaways. Give at least two queries to selected 5s+ scenes.
       Search behavior is cache → portrait/broad stock video → stock still → Veo. Broad fallbacks must remain
       relevant rather than merely producing any available footage.
    5. Licensed Media: You may select `licensed_media` ONLY by an exact `media_id` in the supplied catalog.
       Never put a web URL there. Use `source_audio` only when the catalog permits original audio; that scene's
       `narration` MUST be an empty string and its duration must fit the approved window. Otherwise use
       `muted_under_narration`. Excerpts must add evidence or analysis, not decoration.
    6. Charts: Use `chart` only for useful numbers explicitly present in the evidence ledger. Copy values
       exactly; include the exact evidence URL and a short source label. Use pie only for true parts of a whole
       whose values total approximately 100. Use bars for category comparison and lines for ordered change
       over time. Use 2-6 non-negative data points and no more than two charts in the video. If the dossier has
       a chart-recommended claim with 2+ `chart_points`, the storyboard MUST visualize at least one such set.
       Also use a chart when narrating two or more comparable metrics from the same source and unit. Do not
       place a chart over a source-audio excerpt or use a decorative chart for an isolated number.
    7. Dynamic Pacing: For every scene, assign a `pacing_style`:
       - 'rapid': Use for high-tension montages, chaotic moments, or rapid-fire facts.
       - 'standard': Use for normal explanatory dialogue.
       - 'slow_pan': Use sparingly for dramatic breathing room, profound statements, or establishing shots.
    8. Transition Hints: Prefer `crossfade` or `dissolve`. Use `whip_pan`, `zoom_punch`, or `dip_to_black`
       only when a specific narrative turn justifies it, never merely for variety. No more than two stylized
       transitions in the whole video.
    9. Editing Directives: Every scene needs `editing_directives` with exactly one allowed value per field:
       - camera_movement: 'static', 'gentle_push_in', 'slow_zoom_out', or 'shake'
       - color_grade_hint: 'warm', 'clinical_cool', 'desaturated', or 'high_contrast'
       - audio_emphasis: 'voiceonly', 'music_pedestal', or 'sfx_drop'
       - sound_effect: 'none', 'impact', 'whoosh', or 'chime'
       - caption_style: 'bottom_center', 'top_left', 'keyword_emerge', or 'full_text'
       Restraint is the default: use static or gentle movement, voice-led audio, and `sound_effect='none'`.
       Use at most two non-consecutive sound effects in the entire video, and only when the sound has a clear
       semantic purpose. Never add an effect just to satisfy variety. Never use `shake` for ordinary exposition.
       Every scene with a sound effect uses sfx_drop; other scenes normally use sound_effect='none'.
    10. Music Mood: Choose one whole-video mood: 'tense', 'uplifting', 'mysterious', or 'neutral'.
    11. Word-Count Gate: Spoken narrator words must total 160-260 and fit the duration plan. Empty
        source-audio scenes do not count. Report the true count.
    12. CTA Injection: The final narration MUST end with this exact text: "{cta_text or 'Follow for more'}"
    13. Hook: Scene 1 MUST include `hook` with `hook_type` (question, statistic, controversy, or promise)
        and `hook_text` exactly matching the opening spoken words. Later scenes should omit the hook.
    14. Hook & Retention QA: Score `hook_score` from 0-10 and estimate `retention_estimate` as a percentage.
        Be harsh: a generic hook is 4. Passing requires 7.5+. The first 3 seconds need an immediate
        evidence-backed spoken hook, a matching concrete visual, and readable emphasis captions. An audio
        pattern interrupt is optional, not required. Every later scene must advance, explain, contrast, or resolve it.
    15. Evidence currentness is binding: never use an item marked `do_not_use`. A `dated_context` item
        MUST be spoken with its explicit year/period and cannot be phrased as current. Only `current_fact`
        items may be stated as true now. Preserve qualifiers, denominators, populations, and causal limits.
        Use only claims supported by the dossier. Put only exact canonical `source_url` values in `sources`.

    Output strictly as a JSON object matching the requested schema.
    """