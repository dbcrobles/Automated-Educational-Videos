import os
import sys
import json
import time
import random
from typing import Optional
from pydantic import BaseModel
from google import genai
from google.genai import types

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from database import database

COST_RESEARCH_CALL = 0.05
COST_SCRIPT_CALL = 0.01

GEMINI_MODEL_RESEARCH = "gemini-3.1-pro-preview"
GEMINI_MODEL_STRUCTURED = "gemini-3.5-flash"

VALID_PACING = {"rapid", "standard", "slow_pan"}
VALID_TRANSITIONS = {"whip_pan", "zoom_punch", "crossfade", "dissolve", "dip_to_black"}
VALID_MOODS = {"tense", "uplifting", "mysterious", "neutral"}

def load_accounts_config():
    config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'accounts_config.json')
    with open(config_path, 'r') as f:
        return json.load(f)

class Hook(BaseModel):
    hook_type: str
    hook_text: str

class Scene(BaseModel):
    visual_search_query: str
    narration: str
    pacing_style: str
    transition_hint: str
    hook: Optional[Hook] = None

class ScriptOutput(BaseModel):
    title: str
    word_count: int
    hook_score: float
    retention_estimate: float
    music_mood: str
    scenes: list[Scene]
    sources: list[str]

VIBES = [
    "Frame this with a highly aggressive, 'us vs. them' contrarian angle.",
    "Adopt a mysterious, suspenseful tone, teasing a major secret.",
    "Be highly educational and data-driven, using rapid-fire statistics.",
    "Frame this as a bizarre, almost unbelievable true story.",
    "Adopt an urgent, 'you need to know this right now' warning tone.",
    "Adopt a highly empathetic, 'we are in this together' confessional tone.",
    "Frame this as a controversial myth-buster, aggressively debunking what 'they' told you.",
    "Use a 'David vs Goliath' underdog framing, where the viewer can beat the system."
]

def generate_script(topic, account_id, qa_feedback=None, cta_text=None):
    ACCOUNTS_CONFIG = load_accounts_config()
    account_settings = ACCOUNTS_CONFIG.get(account_id, {})
    persona = account_settings.get('system_instruction', "You are a viral short-form video scriptwriter.")

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise Exception("GEMINI_API_KEY environment variable not set.")

    client = genai.Client(api_key=api_key)

    # PASS 1: Research via Google Search Tool
    research_prompt = f"""
    Research the topic: "{topic}".
    Your goal is to gather highly engaging, counter-intuitive facts suitable for a short-form viral video.
    Provide a detailed factual summary of your findings.
    CRITICAL: You MUST include the exact URLs of the sources you used at the end of your summary.
    """

    search_tool = {"google_search": {}}

    print(f"Node 1: Pass 1 (Research) for '{topic}'...")
    try:
        research_response = client.models.generate_content(
            model=GEMINI_MODEL_RESEARCH,
            contents=research_prompt,
            config=types.GenerateContentConfig(temperature=0.7, tools=[search_tool]),
        )
        research_text = research_response.text
        if not research_text:
            raise Exception("Pass 1 returned empty research text.")
    except Exception as e:
        print(f"Node 1: Pass 1 failed: {e}. Falling back to knowledge-only mode.")
        research_response = client.models.generate_content(
            model=GEMINI_MODEL_RESEARCH,
            contents=research_prompt,
            config=types.GenerateContentConfig(temperature=0.7),
        )
        research_text = research_response.text or f"Topic: {topic}"

    # PASS 2: Structured JSON generation (flash-tier)
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
    Angle/Vibe Constraint: {selected_vibe}

    Here is the factual research and sources you MUST use to build the script:
    {research_text}

    Content Philosophy:
    Your scripts must completely avoid generic, robotic language. Focus on high-impact storytelling and counter-intuitive facts. The tone should be punchy and fast-paced.

    Formatting Rules & Pipeline Constraints:
    1. Narration: Write the narration exactly how it should be spoken. Keep sentences short and punchy. Perfect spelling everywhere.
    2. Stock Video Sourcing: Every `visual_search_query` MUST describe *motion* (e.g. 'aerial city traffic night', 'hands typing keyboard closeup'), never a static scene. 2-5 literal words, no conversational filler.
    3. Dynamic Pacing: For every scene, assign a `pacing_style`:
       - 'rapid': Use for high-tension montages, chaotic moments, or rapid-fire facts.
       - 'standard': Use for normal explanatory dialogue.
       - 'slow_pan': Use sparingly for dramatic breathing room, profound statements, or establishing shots.
    4. Transition Hints: Assign a `transition_hint` per scene based on pacing:
       - rapid → 'whip_pan' or 'zoom_punch' (100-150ms / 4 frames)
       - standard → 'crossfade' (200-300ms / 8 frames)
       - slow_pan → 'dissolve' or 'dip_to_black' (400-500ms / 14 frames)
       No more than 2 consecutive scenes with the same pacing_style; use deliberate contrast patterns (rapid-rapid-slow_pan = tension/release).
    5. Music Mood: Choose one `music_mood` for the whole video: 'tense', 'uplifting', 'mysterious', or 'neutral'.
    6. Word-Count Gate: Total narration must be 170-260 words (~65-100s at 2.6 words/sec). Report the true count in `word_count`.
    7. CTA Injection: The final scene's narration MUST end with this exact call-to-action: "{cta_text or 'Follow for more'}"
    8. Hook: The first scene MUST include a `hook` object with `hook_type` ("question", "statistic", "controversy", or "promise") and exact `hook_text`.
    9. Self-QA: Score your own hook 0-10 (`hook_score`) and estimate 3-second retention % (`retention_estimate`). Be harsh — a generic hook is a 4.
    10. Do not hallucinate outside the retrieved search context.
    11. Cite the exact URLs of the sources provided in the research text.

    Output strictly as a JSON object matching the requested schema.
    """

    print(f"Node 1: Pass 2 (Structured JSON) for '{topic}'...")
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
        raise Exception("Pass 2 returned an empty response.")

    return json.loads(result_text)

def _coerce_enums(output):
    """Coerce invalid enum values to defaults — don't fail the video over one bad value."""
    if output.get('music_mood') not in VALID_MOODS:
        output['music_mood'] = 'neutral'
    for scene in output.get('scenes', []):
        if scene.get('pacing_style') not in VALID_PACING:
            scene['pacing_style'] = 'standard'
        if scene.get('transition_hint') not in VALID_TRANSITIONS:
            scene['transition_hint'] = 'crossfade'
    return output

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
            database.add_cost(video['id'], COST_RESEARCH_CALL)
            database.add_cost(video['id'], COST_SCRIPT_CALL)

            # Coerce invalid enums
            output = _coerce_enums(output)

            # Post-generation validation: word count + hook score
            scenes = output.get('scenes', [])
            actual_word_count = sum(len(s.get('narration', '').split()) for s in scenes)
            hook_score = output.get('hook_score', 0)

            if actual_word_count < 160 or actual_word_count > 280 or hook_score < 6:
                retry_count = (video.get('script_retry_count') or 0) + 1
                reason = f"word_count={actual_word_count} (need 160-280), hook_score={hook_score} (need >=6)."
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