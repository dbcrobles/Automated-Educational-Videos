"""Node 3b — Storyboard worker (long-form pipeline).

Polls Pending_Storyboard. For each beat element:
  - chart: resolve ref → DataPoint → build a ChartSpec-shaped dict
  - broll: stock search via node3's _try_stock_query (landscape-first),
    download to Backend/assets/{video_id}/beats/beat_{order}_{n}.mp4,
    fetch 2–3 candidates per broll cue so the owner can pick.
  - image/meme/sticker/text_callout: carry through unrealized with realized=false.

Output = Backend/assets/{video_id}/beats.json — the single source of truth
Remotion will render from (Phase 6) and the file the owner edits in Remotion
Studio. The same JSON is stored in the beats_json DB column as a recovery
checkpoint. Realization only ADDS keys; stripping them must still validate
against BeatScript.
"""
import os
import sys
import json
import time
import re

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from database import database
from schemas.beat import BeatScript
from schemas.research_artifact import ResearchArtifact
from nodes.asset_fetcher.node3_asset_fetcher import _try_stock_query, clean_query, validate_clip

ASSETS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'assets')
BROLL_CANDIDATE_COUNT = 3


def _build_chart_spec(ref, artifact):
    """Resolve a DataPoint ref into a ChartSpec-shaped dict matching ChartOverlay.tsx."""
    dp = next((d for d in artifact.data_points if d.id == ref), None)
    if not dp:
        raise ValueError(f"DataPoint ref '{ref}' not found in research artifact")

    all_years = all(re.match(r'^\d{4}$', p.label.strip()) for p in dp.points)
    chart_type = "line" if all_years else "bar"

    return {
        "chart_type": chart_type,
        "display_mode": "overlay",
        "title": dp.label,
        "unit": dp.unit,
        "points": [{"label": p.label, "value": p.value} for p in dp.points],
        "highlight": "",
        "source_url": dp.source_url,
        "source_label": dp.source_label or dp.source_url,
    }


def _realize_broll(video_id, beat_order, cue_index, description, used_sources, rejected_sources):
    """Fetch landscape candidates and retain the source ID for each path."""
    beats_dir = os.path.join(ASSETS_DIR, str(video_id), 'beats')
    os.makedirs(beats_dir, exist_ok=True)
    keyword = clean_query(str(description or "stock footage"))
    candidates = []
    candidate_sources = {}
    min_duration = 3

    for n in range(BROLL_CANDIDATE_COUNT):
        dest = os.path.join(beats_dir, f"beat_{beat_order}_{cue_index}_{n}.mp4")
        result = _try_stock_query(
            keyword, dest, min_duration, used_sources, rejected_sources,
            landscape_first=True)
        if result and validate_clip(dest, keyword):
            rel = os.path.relpath(dest, os.path.join(ASSETS_DIR, str(video_id)))
            candidates.append(rel)
            candidate_sources[rel] = result["source_id"]
        else:
            if os.path.exists(dest):
                os.remove(dest)
            break

    return candidates, candidate_sources


def _realize_element(video_id, beat_order, cue_index, element, artifact,
                     used_sources, rejected_sources):
    """Add realization fields to one element dict. Returns the enriched dict."""
    el = element.model_dump()
    el["realized"] = False

    if element.kind == "chart":
        el["chart"] = _build_chart_spec(element.ref, artifact)
        el["realized"] = True

    elif element.kind == "broll":
        candidates, candidate_sources = _realize_broll(
            video_id, beat_order, cue_index, element.description,
            used_sources, rejected_sources)
        if candidates:
            el["src"] = candidates[0]
            el["candidates"] = candidates
            el["source_id"] = candidate_sources[candidates[0]]
            el["candidate_sources"] = candidate_sources
            el["realized"] = True
        else:
            el["src"] = None
            el["candidates"] = []
            el["candidate_sources"] = {}

    return el


def _load_rejected_sources(video_id, beats_json_path):
    """On re-fetch, collect prior source IDs from beats.json so we exclude them."""
    if not os.path.exists(beats_json_path):
        return set()
    try:
        with open(beats_json_path) as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return set()
    rejected = set()
    for beat in data.get("beats", []):
        for el in beat.get("elements", []):
            if el.get("source_id"):
                rejected.add(el["source_id"])
            rejected.update(
                source_id for source_id in el.get("candidate_sources", {}).values()
                if source_id)
    return rejected


def _process_video(video):
    """Realize all beats for one video -> beats.json + DB column."""
    video_id = video['id']
    print(f"Node 3b: Processing video ID {video_id}: {video['topic']}")

    beat_script = BeatScript.model_validate_json(video['beat_script'])
    artifact = ResearchArtifact.model_validate_json(video['research_artifact'])

    beats_json_path = os.path.join(ASSETS_DIR, str(video_id), 'beats.json')
    replacement_requested = str(video.get('qa_feedback') or '').startswith('[VISUAL_REPLACEMENT]')
    rejected_sources = _load_rejected_sources(video_id, beats_json_path) if replacement_requested else set()
    used_sources = set()

    output = {"topic": beat_script.topic, "title": beat_script.title, "beats": []}

    for beat in beat_script.beats:
        beat_dict = beat.model_dump()
        beat_dict["elements"] = []
        for cue_idx, element in enumerate(beat.elements):
            beat_dict["elements"].append(_realize_element(
                video_id, beat.order, cue_idx, element, artifact,
                used_sources, rejected_sources))
        output["beats"].append(beat_dict)

    beats_dir = os.path.join(ASSETS_DIR, str(video_id))
    os.makedirs(beats_dir, exist_ok=True)
    with open(beats_json_path, 'w') as f:
        json.dump(output, f, indent=2)

    database.update_video(video_id, {
        'beats_json': json.dumps(output),
        'status': 'QA_Storyboard',
        'error_message': None,
        'qa_feedback': None,
    })
    database.resolve_pipeline_errors(video_id, 'Node 3b')
    print(f"Node 3b: Video {video_id} -> QA_Storyboard "
          f"({len(output['beats'])} beats, beats.json written)")


def run():
    print("Node 3b: Storyboard worker started.")
    videos = database.fetch_videos_by_status('Pending_Storyboard')
    for video in videos:
        if video.get('format') != 'long':
            continue
        try:
            if not video.get('beat_script'):
                raise Exception("No beat_script found - cannot storyboard.")
            if not video.get('research_artifact'):
                raise Exception("No research_artifact found - cannot resolve chart refs.")
            _process_video(video)
        except Exception as e:
            error_str = str(e)
            print(f"Node 3b: Failed for video ID {video['id']}: {error_str}")
            database.fail_video(video['id'], 'Node 3b', 'STORYBOARD_EXCEPTION', error_str)


if __name__ == "__main__":
    while True:
        run()
        time.sleep(10)