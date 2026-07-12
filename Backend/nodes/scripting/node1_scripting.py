import os
import sys
import json
import time
import random
import re
import math
import requests
from typing import Literal, Optional
from urllib.parse import parse_qsl, urlsplit
from pydantic import BaseModel, Field
from google import genai
from google.genai import types

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from database import database

COST_SCOUT_CALL = 0.03
COST_CURATE_CALL = 0.01
COST_DEEP_RESEARCH_CALL = 0.05
COST_SCRIPT_CALL = 0.01

GEMINI_MODEL_RESEARCH = "gemini-3.1-pro-preview"
GEMINI_MODEL_STRUCTURED = "gemini-3.5-flash"

VALID_PACING = {"rapid", "standard", "slow_pan"}
VALID_TRANSITIONS = {"whip_pan", "zoom_punch", "crossfade", "dissolve", "dip_to_black"}
VALID_MOODS = {"tense", "uplifting", "mysterious", "neutral"}
VALID_CAMERA_MOVEMENTS = {"static", "gentle_push_in", "slow_zoom_out", "shake"}
VALID_COLOR_GRADES = {"warm", "clinical_cool", "desaturated", "high_contrast"}
VALID_AUDIO_EMPHASIS = {"voiceonly", "music_pedestal", "sfx_drop"}
VALID_CAPTION_STYLES = {"bottom_center", "top_left", "keyword_emerge", "full_text"}
APPROVED_RIGHTS = {"owned", "licensed", "permission", "public_domain"}
ASSETS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'assets')

def load_accounts_config():
    config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'accounts_config.json')
    with open(config_path, 'r') as f:
        return json.load(f)

class Hook(BaseModel):
    hook_type: Literal["question", "statistic", "controversy", "promise"]
    hook_text: str

class EditingDirectives(BaseModel):
    camera_movement: Literal["static", "gentle_push_in", "slow_zoom_out", "shake"]
    color_grade_hint: Literal["warm", "clinical_cool", "desaturated", "high_contrast"]
    audio_emphasis: Literal["voiceonly", "music_pedestal", "sfx_drop"]
    caption_style: Literal["bottom_center", "top_left", "keyword_emerge", "full_text"]

class AnchorArticle(BaseModel):
    title: str
    url: str
    source_type: str
    selection_reason: str

class AnchorSelection(BaseModel):
    anchors: list[AnchorArticle]

class EvidenceClaim(BaseModel):
    claim: str
    source_url: str
    population_or_geography: str
    date_or_period: str
    caveat: str
    numeric_value: Optional[float] = None
    unit: Optional[str] = None
    chart_recommended: bool

class ResearchDossier(BaseModel):
    thesis: str
    anchors: list[AnchorArticle]
    evidence_ledger: list[EvidenceClaim]
    related_sources: list[str]
    tensions_or_unknowns: list[str]

class ChartPoint(BaseModel):
    label: str
    value: float

class ChartSpec(BaseModel):
    chart_type: Literal["pie", "bar", "line"]
    display_mode: Literal["overlay", "full_screen"]
    title: str
    unit: str
    points: list[ChartPoint]
    highlight: str
    source_url: str
    source_label: str

class LicensedMediaSpec(BaseModel):
    media_id: str
    playback_mode: Literal["muted_under_narration", "source_audio"]
    display_mode: Literal["full_screen", "picture_in_picture"]

class Scene(BaseModel):
    visual_search_queries: list[str]
    narration: str
    duration_seconds: float = Field(ge=2, le=12)
    pacing_style: Literal["rapid", "standard", "slow_pan"]
    transition_hint: Literal["whip_pan", "zoom_punch", "crossfade", "dissolve", "dip_to_black"]
    editing_directives: EditingDirectives
    chart: Optional[ChartSpec] = None
    licensed_media: Optional[LicensedMediaSpec] = None
    hook: Optional[Hook] = None

class ScriptOutput(BaseModel):
    title: str
    word_count: int
    hook_score: float
    retention_estimate: float
    music_mood: Literal["tense", "uplifting", "mysterious", "neutral"]
    scenes: list[Scene]
    sources: list[str]

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

def _grounding_urls(response):
    """Extract source URLs supplied by Gemini's Google Search grounding metadata."""
    try:
        metadata = response.candidates[0].grounding_metadata
        chunks = metadata.grounding_chunks or []
    except (AttributeError, IndexError, TypeError):
        return []
    urls = []
    for chunk in chunks:
        uri = getattr(getattr(chunk, 'web', None), 'uri', None)
        if uri and uri not in urls:
            urls.append(uri)
    return urls

def _url_key(url):
    """Normalize harmless URL variations without changing the URL used as evidence."""
    parsed = urlsplit(str(url or '').strip())
    query = tuple(sorted(
        (key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.lower().startswith('utm_')
        and key.lower() not in {'fbclid', 'gclid', 'mc_cid', 'mc_eid'}
    ))
    return (parsed.netloc.lower().removeprefix('www.'), parsed.path.rstrip('/') or '/', query)

def _retrieval_statuses(response, requested_urls):
    """Map each requested URL to its URL Context status, tolerating redirects."""
    try:
        metadata = response.candidates[0].url_context_metadata
        entries = metadata.url_metadata or []
    except (AttributeError, IndexError, TypeError):
        entries = []
    records = [
        (
            _url_key(entry.retrieved_url),
            str(getattr(entry.url_retrieval_status, 'value', entry.url_retrieval_status)).upper(),
        )
        for entry in entries
    ]
    by_url = dict(records)
    return {
        url: by_url.get(
            _url_key(url),
            records[index][1] if len(records) == len(requested_urls) else 'NOT_REPORTED',
        )
        for index, url in enumerate(requested_urls)
    }

def _validated_anchors(selection, candidate_urls, excluded_urls=()):
    """Keep curator choices tied to the scout's real URLs and optional exclusion list."""
    candidates = {_url_key(url): url for url in candidate_urls}
    excluded = {_url_key(url) for url in excluded_urls}
    validated = []
    for anchor in selection:
        key = _url_key(anchor.get('url'))
        if key in candidates and key not in excluded:
            anchor = dict(anchor)
            anchor['url'] = candidates[key]
            validated.append(anchor)
    return validated[:2]

def _resolve_doi_anchors(anchors):
    """Replace DOI resolver links with their public article destinations when available."""
    resolved = []
    for anchor in anchors:
        anchor = dict(anchor)
        if urlsplit(anchor['url']).netloc.lower().removeprefix('www.') == 'doi.org':
            try:
                response = requests.get(anchor['url'], allow_redirects=True, stream=True, timeout=8)
                if response.ok and urlsplit(response.url).netloc.lower() != 'doi.org':
                    anchor['url'] = response.url
                response.close()
            except requests.RequestException as error:
                print(f"Node 1: DOI resolution skipped for {anchor['url']}: {error}")
        resolved.append(anchor)
    return resolved

def _retrieval_failures(statuses, research_text):
    """Reject explicit failures; missing optional metadata is inconclusive, not fatal."""
    dossier_urls = {_url_key(url) for url in _urls_from_text(research_text)}
    explicit_failures = ('ERROR', 'PAYWALL', 'UNSAFE')
    return {
        url: status for url, status in statuses.items()
        if status.endswith(explicit_failures)
        or (status == 'NOT_REPORTED' and _url_key(url) not in dossier_urls)
    }

def _load_approved_media_catalog():
    """Return rights-cleared local media entries; absent catalog means stock/charts only."""
    catalog_path = os.path.join(ASSETS_DIR, 'source_media', 'catalog.json')
    if not os.path.exists(catalog_path):
        return []
    try:
        with open(catalog_path) as f:
            data = json.load(f)
        entries = data.get('media', []) if isinstance(data, dict) else data
    except Exception as e:
        print(f"Node 1: source media catalog ignored: {e}")
        return []

    source_dir = os.path.realpath(os.path.dirname(catalog_path))
    approved = []
    seen_ids = set()
    for entry in entries:
        filename = str(entry.get('filename', ''))
        local_path = os.path.realpath(os.path.join(source_dir, filename))
        platforms = entry.get('allowed_platforms', [])
        valid_window = entry.get('approved_end_seconds', 0) > entry.get('approved_start_seconds', 0)
        required_metadata = all(entry.get(key) for key in (
            'id', 'source_name', 'creator', 'source_url', 'credit_text'))
        if (entry.get('rights_status') in APPROVED_RIGHTS
                and local_path.startswith(source_dir + os.sep)
                and os.path.isfile(local_path) and valid_window
                and 'all' in platforms and required_metadata
                and entry['id'] not in seen_ids):
            approved.append(entry)
            seen_ids.add(entry['id'])
    return approved

def _catalog_for_prompt(entries):
    fields = (
        'id', 'source_name', 'creator', 'source_url', 'rights_status',
        'approved_start_seconds', 'approved_end_seconds',
        'allow_original_audio', 'credit_text', 'description'
    )
    return [{key: entry.get(key) for key in fields} for entry in entries]

def _urls_from_text(text):
    return {
        url.rstrip('.,;:')
        for url in re.findall(r'https?://[^\s<>"\]\)]+', text or '')
    }

def _deep_research(client, topic, anchor_urls, research_profile):
    deep_prompt = f"""
    Deeply analyze these anchor articles for an evidence-led video about "{topic}":
    {json.dumps(anchor_urls)}

    Research profile: {json.dumps(research_profile)}
    Use URL context to read every anchor. Then find 2-4 related sources that corroborate, update,
    challenge, or humanize the anchor findings. Build 6-10 atomic evidence claims. Every claim must
    include its exact source URL, population/geography, date/period, caveat, and numeric value/unit
    when applicable. Mark a number chart-worthy only when the denominator, unit, and context are clear.
    Surface disagreements and unknowns. Do not infer a number that no retrieved source states.
    Preserve the supplied anchors exactly in `anchors`.
    """
    print("Node 1: Pass 3 (Anchor deep dive + related evidence)...")
    return client.models.generate_content(
        model=GEMINI_MODEL_RESEARCH,
        contents=deep_prompt,
        config=types.GenerateContentConfig(
            tools=[{"url_context": {}}, {"google_search": {}}],
            response_mime_type="application/json",
            response_schema=ResearchDossier,
            temperature=0.2,
        ),
    )

def generate_script(topic, account_id, qa_feedback=None, cta_text=None):
    ACCOUNTS_CONFIG = load_accounts_config()
    account_settings = ACCOUNTS_CONFIG.get(account_id, {})
    persona = account_settings.get('system_instruction', "You are a viral short-form video scriptwriter.")
    research_profile = account_settings.get('research_profile', {
        'anchor_source_types': ['primary research', 'official data', 'reputable explanatory reporting'],
        'preferred_publishers': [],
        'required_lenses': ['mechanism', 'human impact', 'limitations'],
    })
    approved_media = _load_approved_media_catalog()

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise Exception("GEMINI_API_KEY environment variable not set.")

    client = genai.Client(api_key=api_key)

    # PASS 1: Scout a broad candidate set with grounded Google Search results.
    scout_prompt = f"""
    Find 8-12 strong candidate sources for an evidence-led short video about "{topic}".
    Research profile: {json.dumps(research_profile)}
    Prefer direct, publicly accessible article/paper/report URLs over homepages or search pages.
    For each candidate give title, publisher, date, source type, exact URL, central finding,
    and why it adds a distinct mechanism, number, caveat, or human consequence.
    Do not claim a citation count unless a source explicitly supplies it. Do not invent URLs.
    """
    print(f"Node 1: Pass 1 (Source scout) for '{topic}'...")
    scout_response = client.models.generate_content(
        model=GEMINI_MODEL_RESEARCH,
        contents=scout_prompt,
        config=types.GenerateContentConfig(temperature=0.3, tools=[{"google_search": {}}]),
    )
    scout_text = scout_response.text or ''
    scout_urls = _urls_from_text(scout_text) | set(_grounding_urls(scout_response))
    if len(scout_urls) < 2:
        raise Exception("Source scout found fewer than two verifiable article URLs.")

    # PASS 2: Select only one or two anchors from the scout's real URL set.
    curate_prompt = f"""
    Select 1-2 anchor articles for a video about "{topic}" from ONLY the candidates below.
    Choose the smallest set that can carry the story. Prefer one empirical/official source and,
    when useful, one rigorous explanatory or investigative article. Judge authority, recency,
    direct relevance, accessible evidence, complementary viewpoint, and narrative usefulness.
    Never alter or invent a URL.

    CANDIDATES:
    {scout_text}
    """
    print("Node 1: Pass 2 (Anchor curation)...")
    curate_response = client.models.generate_content(
        model=GEMINI_MODEL_STRUCTURED,
        contents=curate_prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=AnchorSelection,
            temperature=0.1,
        ),
    )
    anchor_selection = json.loads(curate_response.text or '{}').get('anchors', [])[:2]
    anchors = _validated_anchors(anchor_selection, scout_urls)
    if not anchors:
        raise Exception("Anchor curator did not return a URL verified by the source scout.")
    selected_scout_urls = [anchor['url'] for anchor in anchors]
    anchors = _resolve_doi_anchors(anchors)
    anchor_urls = [anchor['url'] for anchor in anchors]

    # PASS 3: Read the anchors directly, then search outward for corroboration and challenge.
    deep_response = _deep_research(client, topic, anchor_urls, research_profile)
    research_text = deep_response.text
    if not research_text:
        raise Exception("Anchor deep dive returned no research dossier.")
    statuses = _retrieval_statuses(deep_response, anchor_urls)
    failed = _retrieval_failures(statuses, research_text)
    if failed:
        print(f"Node 1: URL Context recovery needed: {failed}")
        usable = set(anchor_urls) - set(failed)
        if usable:
            anchors = [anchor for anchor in anchors if anchor['url'] in usable]
        else:
            retry_prompt = curate_prompt + f"""

            URL Context could not retrieve these choices: {json.dumps(list(failed))}
            Exclude them and select 1-2 different, publicly accessible candidates.
            """
            retry_response = client.models.generate_content(
                model=GEMINI_MODEL_STRUCTURED,
                contents=retry_prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=AnchorSelection,
                    temperature=0.1,
                ),
            )
            retry_selection = json.loads(retry_response.text or '{}').get('anchors', [])
            anchors = _validated_anchors(
                retry_selection, scout_urls, set(failed) | set(selected_scout_urls))
            if not anchors:
                raise Exception(f"No retrievable anchor alternative remained. URL Context statuses: {failed}")
            anchors = _resolve_doi_anchors(anchors)
        anchor_urls = [anchor['url'] for anchor in anchors]
        deep_response = _deep_research(client, topic, anchor_urls, research_profile)
        research_text = deep_response.text
        if not research_text:
            raise Exception("Recovered anchor deep dive returned no research dossier.")
        statuses = _retrieval_statuses(deep_response, anchor_urls)
        failed = _retrieval_failures(statuses, research_text)
        if failed:
            raise Exception(f"URL Context could not retrieve the recovered anchors: {failed}")
    dossier = json.loads(research_text)
    dossier['anchors'] = anchors
    verified_research_urls = (
        set(anchor_urls) | _urls_from_text(research_text) | set(_grounding_urls(deep_response))
    )

    # PASS 4: Structured storyboard generation.
    selected_vibe = random.choice(VIBES)

    revision_block = ""
    if qa_feedback and qa_feedback.strip():
        revision_block = f"""

    ⚠️  REVISION REQUEST (from human editor — you MUST address this):
    "{qa_feedback.strip()}"
    Specifically correct or improve what the editor described above.
    Do not repeat the same approach that caused the rejection.
"""

    script_prompt = f"""
    Task: Write a master storyboard for a 65-100 second mobile-optimized video about: "{topic}".
    {revision_block}
    Story Structure Constraint: {selected_vibe}

    Here is the verified research dossier you MUST use to build the script:
    {json.dumps(dossier, indent=2)}

    Here is the complete rights-cleared local media catalog available to this video:
    {json.dumps(_catalog_for_prompt(approved_media), indent=2)}

    Content Philosophy:
    Sound unmistakably like the account persona in the system instruction. Use the assigned story structure
    without changing the persona's ethics or vocabulary. Avoid generic setup, fake controversy, unnamed
    authorities, hype, and robotic transitions. Every sentence must advance the argument or story.

    Formatting Rules & Pipeline Constraints:
    1. Narration: Write exactly what the voice should speak. Use natural contractions, varied sentence length,
       clean pronunciation, and no stage directions. A scene's words must fit its assigned duration.
    2. Intentional Duration: Assign `duration_seconds` from 2-12 seconds per scene. The scene durations MUST
       total 65-100 seconds. Use 2-3.5s scenes for punchy facts or pattern interrupts, 4-7s for explanation,
       and 8-12s sparingly for the central mechanism, emotional turn, or climax. Include at least one short
       scene and one 7s+ scene; do not make every scene nearly equal.
    3. Scene Visual Types: Stock remains the fallback for every scene. `visual_search_queries` is an
       ordered list of 1-3 literal searches. A scene may also use one chart, one licensed-media excerpt,
       or both when they genuinely clarify the narration.
    4. Stock Video Queries: `visual_search_queries` entries must each be 2-5 concrete words.
       Each query must be 2-5 concrete words describing a filmable subject in motion, such as
       "nurse walking hospital" or "hands counting cash". Never include labels, slashes, camera instructions,
       abstractions, brand names, or prose. Query 1 is the ideal visual; queries 2-3 are progressively broader,
       visually related fallbacks and may become cutaways. Give at least two queries to selected 5s+ scenes.
       Search behavior is cache → portrait Pexels → Pixabay; only after all stock queries fail does the pipeline
       generate one 9:16 Veo clip. If that also fails, the video fails, so broad fallbacks must remain relevant.
    5. Licensed Media: You may select `licensed_media` ONLY by an exact `media_id` in the supplied catalog.
       Never put a web URL there. Use `source_audio` only when the catalog permits original audio; that scene's
       `narration` MUST be an empty string and its duration must fit the approved window. Otherwise use
       `muted_under_narration`. Excerpts must add evidence or analysis, not decoration.
    6. Charts: Use `chart` only for useful numbers explicitly present in the evidence ledger. Copy values
       exactly; include the exact evidence URL and a short source label. Use pie only for true parts of a whole
       whose values total approximately 100. Use bars for category comparison and lines for ordered change
       over time. Use 2-6 non-negative data points and no more than two charts in the video. Do not place a
       chart over a source-audio excerpt.
    7. Dynamic Pacing: For every scene, assign a `pacing_style`:
       - 'rapid': Use for high-tension montages, chaotic moments, or rapid-fire facts.
       - 'standard': Use for normal explanatory dialogue.
       - 'slow_pan': Use sparingly for dramatic breathing room, profound statements, or establishing shots.
    8. Transition Hints: Use only the renderer's exact transitions:
       - rapid → 'whip_pan' or 'zoom_punch' (4 frames)
       - standard → 'crossfade' (8 frames)
       - slow_pan → 'dissolve' or 'dip_to_black' (14 frames)
       No more than 2 consecutive scenes with the same pacing_style; use deliberate contrast patterns (rapid-rapid-slow_pan = tension/release).
    9. Editing Directives: Every scene needs `editing_directives` with exactly one allowed value per field:
       - camera_movement: 'static', 'gentle_push_in', 'slow_zoom_out', or 'shake'
       - color_grade_hint: 'warm', 'clinical_cool', 'desaturated', or 'high_contrast'
       - audio_emphasis: 'voiceonly', 'music_pedestal', or 'sfx_drop'
       - caption_style: 'bottom_center', 'top_left', 'keyword_emerge', or 'full_text'
       Match these choices to meaning. Use shake and sfx_drop only as rare emphasis, not defaults.
    10. Music Mood: Choose one whole-video mood: 'tense', 'uplifting', 'mysterious', or 'neutral'.
    11. Word-Count Gate: Spoken narrator words must total 160-260 and fit the duration plan. Empty
        source-audio scenes do not count. Report the true count.
    12. CTA Injection: The final narration MUST end with this exact text: "{cta_text or 'Follow for more'}"
    13. Hook: Scene 1 MUST include `hook` with `hook_type` (question, statistic, controversy, or promise)
        and `hook_text` exactly matching the opening spoken words. Later scenes should omit the hook.
    14. Self-QA: Score `hook_score` from 0-10 and estimate `retention_estimate` as a percentage.
        Be harsh: a generic hook is 4. Do not use suspense that the evidence cannot repay.
    15. Use only claims supported by the dossier. Put only exact dossier URLs in `sources`.

    Output strictly as a JSON object matching the requested schema.
    """

    print(f"Node 1: Pass 4 (Structured storyboard) for '{topic}'...")
    script_response = client.models.generate_content(
        model=GEMINI_MODEL_STRUCTURED,
        contents=script_prompt,
        config=types.GenerateContentConfig(
            system_instruction=f"Role & Objective: {persona}",
            response_mime_type="application/json",
            response_schema=ScriptOutput,
            temperature=0.7
        ),
    )

    result_text = script_response.text
    if not result_text:
        raise Exception("Pass 4 returned an empty storyboard response.")

    output = json.loads(result_text)
    output['sources'] = [url for url in output.get('sources', []) if url in verified_research_urls]
    output['_research'] = dossier
    return output

def _coerce_enums(output):
    """Coerce invalid enum values to defaults — don't fail the video over one bad value."""
    if output.get('music_mood') not in VALID_MOODS:
        output['music_mood'] = 'neutral'
    for scene in output.get('scenes', []):
        if scene.get('pacing_style') not in VALID_PACING:
            scene['pacing_style'] = 'standard'
        if scene.get('transition_hint') not in VALID_TRANSITIONS:
            scene['transition_hint'] = 'crossfade'
        queries = scene.get('visual_search_queries')
        if not isinstance(queries, list):
            queries = [scene.get('visual_search_query', '')]
        scene['visual_search_queries'] = [str(q).strip() for q in queries if str(q).strip()][:3]
        if not scene['visual_search_queries']:
            scene['visual_search_queries'] = ['people walking city']
        try:
            scene['duration_seconds'] = min(12.0, max(2.0, float(scene.get('duration_seconds', 4))))
        except (TypeError, ValueError):
            scene['duration_seconds'] = 4.0
        directives = scene.get('editing_directives') or {}
        if directives.get('camera_movement') not in VALID_CAMERA_MOVEMENTS:
            directives['camera_movement'] = 'gentle_push_in'
        if directives.get('color_grade_hint') not in VALID_COLOR_GRADES:
            directives['color_grade_hint'] = 'high_contrast'
        if directives.get('audio_emphasis') not in VALID_AUDIO_EMPHASIS:
            directives['audio_emphasis'] = 'voiceonly'
        if directives.get('caption_style') not in VALID_CAPTION_STYLES:
            directives['caption_style'] = 'bottom_center'
        scene['editing_directives'] = directives
    return output

def _quality_issues(output, expected_cta):
    scenes = output.get('scenes', [])
    actual_words = sum(len(s.get('narration', '').split()) for s in scenes)
    output['word_count'] = actual_words
    issues = []
    durations = [s.get('duration_seconds', 0) for s in scenes]
    total_duration = sum(durations)

    if actual_words < 160 or actual_words > 280:
        issues.append(f"word_count={actual_words} (need 160-280)")
    if not durations or total_duration < 65 or total_duration > 100:
        issues.append(f"duration={total_duration:.1f}s (need 65-100s)")
    elif min(durations) > 3.5 or max(durations) < 7:
        issues.append("duration plan needs both a 2-3.5s beat and a 7s+ beat")
    narrator_duration = sum(
        s.get('duration_seconds', 0) for s in scenes
        if (s.get('licensed_media') or {}).get('playback_mode') != 'source_audio'
    )
    if narrator_duration and not 1.6 <= actual_words / narrator_duration <= 3.4:
        issues.append(f"speech density={actual_words / narrator_duration:.1f} words/s")
    crowded_scenes = [
        i + 1 for i, scene in enumerate(scenes)
        if scene.get('narration')
        and len(scene.get('narration', '').split()) / scene.get('duration_seconds', 1) > 3.5
    ]
    if crowded_scenes:
        issues.append(f"narration is too dense for scene duration: {crowded_scenes[:3]}")
    if scenes and not any(len(s.get('visual_search_queries', [])) >= 2 for s in scenes):
        issues.append("no scene has fallback/cutaway queries")
    invalid_queries = [
        query for scene in scenes for query in scene.get('visual_search_queries', [])
        if not 2 <= len(query.split()) <= 5
    ]
    if invalid_queries:
        issues.append(f"stock queries must contain 2-5 words: {invalid_queries[:2]}")
    if not scenes or not scenes[0].get('hook'):
        issues.append("first scene has no hook")
    elif not scenes[0].get('narration', '').startswith(scenes[0]['hook'].get('hook_text', '')):
        issues.append("hook_text does not exactly match the opening narration")
    if scenes and not scenes[-1].get('narration', '').rstrip().endswith(expected_cta):
        issues.append("final narration does not end with exact CTA")
    if output.get('hook_score', 0) < 6:
        issues.append(f"hook_score={output.get('hook_score', 0)} (need >=6)")
    if not any(str(s).startswith(('http://', 'https://')) for s in output.get('sources', [])):
        issues.append("sources contains no exact URL")

    catalog = {entry.get('id'): entry for entry in _load_approved_media_catalog()}
    evidence = output.get('_research', {}).get('evidence_ledger', [])
    evidence_urls = {item.get('source_url') for item in evidence}
    if sum(bool(scene.get('chart')) for scene in scenes) > 2:
        issues.append("video may contain no more than two charts")
    for i, scene in enumerate(scenes):
        media = scene.get('licensed_media')
        if media:
            entry = catalog.get(media.get('media_id'))
            if not entry:
                issues.append(f"scene {i + 1} selects unavailable licensed media")
            else:
                available = entry['approved_end_seconds'] - entry['approved_start_seconds']
                if scene.get('duration_seconds', 0) > available + 0.05:
                    issues.append(f"scene {i + 1} exceeds approved media window")
                if media.get('playback_mode') == 'source_audio':
                    if not entry.get('allow_original_audio'):
                        issues.append(f"scene {i + 1} is not approved for original audio")
                    if scene.get('narration', '').strip():
                        issues.append(f"scene {i + 1} cannot mix narration with source audio")

        chart = scene.get('chart')
        if chart:
            if (scene.get('licensed_media') or {}).get('playback_mode') == 'source_audio':
                issues.append(f"scene {i + 1} cannot cover source audio with a chart")
            points = chart.get('points', [])
            values = [point.get('value') for point in points]
            if not 2 <= len(points) <= 6 or any(
                    not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0
                    for v in values):
                issues.append(f"scene {i + 1} chart needs 2-6 finite non-negative values")
                continue
            if chart.get('source_url') not in evidence_urls:
                issues.append(f"scene {i + 1} chart source is not in the evidence ledger")
            sourced_values = [
                item.get('numeric_value') for item in evidence
                if item.get('source_url') == chart.get('source_url')
                and item.get('numeric_value') is not None
            ]
            if not all(
                    any(item.get('source_url') == chart.get('source_url')
                        and item.get('numeric_value') is not None
                        and math.isclose(point['value'], item['numeric_value'], rel_tol=1e-6, abs_tol=1e-6)
                        and (not item.get('unit') or item.get('unit') == chart.get('unit'))
                        for item in evidence)
                    for point in points):
                issues.append(f"scene {i + 1} chart value or unit does not match its source claims")
            if any(not any(math.isclose(v, source, rel_tol=1e-6, abs_tol=1e-6)
                           for source in sourced_values) for v in values):
                issues.append(f"scene {i + 1} chart contains a value absent from its source claims")
            if chart.get('chart_type') == 'pie':
                if any(v < 0 for v in values) or not math.isclose(sum(values), 100, abs_tol=1):
                    issues.append(f"scene {i + 1} pie values must total about 100")
    return issues

def run():
    print("Node 1: Master Scriptwriter started.")
    videos = database.fetch_videos_by_status('Pending_Script')
    for video in videos:
        print(f"Processing video ID {video['id']}: {video['topic']}")

        try:
            config_cta = load_accounts_config().get(video['account_id'], {}).get('default_cta', "Follow for more")
            target_cta = video.get('cta_text') or config_cta

            output = generate_script(
                video['topic'], video['account_id'],
                qa_feedback=video.get('qa_feedback'),
                cta_text=target_cta
            )

            # Cost logging
            database.add_cost(video['id'], COST_SCOUT_CALL)
            database.add_cost(video['id'], COST_CURATE_CALL)
            database.add_cost(video['id'], COST_DEEP_RESEARCH_CALL)
            database.add_cost(video['id'], COST_SCRIPT_CALL)

            # Coerce invalid enums
            output = _coerce_enums(output)

            # Post-generation validation: narration, rhythm, sourcing, and required structure
            issues = _quality_issues(output, target_cta)
            if issues:
                retry_count = (video.get('script_retry_count') or 0) + 1
                reason = "; ".join(issues) + "."
                if retry_count < 2:
                    database.update_video(video['id'], {
                        'status': 'Pending_Script',
                        'script_retry_count': retry_count,
                        'qa_feedback': f"Auto-rejected: {reason}",
                        'error_message': None,
                    })
                    print(f"Video {video['id']} auto-rejected (attempt {retry_count}): {reason}")
                else:
                    database.update_video(video['id'], {
                        'status': 'Failed',
                        'error_message': f"Script generation failed after {retry_count} attempts: {reason}",
                        'script_retry_count': retry_count,
                    })
                    print(f"Video {video['id']} FAILED after {retry_count} retries.")
                continue

            # Success path
            next_status = 'Pending_Voice' if video.get('auto_approve') else 'QA_Script'
            database.update_video(video['id'], {
                'script': json.dumps(output, indent=2),
                'script_sources': json.dumps(output.get('sources', [])),
                'status': next_status,
                'hook_score': output.get('hook_score', 0),
                'retention_estimate': output.get('retention_estimate', 0),
                'script_retry_count': 0,
                'qa_feedback': None,
                'error_message': None,
            })
            print(f"Video {video['id']} → {next_status}")

        except Exception as e:
            error_str = str(e)
            print(f"Failed to generate script for video ID {video['id']}: {error_str}")
            database.update_video(video['id'], {
                'status': 'Failed',
                'error_message': f"Node 1 (Scripting) Error: {error_str}"
            })

if __name__ == "__main__":
    while True:
        run()
        time.sleep(10)