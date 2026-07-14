"""Phase 8: derive a vertical short from one beat of a published long-form video.

Owner rule: shorts are RE-RENDERED from the beat's element specs — never
cropped from the finished 16:9 MP4. Narration is the owner's real voice sliced
at beat boundaries; captions are sliced in-range and re-based to 0; the beat's
hook_label becomes an opening title card. Renders through the ShortFromBeat
Remotion composition (1080×1920). No LLM calls — the beat carries everything.
"""
import os
import sys
import json
import math
import shutil
import subprocess

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from database import database
from nodes.render_worker.node4_render_worker import (
    FPS, WIDTH, HEIGHT, FFMPEG, ASSETS_DIR,
    load_captions_words, make_public_symlinks, remove_public_symlinks,
    preprocess_clip, probe_duration, render_remotion, stamp_metadata,
)

INTRO_CARD_SEC = 2.0  # hook_label title card over the first ~2s

# Landscape corner overlays don't survive 9:16 — remap to vertical-safe bands.
VERTICAL_POSITION_MAP = {
    'top_left': 'upper_third', 'top_right': 'upper_third',
    'bottom_left': 'lower_third', 'bottom_right': 'lower_third',
}


def _fetch_video(video_id):
    conn = database.get_connection()
    conn.row_factory = database.sqlite3.Row
    row = conn.execute("SELECT * FROM videos WHERE id = ?", (video_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def load_parent_beat(parent, beat_order):
    """The realized beat spec: prefer beats.json on disk, else the DB checkpoint."""
    beats_path = os.path.join(ASSETS_DIR, str(parent['id']), 'beats.json')
    if os.path.exists(beats_path):
        with open(beats_path) as f:
            data = json.load(f)
    else:
        data = json.loads(parent.get('beats_json') or '{}')
    beat = next((b for b in data.get('beats', [])
                 if b.get('order') == beat_order), None)
    if not beat:
        raise Exception(f"Beat {beat_order} not found for parent video {parent['id']}.")
    if (not isinstance(beat.get('start'), (int, float))
            or not isinstance(beat.get('end'), (int, float))):
        raise Exception(f"Beat {beat_order} has no narration timing (start/end).")
    return beat


def slice_voiceover(parent, beat, out_path):
    """Accurate slice of the parent's real narration at the beat boundaries."""
    src = database.asset_path(parent['id'], 'voiceover.mp3')
    if not os.path.exists(src):
        raise Exception(f"Parent voiceover not found: {src}")
    cmd = [FFMPEG, '-y', '-i', src,
           '-ss', f"{float(beat['start']):.3f}", '-to', f"{float(beat['end']):.3f}",
           '-c:a', 'libmp3lame', '-q:a', '2', out_path]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        tail = '\n'.join(r.stderr.splitlines()[-10:])
        raise Exception(f"Voiceover slice failed:\n{tail}")


def slice_captions(parent, beat, out_path):
    """Caption words inside [start, end), re-based to 0 for the short's timeline."""
    words = load_captions_words({'id': parent['id']})
    start, end = float(beat['start']), float(beat['end'])
    sliced = [{'word': w['word'],
               'start': round(max(0.0, w['start'] - start), 3),
               'end': round(min(end - start, w['end'] - start), 3)}
              for w in words if w['end'] > start and w['start'] < end]
    with open(out_path, 'w') as f:
        json.dump(sliced, f, indent=2)
    return sliced


def prepare_elements(parent, beat, short_dir, duration_sec):
    """Copy realized element media into the short's asset dir; remap overlay
    positions to vertical-safe bands. Charts stay spec-driven (no media file)."""
    elements = []
    parent_dir = os.path.join(ASSETS_DIR, str(parent['id']))
    for i, el in enumerate(json.loads(json.dumps(beat.get('elements', [])))):
        el['position'] = VERTICAL_POSITION_MAP.get(el.get('position'), el.get('position'))
        src = el.get('src')
        if src:
            abs_src = os.path.join(parent_dir, src)
            if not os.path.exists(abs_src):
                raise Exception(f"Element media missing: {src} (parent {parent['id']}). "
                                "Parent intermediates may have been cleaned up.")
            if str(src).endswith('.mp4'):
                name = f'short_el_{i}.mp4'  # re-letterboxed to 1080×1920
                preprocess_clip(abs_src, os.path.join(short_dir, name),
                                max(1.0, duration_sec + 0.5))
            else:
                name = f'short_el_{i}{os.path.splitext(src)[1]}'
                shutil.copy2(abs_src, os.path.join(short_dir, name))
            el['src'] = name
        elements.append(el)
    return elements


def build_short_props(short, parent, beat, captions, elements, duration_sec):
    """Props contract for the ShortFromBeat composition (see Phase 8 handoff)."""
    props = {
        'fps': FPS, 'width': WIDTH, 'height': HEIGHT,
        'durationInFrames': int(math.ceil(duration_sec * FPS)),
        'assetBase': str(short['id']),
        'introCard': {'text': beat.get('hook_label') or short['topic'],
                      'durationInFrames': int(INTRO_CARD_SEC * FPS)},
        'voiceoverSrc': f"{short['id']}/voiceover.mp3",
        'captions': captions,
        'elements': elements,
        'layoutMode': 'vertical',  # chart legend below, fonts ~1.4×
        'accentColor': '#FFD447',
        'compliance': {'text': 'AI-Assisted', 'fullDuration': True},
    }
    comp_json = os.path.join(ASSETS_DIR, str(short['id']), 'comp_short.json')
    with open(comp_json, 'w') as f:
        json.dump(props, f, indent=2)
    return comp_json


def render_short(short):
    parent = _fetch_video(short.get('parent_video_id') or 0)
    if not parent:
        raise Exception("Parent video row not found.")
    beat = load_parent_beat(parent, short.get('beat_order'))
    duration_sec = float(beat['end']) - float(beat['start'])
    if duration_sec <= 1.0:
        raise Exception(f"Beat {short.get('beat_order')} is too short ({duration_sec:.1f}s).")

    short_dir = os.path.join(ASSETS_DIR, str(short['id']))
    os.makedirs(short_dir, exist_ok=True)
    slice_voiceover(parent, beat, os.path.join(short_dir, 'voiceover.mp3'))
    captions = slice_captions(parent, beat, os.path.join(short_dir, 'captions.json'))
    elements = prepare_elements(parent, beat, short_dir, duration_sec)
    comp_json = build_short_props(short, parent, beat, captions, elements, duration_sec)

    rendered = os.path.join(short_dir, 'rendered_short.mp4')
    final_path = os.path.join(short_dir, 'final.mp4')
    make_public_symlinks(short['id'])
    try:
        print(f"ShortRender: {duration_sec:.1f}s beat {short.get('beat_order')} "
              f"of video {parent['id']} via Remotion (ShortFromBeat)...")
        render_remotion(comp_json, rendered, composition='ShortFromBeat')
    finally:
        remove_public_symlinks(short['id'])
    stamp_metadata(short, rendered, final_path)

    out_dur = probe_duration(final_path)
    if abs(out_dur - duration_sec) > 1.0:
        raise Exception(f"Short render sanity check failed: output {out_dur:.1f}s "
                        f"vs beat {duration_sec:.1f}s.")
    print(f"ShortRender: final {out_dur:.1f}s → {final_path}")
    return final_path


def run():
    for video in database.fetch_videos_by_status('Pending_ShortRender'):
        if video.get('format') != 'short_derived':
            continue
        print(f"ShortRender: video {video['id']} — '{video['topic']}'")
        try:
            final_path = render_short(video)
            database.update_video(video['id'], {
                'final_path': final_path,
                'status': 'QA_Final',
                'compliance_metadata': json.dumps({
                    'ai_disclosure': 'AI-Assisted',
                    'derived_from': video.get('parent_video_id'),
                    'sponsored': bool(video.get('is_sponsored')),
                }),
                'error_message': None,
            })
            database.resolve_pipeline_errors(video['id'], 'ShortRender')
            print(f"ShortRender: video {video['id']} → QA_Final.")
        except Exception as e:
            print(f"ShortRender: FAILED video {video['id']}: {e}")
            database.fail_video(video['id'], 'ShortRender', 'SHORT_RENDER_FAILED', str(e))