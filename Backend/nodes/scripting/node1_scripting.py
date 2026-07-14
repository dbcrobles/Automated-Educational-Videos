"""Node 1 — Master Scriptwriter (legacy short-form pipeline).

Research lives in Backend/nodes/research/researcher.py; storyboard QA/repair in
script_quality.py; prompt text in prompts.py. This file orchestrates them.
"""
import os
import sys
import json
import time
import random
import requests
from typing import Literal, Optional
from pydantic import BaseModel, Field
from google import genai
from google.genai import types

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from database import database
from nodes.research.researcher import (  # noqa: F401 — re-exported for legacy imports
    ChartPoint, ResearchDossier, EvidenceClaim, SourceReference, AnchorArticle,
    GEMINI_MODEL_RESEARCH, GEMINI_MODEL_STRUCTURED,
    _build_research_dossier, _audit_currentness, _normalize_dossier,
    _research_quality_issues, _dossier_needs_audit, _source_details,
    _url_key, _urls_from_text, _grounding_urls,
)
from nodes.scripting.script_quality import (  # noqa: F401 — re-exported for legacy imports
    _load_approved_media_catalog, _catalog_for_prompt, _fact_check_storyboard,
    _coerce_enums, _apply_safe_fallbacks, _quality_issues,
)
from nodes.scripting import prompts

COST_SCRIPT_CALL = 0.01
SOFT_SCRIPT_COST_LIMIT = 0.25   # automatic QA repairs pause here for human review
HARD_SCRIPT_COST_LIMIT = 0.55   # absolute ceiling — even manual retries stop here
MAX_AUTO_QA_RETRIES = 4         # runaway guard while spend stays under the soft cap

OPENAI_MODEL_SCRIPT = "gpt-5.6-luna"
OPENAI_INPUT_USD_PER_TOKEN = 1.00 / 1_000_000
OPENAI_OUTPUT_USD_PER_TOKEN = 6.00 / 1_000_000

VIBES = prompts.VIBES


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
    sound_effect: Literal["none", "impact", "whoosh", "chime"]
    caption_style: Literal["bottom_center", "top_left", "keyword_emerge", "full_text"]

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


def _openai_storyboard(prompt, persona, video_id):
    """Generate the creative draft with Luna while keeping research in Gemini."""
    schema = ScriptOutput.model_json_schema()
    stack = [schema]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            node.pop('default', None)
            if node.get('type') == 'object' and 'properties' in node:
                node['additionalProperties'] = False
                node['required'] = list(node['properties'])
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)
    response = requests.post(
        "https://api.openai.com/v1/responses",
        headers={
            "Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}",
            "Content-Type": "application/json",
        },
        json={
            "model": OPENAI_MODEL_SCRIPT,
            "input": [
                {"role": "system", "content": f"Role & Objective: {persona}"},
                {"role": "user", "content": prompt},
            ],
            "reasoning": {"effort": os.environ.get("OPENAI_REASONING_EFFORT", "max")},
            "text": {"format": {
                "type": "json_schema",
                "name": "video_storyboard",
                "schema": schema,
                "strict": True,
            }},
        },
        timeout=180,
    )
    response.raise_for_status()
    payload = response.json()
    result_text = payload.get('output_text')
    if not result_text:
        result_text = next(
            (content.get('text') for item in payload.get('output', [])
             for content in item.get('content', [])
             if content.get('type') == 'output_text'), None)
    if not result_text:
        raise Exception("GPT-5.6 Luna returned no storyboard text.")
    usage = payload.get('usage', {})
    cost = (usage.get('input_tokens', 0) * OPENAI_INPUT_USD_PER_TOKEN
            + usage.get('output_tokens', 0) * OPENAI_OUTPUT_USD_PER_TOKEN)
    database.add_script_cost(video_id, cost or COST_SCRIPT_CALL)
    return result_text


def generate_script(topic, account_id, video_id, qa_feedback=None, cta_text=None,
                    cached_research=None, previous_draft=None):
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

    if cached_research:
        print("Node 1: Reusing saved research dossier (passes 1-3 skipped).")
        dossier = json.loads(cached_research)
        if _dossier_needs_audit(dossier):
            print("Node 1: Saved research is legacy/stale; refreshing currentness via Google Search.")
            original_anchors = _normalize_dossier(dossier).get('anchors', [])
            dossier, audit_response = _audit_currentness(client, topic, dossier, video_id)
            audited_access = {_url_key(a.get('url')): a.get('access_url')
                              for a in dossier.get('anchors', [])}
            for anchor in original_anchors:
                anchor['access_url'] = audited_access.get(
                    _url_key(anchor.get('url')), anchor.get('access_url') or anchor.get('url'))
            dossier['anchors'] = original_anchors
            database.update_video(video_id, {'research_dossier': json.dumps(dossier)})
            verified_research_urls = (_urls_from_text(json.dumps(dossier))
                                      | set(_grounding_urls(audit_response)))
        else:
            dossier = _normalize_dossier(dossier)
            verified_research_urls = _urls_from_text(json.dumps(dossier))
        research_issues = _research_quality_issues(dossier)
        if research_issues:
            raise Exception("Research quality gate failed: " + "; ".join(research_issues))
    else:
        dossier, verified_research_urls = _build_research_dossier(
            client, topic, research_profile, video_id)
        database.update_video(video_id, {'research_dossier': json.dumps(dossier)})

    # PASS 4: Structured storyboard generation.
    script_prompt = prompts.storyboard_prompt(
        topic,
        prompts.revision_block(qa_feedback, previous_draft),
        random.choice(prompts.VIBES),
        dossier,
        _catalog_for_prompt(approved_media),
        cta_text,
    )

    print(f"Node 1: Pass 4 (Structured storyboard) for '{topic}'...")
    result_text = None
    if os.environ.get('OPENAI_API_KEY'):
        try:
            print(f"Node 1: Writing with {OPENAI_MODEL_SCRIPT} (reasoning=max).")
            result_text = _openai_storyboard(script_prompt, persona, video_id)
        except Exception as error:
            database.record_pipeline_error(
                video_id, 'Node 1', 'LUNA_FALLBACK', str(error), auto_recovered=True)
            print(f"Node 1: Luna unavailable ({error}); using {GEMINI_MODEL_STRUCTURED}.")
    if not result_text:
        if not os.environ.get('OPENAI_API_KEY'):
            print(f"Node 1: OPENAI_API_KEY absent; using {GEMINI_MODEL_STRUCTURED}.")
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
        database.add_script_cost(video_id, COST_SCRIPT_CALL)
        result_text = script_response.text
    if not result_text:
        raise Exception("Pass 4 returned an empty storyboard response.")

    output = json.loads(result_text)
    output['sources'] = [url for url in output.get('sources', []) if url in verified_research_urls]
    output['_research'] = dossier
    output['_fact_issues'] = _fact_check_storyboard(client, output, video_id)
    output['source_details'] = _source_details(dossier, output['sources'])
    return output


def run():
    print("Node 1: Master Scriptwriter started.")
    videos = database.fetch_videos_by_status('Pending_Script')
    for video in videos:
        print(f"Processing video ID {video['id']}: {video['topic']}")

        try:
            config_cta = load_accounts_config().get(video['account_id'], {}).get('default_cta', "Follow for more")
            target_cta = video.get('cta_text') or config_cta

            spent = video.get('script_cost_estimate') or 0
            if spent >= HARD_SCRIPT_COST_LIMIT:
                database.fail_video(
                    video['id'], 'Node 1', 'SCRIPT_COST_HARD_LIMIT',
                    f"Node 1 spend reached ${spent:.2f}; the ${HARD_SCRIPT_COST_LIMIT:.2f} "
                    f"hard cap blocks all further retries. Use Full Restart or delete.",
                    attempt=video.get('script_retry_count') or 0)
                continue

            output = generate_script(
                video['topic'], video['account_id'], video['id'],
                qa_feedback=video.get('qa_feedback'),
                cta_text=target_cta,
                cached_research=video.get('research_dossier'),
                previous_draft=video.get('storyboard_draft'),
            )

            # Cheap deterministic repairs happen before any paid retry.
            output = _coerce_enums(output)
            output = _apply_safe_fallbacks(output, target_cta)
            database.update_video(video['id'], {
                'storyboard_draft': json.dumps({
                    key: value for key, value in output.items() if key != '_research'
                }),
            })

            # Post-generation validation: narration, rhythm, sourcing, and required structure
            issues = _quality_issues(output, target_cta)
            if issues:
                retry_count = (video.get('script_retry_count') or 0) + 1
                reason = "; ".join(issues) + "."
                spent = database.get_script_cost(video['id'])
                database.record_pipeline_error(
                    video['id'], 'Node 1', 'STORYBOARD_QA', reason,
                    {'issues': issues}, retry_count)
                if spent >= SOFT_SCRIPT_COST_LIMIT:
                    database.fail_video(
                        video['id'], 'Node 1', 'SCRIPT_COST_SOFT_LIMIT',
                        f"Auto-repair paused at ${spent:.2f} (soft cap ${SOFT_SCRIPT_COST_LIMIT:.2f}). "
                        f"Remaining issues: {reason} Add a note and Smart Retry to continue "
                        f"(hard stop at ${HARD_SCRIPT_COST_LIMIT:.2f}).",
                        {'issues': issues}, retry_count)
                    database.update_video(video['id'], {'script_retry_count': retry_count})
                    print(f"Video {video['id']} paused for cost review at ${spent:.2f}.")
                elif retry_count <= MAX_AUTO_QA_RETRIES:
                    database.update_video(video['id'], {
                        'status': 'Pending_Script',
                        'script_retry_count': retry_count,
                        'qa_feedback': f"Repair only these remaining issues: {reason}",
                        'error_message': None,
                    })
                    print(f"Video {video['id']} queued for storyboard repair "
                          f"{retry_count}/{MAX_AUTO_QA_RETRIES} (${spent:.2f} spent): {reason}")
                else:
                    database.fail_video(
                        video['id'], 'Node 1', 'STORYBOARD_QA_REPEAT', reason,
                        {'issues': issues}, retry_count)
                    database.update_video(video['id'], {'script_retry_count': retry_count})
                    print(f"Video {video['id']} FAILED after {retry_count} attempts.")
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
                'storyboard_draft': None,
            })
            database.resolve_pipeline_errors(video['id'], 'Node 1')
            print(f"Video {video['id']} → {next_status}")

        except Exception as e:
            error_str = str(e)
            print(f"Failed to generate script for video ID {video['id']}: {error_str}")
            code = 'URL_CONTEXT' if 'URL Context' in error_str else 'SCRIPTING_EXCEPTION'
            database.fail_video(
                video['id'], 'Node 1', code, error_str,
                attempt=(video.get('script_retry_count') or 0) + 1)

if __name__ == "__main__":
    while True:
        run()
        time.sleep(10)