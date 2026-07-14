"""Node 1b — Beat Script worker (long-form pipeline).

Polls Pending_BeatScript, makes ONE LLM call to produce a BeatScript, runs
deterministic QA (no extra LLM call), and sets status to QA_BeatScript for
dashboard review. Spend is logged with stage='beat_script'.
"""
import os
import sys
import json
import time
import requests

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from database import database
from schemas.beat import BeatScript
from schemas.research_artifact import ResearchArtifact
from nodes.beat_script import prompts

from google import genai
from google.genai import types

# Same OpenAI model node1 uses; Gemini fallback below.
OPENAI_MODEL_BEAT = "gpt-5.6-luna"
OPENAI_INPUT_USD_PER_TOKEN = 1.00 / 1_000_000
OPENAI_OUTPUT_USD_PER_TOKEN = 6.00 / 1_000_000
COST_FALLBACK = 0.01  # flat estimate when token counts are unavailable

GEMINI_MODEL_STRUCTURED = "gemini-3.5-flash"

MAX_AUTO_QA_RETRIES = 3
MIN_DURATION_SEC = 180
MAX_DURATION_SEC = 600
MIN_WPS = 2.0
MAX_WPS = 3.0


def _load_accounts_config():
    config_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'accounts_config.json')
    with open(config_path, 'r') as f:
        return json.load(f)


def _load_pipeline_config():
    config_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'pipeline_config.json')
    with open(config_path, 'r') as f:
        return json.load(f)


def _beat_quality_issues(beat_script: BeatScript, artifact: ResearchArtifact) -> list[str]:
    """Deterministic QA — no LLM call. Returns a list of human-readable issues."""
    issues = []

    # Duration check
    total = beat_script.total_duration_sec
    if total < MIN_DURATION_SEC:
        issues.append(f"Total duration {total:.0f}s is below the {MIN_DURATION_SEC}s minimum")
    if total > MAX_DURATION_SEC:
        issues.append(f"Total duration {total:.0f}s exceeds the {MAX_DURATION_SEC}s maximum")

    # Word-rate sanity per beat
    for beat in beat_script.beats:
        words = len(beat.spoken_text.split())
        wps = words / beat.target_duration_sec if beat.target_duration_sec > 0 else 0
        if wps < MIN_WPS:
            issues.append(
                f"Beat {beat.order} word rate {wps:.1f} w/s is below {MIN_WPS} "
                f"({words} words in {beat.target_duration_sec:.0f}s)")
        if wps > MAX_WPS:
            issues.append(
                f"Beat {beat.order} word rate {wps:.1f} w/s exceeds {MAX_WPS} "
                f"({words} words in {beat.target_duration_sec:.0f}s)")

    # Chart ref validation
    valid_dp_ids = {dp.id for dp in artifact.data_points}
    chart_refs_used = set()
    for beat in beat_script.beats:
        for el in beat.elements:
            if el.kind == "chart":
                if not el.ref:
                    issues.append(f"Beat {beat.order} has a chart element with no ref")
                elif el.ref not in valid_dp_ids:
                    issues.append(
                        f"Beat {beat.order} chart ref '{el.ref}' does not exist in the artifact's data_points")
                else:
                    chart_refs_used.add(el.ref)

    # At least one data point visualized
    if valid_dp_ids and not chart_refs_used:
        issues.append("No data point is visualized — at least one beat must use a chart with a valid ref")

    return issues


def _openai_beat_script(prompt, persona, video_id, model):
    """Generate the beat script via OpenAI structured output, with real token-cost accounting."""
    schema = BeatScript.model_json_schema()
    # Strip defaults and enforce strict additionalProperties=False like node1 does
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
            "model": model,
            "input": [
                {"role": "system", "content": f"Role & Objective: {persona}"},
                {"role": "user", "content": prompt},
            ],
            "reasoning": {"effort": os.environ.get("OPENAI_REASONING_EFFORT", "max")},
            "text": {"format": {
                "type": "json_schema",
                "name": "beat_script",
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
        raise Exception("OpenAI returned no beat script text.")

    usage = payload.get('usage', {})
    tokens_in = usage.get('input_tokens', 0)
    tokens_out = usage.get('output_tokens', 0)
    cost = (tokens_in * OPENAI_INPUT_USD_PER_TOKEN + tokens_out * OPENAI_OUTPUT_USD_PER_TOKEN)
    cost_status = database.log_cost(
        video_id, cost or COST_FALLBACK, 'beat_script',
        provider='openai', model=model, tokens_in=tokens_in, tokens_out=tokens_out)
    return result_text, cost_status


def _gemini_beat_script(client, prompt, persona, video_id, model):
    """Gemini fallback for beat script generation."""
    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=f"Role & Objective: {persona}",
            response_mime_type="application/json",
            response_schema=BeatScript,
            temperature=0.7,
        ),
    )
    if not response.text:
        raise Exception("Gemini returned an empty beat script response.")
    cost_status = database.log_cost(
        video_id, COST_FALLBACK, 'beat_script', provider='google', model=model)
    return response.text, cost_status


def generate_beat_script(video_id, topic, account_id, artifact_json,
                         qa_feedback=None, previous_draft=None,
                         use_degraded_model=False):
    """One LLM call → BeatScript. Returns (BeatScript, cost_status)."""
    accounts_config = _load_accounts_config()
    account_settings = accounts_config.get(account_id, {})
    persona = account_settings.get(
        'system_instruction', "You are an educational YouTube narrator.")
    pipeline_config = _load_pipeline_config()

    artifact = ResearchArtifact.model_validate_json(artifact_json)
    data_point_ids = [dp.id for dp in artifact.data_points]

    prompt = prompts.beat_script_prompt(
        topic, artifact_json, persona,
        prompts.revision_block(qa_feedback, previous_draft),
        data_point_ids)

    # Choose model
    if use_degraded_model:
        model = pipeline_config.get('degraded_model', GEMINI_MODEL_STRUCTURED)
    else:
        model = OPENAI_MODEL_BEAT

    result_text = None
    cost_status = 'ok'

    # Try OpenAI first (unless degraded forces Gemini)
    if not use_degraded_model and os.environ.get('OPENAI_API_KEY'):
        try:
            result_text, cost_status = _openai_beat_script(prompt, persona, video_id, model)
        except Exception as error:
            database.record_pipeline_error(
                video_id, 'Node 1b', 'LUNA_FALLBACK', str(error), auto_recovered=True)
            print(f"Node 1b: Luna unavailable ({error}); using Gemini fallback.")
            model = GEMINI_MODEL_STRUCTURED

    # Gemini fallback (or degraded path)
    if not result_text:
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise Exception("GEMINI_API_KEY environment variable not set.")
        client = genai.Client(api_key=api_key)
        result_text, cost_status = _gemini_beat_script(
            client, prompt, persona, video_id, model)

    beat_script = BeatScript.model_validate_json(result_text)
    return beat_script, cost_status


def run():
    print("Node 1b: Beat Script worker started.")
    videos = database.fetch_videos_by_status('Pending_BeatScript')
    for video in videos:
        if video.get('format') != 'long':
            continue
        print(f"Node 1b: Processing video ID {video['id']}: {video['topic']}")

        try:
            artifact_json = video.get('research_artifact')
            if not artifact_json:
                raise Exception("No research_artifact found — cannot write beat script.")

            beat_script, cost_status = generate_beat_script(
                video['id'], video['topic'], video['account_id'], artifact_json,
                qa_feedback=video.get('qa_feedback'),
                previous_draft=video.get('beat_script'),
                use_degraded_model=bool(video.get('use_degraded_model', 0)))

            # Hard cost tier → pause, keep what we have
            if cost_status == 'hard':
                database.pause_for_cost(video['id'], 'beat_script')
                print(f"Node 1b: Video {video['id']} paused at hard cost tier.")
                continue

            # Deterministic QA
            artifact = ResearchArtifact.model_validate_json(artifact_json)
            issues = _beat_quality_issues(beat_script, artifact)

            if issues:
                retry_count = (video.get('script_retry_count') or 0) + 1
                reason = "; ".join(issues)
                database.record_pipeline_error(
                    video['id'], 'Node 1b', 'BEAT_SCRIPT_QA', reason,
                    {'issues': issues}, retry_count)

                if retry_count <= MAX_AUTO_QA_RETRIES:
                    database.update_video(video['id'], {
                        'status': 'Pending_BeatScript',
                        'script_retry_count': retry_count,
                        'qa_feedback': f"Repair only these remaining issues: {reason}",
                        'error_message': None,
                    })
                    print(f"Node 1b: Video {video['id']} queued for beat script repair "
                          f"{retry_count}/{MAX_AUTO_QA_RETRIES}: {reason}")
                else:
                    database.fail_video(
                        video['id'], 'Node 1b', 'BEAT_SCRIPT_QA_REPEAT', reason,
                        {'issues': issues}, retry_count)
                    database.update_video(video['id'], {'script_retry_count': retry_count})
                    print(f"Node 1b: Video {video['id']} FAILED after {retry_count} attempts.")
                continue

            # Success path
            database.update_video(video['id'], {
                'beat_script': beat_script.model_dump_json(),
                'status': 'QA_BeatScript',
                'script_retry_count': 0,
                'qa_feedback': None,
                'error_message': None,
            })
            database.resolve_pipeline_errors(video['id'], 'Node 1b')
            print(f"Node 1b: Video {video['id']} → QA_BeatScript "
                  f"({beat_script.total_duration_sec:.0f}s, {len(beat_script.beats)} beats)")

        except Exception as e:
            error_str = str(e)
            print(f"Node 1b: Failed for video ID {video['id']}: {error_str}")
            database.fail_video(
                video['id'], 'Node 1b', 'BEAT_SCRIPT_EXCEPTION', error_str,
                attempt=(video.get('script_retry_count') or 0) + 1)


if __name__ == "__main__":
    while True:
        run()
        time.sleep(10)