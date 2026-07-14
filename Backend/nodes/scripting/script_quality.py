"""Deterministic storyboard QA, repair, and media-catalog helpers.

Moved verbatim from node1_scripting.py to keep every file under 800 lines.
"""
import os
import sys
import json
import math
import re
from typing import Literal
from urllib.parse import urlsplit
from pydantic import BaseModel
from google.genai import types

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from database import database
from nodes.research.researcher import GEMINI_MODEL_STRUCTURED

COST_FACT_CHECK_CALL = 0.01

VALID_PACING = {"rapid", "standard", "slow_pan"}
VALID_TRANSITIONS = {"whip_pan", "zoom_punch", "crossfade", "dissolve", "dip_to_black"}
VALID_MOODS = {"tense", "uplifting", "mysterious", "neutral"}
VALID_CAMERA_MOVEMENTS = {"static", "gentle_push_in", "slow_zoom_out", "shake"}
VALID_COLOR_GRADES = {"warm", "clinical_cool", "desaturated", "high_contrast"}
VALID_AUDIO_EMPHASIS = {"voiceonly", "music_pedestal", "sfx_drop"}
VALID_CAPTION_STYLES = {"bottom_center", "top_left", "keyword_emerge", "full_text"}
APPROVED_RIGHTS = {"owned", "licensed", "permission", "public_domain"}
ASSETS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'assets')


class FactualIssue(BaseModel):
    scene_number: int
    issue_type: Literal[
        "stale_as_current", "unsupported_claim", "number_mismatch",
        "missing_qualifier", "causal_overstatement"
    ]
    message: str
    source_url: str

class FactualReview(BaseModel):
    issues: list[FactualIssue]


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

def _fact_check_storyboard(client, output, video_id):
    """Semantic gate catches stale-as-current wording that URL checks cannot."""
    prompt = f"""
    Compare every factual statement in this storyboard against the evidence ledger. Return only genuine
    factual issues, not style advice. A claim with usage `do_not_use` may not appear. A `dated_context`
    claim must explicitly say its year/period and must not use present-tense wording that implies it is
    current. Numbers, populations, denominators, comparisons, causal strength, and caveats must match.
    Broad narrative language needs evidence too. If fully supported, return an empty issues list.

    EVIDENCE:
    {json.dumps(output.get('_research', {}).get('evidence_ledger', []), indent=2)}

    STORYBOARD:
    {json.dumps(output.get('scenes', []), indent=2)}
    """
    response = client.models.generate_content(
        model=GEMINI_MODEL_STRUCTURED,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=FactualReview,
            temperature=0,
        ),
    )
    database.add_script_cost(video_id, COST_FACT_CHECK_CALL)
    if not response.text:
        raise Exception("Factual storyboard review returned no result.")
    return json.loads(response.text).get('issues', [])

def _coerce_enums(output):
    """Coerce invalid enum values to defaults — don't fail the video over one bad value."""
    if output.get('music_mood') not in VALID_MOODS:
        output['music_mood'] = 'neutral'
    stylized_transitions = 0
    shake_scenes = 0
    effect_scenes = 0
    previous_effect_index = -2
    for index, scene in enumerate(output.get('scenes', [])):
        if scene.get('pacing_style') not in VALID_PACING:
            scene['pacing_style'] = 'standard'
        if scene.get('transition_hint') not in VALID_TRANSITIONS:
            scene['transition_hint'] = 'crossfade'
        if scene['transition_hint'] in {'whip_pan', 'zoom_punch', 'dip_to_black'}:
            stylized_transitions += 1
            if stylized_transitions > 2:
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
            directives['camera_movement'] = 'static'
        if directives['camera_movement'] == 'shake':
            shake_scenes += 1
            if shake_scenes > 1:
                directives['camera_movement'] = 'static'
        if directives.get('color_grade_hint') not in VALID_COLOR_GRADES:
            directives['color_grade_hint'] = 'high_contrast'
        if directives.get('audio_emphasis') not in VALID_AUDIO_EMPHASIS:
            directives['audio_emphasis'] = 'voiceonly'
        if directives.get('sound_effect') not in {'none', 'impact', 'whoosh', 'chime'}:
            directives['sound_effect'] = 'none'
        if directives['sound_effect'] != 'none':
            if effect_scenes >= 2 or index == previous_effect_index + 1:
                directives.update(sound_effect='none', audio_emphasis='voiceonly')
            else:
                effect_scenes += 1
                previous_effect_index = index
                directives['audio_emphasis'] = 'sfx_drop'
        if directives.get('caption_style') not in VALID_CAPTION_STYLES:
            directives['caption_style'] = 'bottom_center'
        scene['editing_directives'] = directives
    return output

def _norm_unit(unit):
    """Treat cosmetic unit spellings ('%', 'Percent') as the same unit."""
    text = str(unit or '').strip().lower().rstrip('.')
    return {'%': 'percent', 'pct': 'percent', 'percentage': 'percent'}.get(text, text)

def _chart_point_is_sourced(point, chart, evidence):
    """Accept exact atomic values or exact values from a researched chart set."""
    for item in evidence:
        if item.get('usage') == 'do_not_use':
            continue
        if item.get('source_url') != chart.get('source_url'):
            continue
        point_unit = item.get('chart_unit') or item.get('unit')
        if point_unit and _norm_unit(point_unit) != _norm_unit(chart.get('unit')):
            continue
        values = [item.get('numeric_value')]
        values.extend(p.get('value') for p in item.get('chart_points') or [])
        if any(isinstance(value, (int, float))
               and math.isclose(point['value'], value, rel_tol=1e-6, abs_tol=1e-6)
               for value in values):
            return True
    return False

def _chartable_evidence(evidence):
    """Return only complete, exact chart sets; isolated numbers do not force charts."""
    return [item for item in evidence
            if item.get('usage') != 'do_not_use'
            and item.get('chart_recommended')
            and item.get('chart_unit')
            and 2 <= len(item.get('chart_points') or []) <= 6
            and all(isinstance(point.get('value'), (int, float))
                    and math.isfinite(point['value']) and point['value'] >= 0
                    for point in item.get('chart_points') or [])]

def _inject_required_chart(output):
    """Build one truthful chart from researched points when the model omits it."""
    scenes = output.get('scenes', [])
    if not scenes or any(scene.get('chart') for scene in scenes):
        return output
    chart_sets = _chartable_evidence(output.get('_research', {}).get('evidence_ledger', []))
    if not chart_sets:
        return output
    item = chart_sets[0]
    claim = str(item.get('claim') or 'Sourced comparison')
    keywords = {word.lower() for word in re.findall(r'[A-Za-z]{4,}', claim)}
    eligible = [(index, scene) for index, scene in enumerate(scenes[1:], 1)
                if (scene.get('licensed_media') or {}).get('playback_mode') != 'source_audio']
    if not eligible:
        return output
    index, scene = max(eligible, key=lambda pair: (
        len(keywords & {word.lower() for word in re.findall(r'[A-Za-z]{4,}', pair[1].get('narration', ''))}),
        pair[1].get('duration_seconds', 0)))
    labels = [str(point.get('label', '')) for point in item['chart_points']]
    chart_type = 'line' if labels and all(re.search(r'\b(?:19|20)\d{2}\b', label) for label in labels) else 'bar'
    scene['chart'] = {
        'chart_type': chart_type,
        'display_mode': 'full_screen',
        'title': claim.split('.')[0][:72],
        'unit': item['chart_unit'],
        'points': item['chart_points'],
        'highlight': claim[:110],
        'source_url': item['source_url'],
        'source_label': urlsplit(item['source_url']).netloc.removeprefix('www.')[:45],
    }
    return output

def _apply_safe_fallbacks(output, expected_cta):
    """Repair deterministic formatting problems without another model call."""
    scenes = output.get('scenes', [])
    evidence = output.get('_research', {}).get('evidence_ledger', [])
    evidence_urls = {item.get('source_url') for item in evidence
                     if item.get('usage') != 'do_not_use'}
    total_duration = sum(scene.get('duration_seconds', 0) for scene in scenes)
    for scene in scenes:
        words = len(scene.get('narration', '').split())
        duration = scene.get('duration_seconds', 4)
        required = min(12.0, words / 3.3) if words else duration
        increase = min(max(0, required - duration), max(0, 100 - total_duration))
        if increase:
            scene['duration_seconds'] = round(duration + increase, 1)
            total_duration += increase

        queries = []
        for query in scene.get('visual_search_queries', []):
            parts = str(query).split()[:5]
            if len(parts) == 1:
                parts.append('people')
            if parts:
                queries.append(' '.join(parts))
        scene['visual_search_queries'] = queries or ['people walking city']

        chart = scene.get('chart')
        if chart:
            points = chart.get('points', [])
            values = [point.get('value') for point in points]
            valid_values = 2 <= len(points) <= 6 and all(
                isinstance(value, (int, float)) and math.isfinite(value) and value >= 0
                for value in values)
            claims_match = (valid_values and chart.get('source_url') in evidence_urls
                            and all(_chart_point_is_sourced(point, chart, evidence)
                                    for point in points))
            valid_pie = chart.get('chart_type') != 'pie' or (
                valid_values and math.isclose(sum(values), 100, abs_tol=1))
            if (not claims_match or not valid_pie
                    or (scene.get('licensed_media') or {}).get('playback_mode') == 'source_audio'):
                scene['chart'] = None

    # Inject a truthful chart only AFTER invalid model charts were stripped, so a bad
    # model chart can never leave the video chartless and trip QA on a retry loop.
    output = _inject_required_chart(output)

    if scenes and scenes[-1].get('narration'):
        narration = scenes[-1]['narration'].rstrip()
        if not narration.endswith(expected_cta):
            scenes[-1]['narration'] = f"{narration} {expected_cta}"
    if scenes and not any(len(scene.get('visual_search_queries', [])) >= 2 for scene in scenes):
        fallback = 'people walking city'
        if fallback not in scenes[0]['visual_search_queries']:
            scenes[0]['visual_search_queries'].append(fallback)
    if not output.get('sources'):
        output['sources'] = [
            anchor.get('url') for anchor in output.get('_research', {}).get('anchors', [])
            if anchor.get('url')
        ]
    return output

def _quality_issues(output, expected_cta):
    scenes = output.get('scenes', [])
    actual_words = sum(len(s.get('narration', '').split()) for s in scenes)
    output['word_count'] = actual_words
    issues = []
    issues.extend(
        f"factual QA scene {item.get('scene_number')}: {item.get('message')}"
        for item in output.get('_fact_issues', []))
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
    if scenes:
        first = scenes[0]
        first_directives = first.get('editing_directives') or {}
        if first.get('duration_seconds', 99) > 3:
            issues.append("first scene must end within the first 3 seconds")
        if len(first.get('narration', '').split()) > 8:
            issues.append("first scene hook must contain no more than 8 spoken words")
        if first_directives.get('caption_style') not in {'keyword_emerge', 'full_text'}:
            issues.append("first scene needs emphasis captions")
    if scenes and not scenes[-1].get('narration', '').rstrip().endswith(expected_cta):
        issues.append("final narration does not end with exact CTA")
    if output.get('hook_score', 0) < 7.5:
        issues.append(f"hook_score={output.get('hook_score', 0)} (need >=7.5)")
    if not any(str(s).startswith(('http://', 'https://')) for s in output.get('sources', [])):
        issues.append("sources contains no exact URL")

    catalog = {entry.get('id'): entry for entry in _load_approved_media_catalog()}
    evidence = output.get('_research', {}).get('evidence_ledger', [])
    evidence_urls = {item.get('source_url') for item in evidence
                     if item.get('usage') != 'do_not_use'}
    chart_eligible_scene = any(
        (scene.get('licensed_media') or {}).get('playback_mode') != 'source_audio'
        for scene in scenes[1:])
    chart_expected = bool(_chartable_evidence(evidence)) and chart_eligible_scene
    if chart_expected and not any(scene.get('chart') for scene in scenes):
        issues.append("chart-worthy/comparable sourced metrics require at least one chart")
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
            if not all(_chart_point_is_sourced(point, chart, evidence) for point in points):
                issues.append(f"scene {i + 1} chart value or unit does not match its source claims")
            if chart.get('chart_type') == 'pie':
                if any(v < 0 for v in values) or not math.isclose(sum(values), 100, abs_tol=1):
                    issues.append(f"scene {i + 1} pie values must total about 100")
    return issues