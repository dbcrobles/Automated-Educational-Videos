import os
import sys
import json
import time
import base64
import requests

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from database import database

ELEVENLABS_USD_PER_CHAR = 0.00011

def load_accounts_config():
    config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'accounts_config.json')
    with open(config_path, 'r') as f:
        return json.load(f)

ELEVENLABS_API_KEY = os.environ.get('ELEVENLABS_API_KEY')

DEFAULT_VOICE_ID = "nPczCjzI2devNBz1zQrb"

# Voice pool tagged by the moods each voice suits.  music_mood comes from the
# script (Node 1): "tense" | "uplifting" | "mysterious" | "neutral".
VOICE_POOL = [
    {"id": "nPczCjzI2devNBz1zQrb", "name": "Brian (American, deep)",       "moods": ["tense", "mysterious", "neutral"]},
    {"id": "IKne3meq5aSn9XLyUdCD", "name": "Charlie (American, natural)",  "moods": ["uplifting", "neutral"]},
    {"id": "JBFqnCBsd6RMkjVDRZzb", "name": "George (British, warm)",       "moods": ["tense", "mysterious", "neutral"]},
    {"id": "TX3LPaxmHKxFdv7VOQHJ", "name": "Liam (American, articulate)",  "moods": ["tense", "neutral"]},
    {"id": "bIHbv24MWmeRgasZH58o", "name": "Will (American, friendly)",    "moods": ["uplifting", "neutral"]},
    {"id": "9BWtsMINqrJLrRacOk9x", "name": "Aria (American, expressive)",  "moods": ["uplifting", "mysterious"]},
    {"id": "EXAVITQu4vr4xnSDxMaL", "name": "Sarah (American, calm)",       "moods": ["mysterious", "neutral"]},
    {"id": "FGY2WhTYpPnrIDTdsKH5", "name": "Laura (American, upbeat)",     "moods": ["uplifting"]},
    {"id": "Xb7hH8MSUJpSbSDYk0k2", "name": "Alice (British, confident)",   "moods": ["tense", "uplifting", "neutral"]},
    {"id": "SAz9YHcvj6GT2YYXdXww", "name": "River (American, neutral)",    "moods": ["mysterious", "neutral"]},
]

def select_voice(video_id, script_json_str, account_settings):
    """Pick a voice for this video.

    - account voice_mode == "fixed" → always use the account's configured voice.
    - otherwise (default "random") → random voice from the pool matching the
      script's music_mood, seeded by video_id so re-runs pick the same voice.
    Returns (voice_id, voice_name).
    """
    import random

    if account_settings.get('voice_mode') == 'fixed':
        vid = account_settings.get('elevenlabs_voice_id', DEFAULT_VOICE_ID)
        name = account_settings.get('elevenlabs_voice_name', vid)
        return vid, name

    mood = 'neutral'
    try:
        mood = json.loads(script_json_str).get('music_mood', 'neutral') or 'neutral'
    except Exception:
        pass

    matches = [v for v in VOICE_POOL if mood in v['moods']]
    if not matches:
        matches = VOICE_POOL
    choice = random.Random(video_id).choice(matches)
    print(f"Node 2: mood='{mood}' → voice '{choice['name']}'")
    return choice['id'], choice['name']

def _chars_to_words(alignment):
    """Convert ElevenLabs character-level alignment to word-level list."""
    chars = alignment['characters']
    starts = alignment['character_start_times_seconds']
    ends = alignment['character_end_times_seconds']

    words = []
    current_word = ""
    current_start = None

    for char, start, end in zip(chars, starts, ends):
        if char == " " or char == "\n":
            if current_word:
                words.append({"word": current_word, "start": current_start, "end": start})
                current_word = ""
                current_start = None
        else:
            if current_start is None:
                current_start = start
            current_word += char

    if current_word:
        words.append({"word": current_word, "start": current_start, "end": ends[-1]})

    return words

def _build_scene_timing(words, scene_word_counts):
    """Walk the word list, slicing scene_word_counts[i] words per scene."""
    timing = []
    idx = 0
    for i, count in enumerate(scene_word_counts):
        if idx + count > len(words):
            # Alignment merged something — fall back to proportional allocation
            print(f"Node 2: Word count mismatch ({idx + count} > {len(words)}), using proportional fallback.")
            total_chars = sum(len(w["word"]) for w in words[idx:])
            remaining_scenes = len(scene_word_counts) - i
            if total_chars == 0:
                break
            for j in range(remaining_scenes):
                scene_chars = sum(len(words[k]["word"]) for k in range(idx, min(idx + count, len(words))))
                if idx < len(words):
                    start = words[idx]["start"]
                    end = words[min(idx + count - 1, len(words) - 1)]["end"]
                    timing.append({"scene_index": i + j, "start": start, "end": end})
                    idx += count
            break
        scene_words = words[idx:idx + count]
        if scene_words:
            timing.append({
                "scene_index": i,
                "start": scene_words[0]["start"],
                "end": scene_words[-1]["end"],
            })
        idx += count
    return timing

def generate_voiceover(video_id, script_json_str, voice_id):
    if not ELEVENLABS_API_KEY:
        raise Exception("ELEVENLABS_API_KEY not set")

    try:
        script_data = json.loads(script_json_str)
        scenes = script_data.get('scenes', [])
    except Exception as e:
        raise Exception(f"Failed to parse script JSON: {e}")

    # Build narrations with legacy fallback
    narrations = []
    for scene in scenes:
        text = scene.get('narration') or scene.get('audio_narration', '')
        narrations.append(text)

    scene_word_counts = [len(n.split()) for n in narrations]
    full_text = " ".join(narrations)

    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/with-timestamps"
    headers = {
        "xi-api-key": ELEVENLABS_API_KEY,
        "Content-Type": "application/json"
    }
    payload = {
        "text": full_text,
        "model_id": "eleven_multilingual_v2"
    }

    response = requests.post(url, json=payload, headers=headers, timeout=60)
    response.raise_for_status()

    data = response.json()
    audio_bytes = base64.b64decode(data['audio_base64'])
    alignment = data['alignment']

    # Build word-level captions
    words = _chars_to_words(alignment)

    # Build per-scene timing
    timing = _build_scene_timing(words, scene_word_counts)

    # Write files to assets/{id}/
    assets_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'assets')
    video_assets_dir = os.path.join(assets_dir, str(video_id))
    os.makedirs(video_assets_dir, exist_ok=True)

    audio_path = os.path.join(video_assets_dir, "voiceover.mp3")
    timing_path = os.path.join(video_assets_dir, "timing.json")
    captions_path = os.path.join(video_assets_dir, "captions.json")

    with open(audio_path, 'wb') as f:
        f.write(audio_bytes)

    with open(timing_path, 'w') as f:
        json.dump(timing, f, indent=2)

    with open(captions_path, 'w') as f:
        json.dump(words, f, indent=2)

    # Cost logging
    cost = len(full_text) * ELEVENLABS_USD_PER_CHAR
    database.add_cost(video_id, cost)

    return audio_path

def run():
    print("Node 2: Voice worker started.")
    videos = database.fetch_videos_by_status('Pending_Voice')

    ACCOUNTS_CONFIG = load_accounts_config()

    for video in videos:
        print(f"Generating voiceover for video ID {video['id']}")
        account_settings = ACCOUNTS_CONFIG.get(video['account_id'], {})
        voice_id, voice_name = select_voice(video['id'], video['script'], account_settings)

        try:
            audio_path = generate_voiceover(video['id'], video['script'], voice_id)

            database.update_video(video['id'], {
                'voiceover_path': audio_path,
                'voice_name': voice_name,
                'status': 'Pending_Assets',
                'error_message': None
            })
            print(f"Updated video ID {video['id']} to Pending_Assets")

        except Exception as e:
            error_str = str(e)
            print(f"Failed to generate voiceover: {error_str}")
            database.update_video(video['id'], {
                'status': 'Failed',
                'error_message': f"Node 2 (Voice) Error: {error_str}"
            })

if __name__ == "__main__":
    while True:
        run()
        time.sleep(10)