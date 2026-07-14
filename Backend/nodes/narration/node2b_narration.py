"""Node 2b — align uploaded owner narration to beat boundaries."""
import json
import os
import subprocess
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from database import database

ASSETS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "assets")
FFMPEG = "/opt/homebrew/bin/ffmpeg"
NARRATION_EXTENSIONS = (".mp3", ".m4a", ".wav")
_MODEL = None


def find_narration(video_id):
    folder = os.path.join(ASSETS_DIR, str(video_id))
    return next((os.path.join(folder, f"narration{ext}")
                 for ext in NARRATION_EXTENSIONS
                 if os.path.exists(os.path.join(folder, f"narration{ext}"))), None)


def convert_audio(source_path):
    """Normalize an upload to the canonical MP3 consumed by both renderers."""
    output_path = os.path.join(os.path.dirname(source_path), "voiceover.mp3")
    result = subprocess.run([
        FFMPEG, "-y", "-i", source_path, "-vn", "-ar", "44100", "-ac", "2",
        "-c:a", "libmp3lame", "-q:a", "2", output_path,
    ], capture_output=True, text=True)
    if result.returncode != 0:
        detail = result.stderr.splitlines()[-1] if result.stderr else "unknown error"
        raise RuntimeError(f"Narration conversion failed: {detail}")
    return output_path


def _whisper_model():
    global _MODEL
    if _MODEL is None:
        from faster_whisper import WhisperModel
        _MODEL = WhisperModel("small", device="auto", compute_type="int8")
    return _MODEL


def _transcribe(audio_path, model=None):
    segments, _ = (model or _whisper_model()).transcribe(
        audio_path, word_timestamps=True)
    words = []
    for segment in segments:
        for word in segment.words or []:
            text = word.word.strip()
            if text and word.start is not None and word.end is not None:
                words.append({"word": text, "start": float(word.start), "end": float(word.end)})
    if not words:
        raise ValueError("No spoken words were detected in the narration.")
    return words


def _load_beats(video):
    path = os.path.join(ASSETS_DIR, str(video["id"]), "beats.json")
    candidates = []
    if os.path.exists(path):
        with open(path) as source:
            candidates.append(json.load(source))
    for field in ("beats_json", "beat_script"):
        if video.get(field):
            candidates.append(json.loads(video[field]))
    for payload in candidates:
        if payload.get("beats"):
            return path, payload

    script = json.loads(video.get("script") or "{}")
    beats = [{
        "order": index,
        "spoken_text": scene.get("narration") or scene.get("audio_narration", ""),
        "elements": [],
    } for index, scene in enumerate(script.get("scenes", []))]
    if not beats:
        raise ValueError("No beats or legacy scenes found for narration alignment.")
    return path, {"topic": video.get("topic", ""), "beats": beats}


def build_beat_timing(words, beats):
    """Allocate aligned words by scripted beat word counts, scaling only small drift."""
    counts = [len(str(beat.get("spoken_text") or "").split()) for beat in beats]
    expected, actual = sum(counts), len(words)
    if not expected or any(count == 0 for count in counts):
        raise ValueError("Every beat must contain spoken_text before narration alignment.")
    drift = abs(actual - expected) / expected
    if drift >= 0.10:
        raise ValueError(
            f"Narration differs from the script by {drift:.1%} ({actual} vs {expected} words).")

    timing, start_index, cumulative = [], 0, 0
    for index, (beat, count) in enumerate(zip(beats, counts)):
        cumulative += count
        end_index = actual if index == len(beats) - 1 else round(cumulative * actual / expected)
        remaining = len(beats) - index - 1
        end_index = max(start_index + 1, min(end_index, actual - remaining))
        beat_words = words[start_index:end_index]
        start, end = beat_words[0]["start"], beat_words[-1]["end"]
        beat["start"], beat["end"] = start, end
        timing.append({
            "scene_index": index, "start": start, "end": end,
            "timing_source": "narration_alignment",
        })
        start_index = end_index
    return timing


def _write_json(path, payload):
    temp_path = f"{path}.tmp"
    with open(temp_path, "w") as destination:
        json.dump(payload, destination, indent=2)
    os.replace(temp_path, path)


def process_video(video, model=None):
    narration_path = find_narration(video["id"])
    if not narration_path:
        return False
    voiceover_path = convert_audio(narration_path)
    words = _transcribe(voiceover_path, model=model)
    beats_path, payload = _load_beats(video)
    timing = build_beat_timing(words, payload["beats"])
    os.makedirs(os.path.dirname(beats_path), exist_ok=True)
    _write_json(os.path.join(os.path.dirname(beats_path), "captions.json"), words)
    _write_json(os.path.join(os.path.dirname(beats_path), "timing.json"), timing)
    _write_json(beats_path, payload)

    next_status = "Pending_LongRender" if video.get("format") == "long" else "Pending_Assets"
    database.update_video(video["id"], {
        "beats_json": json.dumps(payload), "voiceover_path": voiceover_path,
        "voice_name": "Owner narration", "status": next_status, "error_message": None,
    })
    database.resolve_pipeline_errors(video["id"], "Node 2b")
    print(f"Node 2b: Video {video['id']} -> {next_status} ({len(words)} words)")
    return True


def run():
    print("Node 2b: Narration alignment worker started.")
    for video in database.fetch_videos_by_status("Awaiting_Narration"):
        if not find_narration(video["id"]):
            continue
        try:
            process_video(video)
        except Exception as error:
            database.fail_video(
                video["id"], "Node 2b", "NARRATION_ALIGNMENT", str(error))


if __name__ == "__main__":
    run()