import os
import sys
import re
import json
import time
import glob
import random
import shutil
import subprocess
import math
import struct
import wave

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from database import database

FPS          = 30
WIDTH        = 1080
HEIGHT       = 1920
FFMPEG       = "/opt/homebrew/bin/ffmpeg"
FFPROBE      = "/opt/homebrew/bin/ffprobe"
BACKEND_DIR  = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ASSETS_DIR   = os.path.join(BACKEND_DIR, 'assets')
REMOTION_DIR = os.path.join(BACKEND_DIR, 'remotion')

SCRIPT_MODEL = "gpt-5.6-luna / gemini-3.5-flash fallback"

# transition_hint → (type, durationInFrames)
TRANSITION_MAP = {
    'whip_pan':     ('whip_pan', 4),
    'zoom_punch':   ('zoom_punch', 4),
    'crossfade':    ('crossfade', 8),
    'dissolve':     ('dissolve', 14),
    'dip_to_black': ('dip_to_black', 14),
}
PACING_DEFAULT_SEC = {'rapid': 2, 'standard': 4, 'slow_pan': 8}


# ─── Probing helpers ──────────────────────────────────────────────────────────

def probe_duration(path):
    r = subprocess.run(
        [FFPROBE, '-v', 'error', '-show_entries', 'format=duration',
         '-of', 'default=noprint_wrappers=1:nokey=1', path],
        capture_output=True, text=True)
    return float(r.stdout.strip())


# ─── Legacy SRT fallback (videos rendered before captions.json existed) ───────

def srt_timestamp_to_seconds(ts):
    ts = ts.strip().replace(',', '.')
    h, m, s = ts.split(':')
    return int(h) * 3600 + int(m) * 60 + float(s)


def parse_srt(srt_path):
    with open(srt_path, 'r', encoding='utf-8') as f:
        content = f.read()
    captions = []
    for block in [b.strip() for b in re.split(r'\n\s*\n', content) if b.strip()]:
        lines = [l.strip() for l in block.splitlines() if l.strip()]
        ts_idx = next((i for i, l in enumerate(lines) if '-->' in l), None)
        if ts_idx is None:
            continue
        parts = lines[ts_idx].split('-->')
        if len(parts) != 2:
            continue
        try:
            start = srt_timestamp_to_seconds(parts[0])
            end = srt_timestamp_to_seconds(parts[1])
        except Exception:
            continue
        text = ' '.join(lines[ts_idx + 1:]).strip()
        if text:
            captions.append({'text': text, 'start': start, 'end': end})
    return captions


def srt_to_words(srt_path):
    """Approximate word-level timing from segment-level SRT (legacy shim)."""
    words = []
    for seg in parse_srt(srt_path):
        seg_words = seg['text'].split()
        if not seg_words:
            continue
        step = (seg['end'] - seg['start']) / len(seg_words)
        for i, w in enumerate(seg_words):
            words.append({'word': w,
                          'start': seg['start'] + i * step,
                          'end': seg['start'] + (i + 1) * step})
    return words


# ─── Input resolution ─────────────────────────────────────────────────────────

def _scene_clip_key(path):
    m = re.search(r'scene_(\d+)(?:_clip_(\d+))?\.mp4$', path)
    return (int(m.group(1)), int(m.group(2) or 0)) if m else None


def _group_scene_clips(paths):
    """Group scene_N.mp4 and scene_N_clip_M.mp4 while preserving legacy lists."""
    groups = {}
    for path in paths:
        key = _scene_clip_key(path)
        if key is None:
            return [[p] for p in paths]
        groups.setdefault(key[0], []).append((key[1], path))
    return [[path for _, path in sorted(groups[index])]
            for index in sorted(groups)]


def find_scene_clips(video):
    """Locate and group one or more source clips for each scripted scene."""
    vid = video['id']
    clips = glob.glob(os.path.join(ASSETS_DIR, str(vid), 'scene_*.mp4'))
    if clips:
        return _group_scene_clips(clips)

    # Fallback 1: DB video_path holds a JSON array (pre-fix behaviour)
    try:
        paths = json.loads(video.get('video_path') or '')
        if isinstance(paths, list):
            paths = [p for p in paths if os.path.exists(p)]
            if paths:
                return _group_scene_clips(paths)
    except Exception:
        pass

    # Fallback 2: legacy flat layout video_{id}_scene_N.mp4
    clips = glob.glob(os.path.join(ASSETS_DIR, f'video_{vid}_scene_*.mp4'))
    return _group_scene_clips(clips)


def load_scene_durations(video, num_clips, scenes, audio_dur):
    """Per-scene display durations in seconds.

    Primary: timing.json — scene i runs from its narration start to the next
    scene's narration start (no dead air), last scene runs to end of audio.
    Fallback: pacing-style defaults, scaled so the total matches the audio.
    """
    timing_path = database.asset_path(video['id'], 'timing.json')
    if os.path.exists(timing_path):
        try:
            with open(timing_path) as f:
                timing = json.load(f)
            if len(timing) == num_clips and num_clips > 0:
                durations = []
                for i in range(num_clips):
                    start = timing[i]['start']
                    end = timing[i + 1]['start'] if i + 1 < num_clips else audio_dur
                    durations.append(max(1.0, end - start))
                return durations
            print(f"Node 4: timing.json has {len(timing)} entries for {num_clips} clips — using pacing fallback.")
        except Exception as e:
            print(f"Node 4: failed to read timing.json ({e}) — using pacing fallback.")

    # Pacing-enum fallback, scaled to cover the full voiceover
    durations = []
    for i in range(num_clips):
        pacing = scenes[i].get('pacing_style', 'standard') if i < len(scenes) else 'standard'
        durations.append(PACING_DEFAULT_SEC.get(pacing, 4))
    total = sum(durations)
    if total > 0 and audio_dur > 0:
        scale = audio_dur / total
        durations = [d * scale for d in durations]
    return durations


def load_captions_words(video):
    """Word list [{word, start, end}] from captions.json, or legacy SRT shim."""
    cap_path = database.asset_path(video['id'], 'captions.json')
    if os.path.exists(cap_path):
        try:
            with open(cap_path) as f:
                return json.load(f)
        except Exception:
            pass
    srt_path = os.path.join(ASSETS_DIR, f"captions_{video['id']}.srt")
    if os.path.exists(srt_path):
        return srt_to_words(srt_path)
    return []


def resolve_voiceover(video):
    """Ensure the voiceover lives at assets/{id}/voiceover.mp3 (Remotion serves per-id folders)."""
    vid_dir = os.path.join(ASSETS_DIR, str(video['id']))
    os.makedirs(vid_dir, exist_ok=True)
    canonical = os.path.join(vid_dir, 'voiceover.mp3')
    if os.path.exists(canonical):
        return canonical
    src = video.get('voiceover_path')
    if src and os.path.exists(src):
        shutil.copy(src, canonical)
        return canonical
    raise Exception("Voiceover audio missing. Cannot render.")


def pick_music(video_id, mood):
    """Deterministic music pick from assets/music/{mood}/, any mood as fallback."""
    mood_dir = os.path.join(ASSETS_DIR, 'music', mood)
    tracks = sorted(glob.glob(os.path.join(mood_dir, '*.mp3')))
    if not tracks:
        tracks = sorted(glob.glob(os.path.join(ASSETS_DIR, 'music', '*', '*.mp3')))
    if not tracks:
        return None
    choice = random.Random(video_id).choice(tracks)
    rel = os.path.relpath(choice, os.path.join(ASSETS_DIR, 'music'))
    return f"music/{rel}"


def ensure_sfx_assets():
    """Create a tiny built-in effects palette without another API or asset dependency."""
    sfx_dir = os.path.join(ASSETS_DIR, 'sfx')
    os.makedirs(sfx_dir, exist_ok=True)
    sample_rate, length = 44100, 0.8
    for name in ('impact', 'whoosh', 'chime'):
        path = os.path.join(sfx_dir, f'{name}.wav')
        if os.path.exists(path):
            continue
        rng = random.Random(name)
        frames = []
        for index in range(round(sample_rate * length)):
            t = index / sample_rate
            fade = max(0, 1 - t / length)
            if name == 'impact':
                value = (math.sin(2 * math.pi * (75 - 35 * t) * t) + rng.uniform(-0.35, 0.35)) * fade ** 4
            elif name == 'whoosh':
                swell = math.sin(math.pi * t / length) ** 2
                value = rng.uniform(-1, 1) * swell * math.sin(2 * math.pi * (250 + 900 * t) * t)
            else:
                value = (math.sin(2 * math.pi * 880 * t) + 0.5 * math.sin(2 * math.pi * 1320 * t)) * fade ** 3
            frames.append(struct.pack('<h', int(max(-1, min(1, value * 0.45)) * 32767)))
        with wave.open(path, 'wb') as audio:
            audio.setparams((1, 2, sample_rate, 0, 'NONE', 'not compressed'))
            audio.writeframes(b''.join(frames))


# ─── Preprocessing (FFmpeg normalisation for Remotion) ───────────────────────

BASE_VF = (f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,"
           f"crop={WIDTH}:{HEIGHT},setsar=1,fps={FPS}")

LONG_WIDTH, LONG_HEIGHT = 1920, 1080
LONG_VF = (f"scale={LONG_WIDTH}:{LONG_HEIGHT}:force_original_aspect_ratio=increase,"
           f"crop={LONG_WIDTH}:{LONG_HEIGHT},setsar=1,fps={FPS}")


def preprocess_clip(src, dst, needed_sec, keep_audio=False, vf=BASE_VF):
    src_dur = probe_duration(src)
    cmd = [FFMPEG, '-y']
    if src_dur < needed_sec:
        cmd += ['-stream_loop', '-1']
    cmd += ['-i', src, '-t', f'{needed_sec:.3f}', '-vf', vf]
    if keep_audio:
        cmd += ['-c:a', 'aac', '-ar', '44100', '-ac', '2']
    else:
        cmd += ['-an']
    cmd += ['-c:v', 'libx264', '-preset', 'veryfast', '-crf', '20',
            '-pix_fmt', 'yuv420p', dst]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        tail = '\n'.join(r.stderr.splitlines()[-15:])
        raise Exception(f"Preprocess failed for {os.path.basename(src)}:\n{tail}")


def clip_has_audio(path):
    result = subprocess.run(
        [FFPROBE, '-v', 'error', '-select_streams', 'a:0',
         '-show_entries', 'stream=index', '-of', 'csv=p=0', path],
        capture_output=True, text=True)
    return bool(result.stdout.strip())


def source_media_metadata():
    catalog_path = os.path.join(ASSETS_DIR, 'source_media', 'catalog.json')
    if not os.path.exists(catalog_path):
        return {}
    try:
        with open(catalog_path) as f:
            data = json.load(f)
        entries = data.get('media', []) if isinstance(data, dict) else data
        return {entry.get('id'): entry for entry in entries}
    except Exception:
        return {}


def preprocess_intro(video):
    """Returns (rel_src, durationInFrames) or None."""
    if not video.get('use_human_intro'):
        return None
    intro_dir = os.path.join(ASSETS_DIR, 'intros', video['account_id'])
    if not os.path.isdir(intro_dir):
        return None
    intros = sorted(f for f in os.listdir(intro_dir) if f.endswith('.mp4'))
    if not intros:
        return None
    src = os.path.join(intro_dir, random.Random(video['id']).choice(intros))
    dst = os.path.join(ASSETS_DIR, str(video['id']), 'prepped_intro.mp4')
    dur = min(3.0, probe_duration(src))
    preprocess_clip(src, dst, dur, keep_audio=True)
    frames = round(probe_duration(dst) * FPS)
    print(f"Node 4: Intro prepped ({frames} frames): {os.path.basename(src)}")
    return {'src': f"{video['id']}/prepped_intro.mp4", 'durationInFrames': frames}


# ─── Props + Remotion render ─────────────────────────────────────────────────

def build_props(video, clips, scenes, durations, words, mood):
    vid = video['id']
    media_catalog = source_media_metadata()
    scene_props = []
    for i, dur in enumerate(durations):
        hint = scenes[i].get('transition_hint', 'crossfade') if i < len(scenes) else 'crossfade'
        ttype, tframes = TRANSITION_MAP.get(hint, TRANSITION_MAP['crossfade'])
        directives = scenes[i].get('editing_directives', {}) if i < len(scenes) else {}
        media = scenes[i].get('licensed_media') or {} if i < len(scenes) else {}
        media_entry = media_catalog.get(media.get('media_id'), {})
        scene_props.append({
            'clips': [f"{vid}/prepped_scene_{i}_clip_{j}.mp4"
                      for j in range(len(clips[i]))],
            'durationInFrames': round(dur * FPS),
            'sceneIndex': i,
            'pacingStyle': scenes[i].get('pacing_style', 'standard') if i < len(scenes) else 'standard',
            'cameraMovement': directives.get('camera_movement', 'static'),
            'colorGradeHint': directives.get('color_grade_hint', 'high_contrast'),
            'audioEmphasis': directives.get('audio_emphasis', 'voiceonly'),
            'soundEffect': directives.get('sound_effect', 'none'),
            'captionStyle': directives.get('caption_style', 'bottom_center'),
            'chart': scenes[i].get('chart') if i < len(scenes) else None,
            'mediaDisplayMode': media.get('display_mode'),
            'sourceAudio': media.get('playback_mode') == 'source_audio',
            'sourceCredit': media_entry.get('credit_text'),
            'transitionAfter': None if i == len(durations) - 1
                               else {'type': ttype, 'durationInFrames': tframes},
        })

    intro = preprocess_intro(video)
    intro_frames = intro['durationInFrames'] if intro else 0
    total_frames = intro_frames + sum(s['durationInFrames'] for s in scene_props)

    music_src = pick_music(vid, mood)
    compliance_text = "#ad | AI-Assisted" if video.get('is_sponsored') else "AI-Assisted"

    caption_props = []
    scene_ends = []
    cursor = 0
    for scene in scene_props:
        cursor += scene['durationInFrames']
        scene_ends.append(cursor)
    for word in words:
        start_frame = round(word['start'] * FPS)
        scene_index = next((i for i, end in enumerate(scene_ends) if start_frame < end),
                           max(0, len(scene_props) - 1))
        style = scene_props[scene_index]['captionStyle'] if scene_props else 'bottom_center'
        caption_props.append({'word': word['word'],
                              'startFrame': start_frame,
                              'endFrame': round(word['end'] * FPS),
                              'style': style})

    props = {
        'fps': FPS, 'width': WIDTH, 'height': HEIGHT,
        'durationInFrames': total_frames,
        'intro': intro,
        'scenes': scene_props,
        'voiceoverSrc': f"{vid}/voiceover.mp3",
        'captions': caption_props,
        'music': ({'src': music_src, 'volumeDb': -22, 'fadeOutSec': 2}
                  if music_src else None),
        'compliance': {'text': compliance_text,
                       'fullDuration': bool(video.get('is_sponsored'))},
        'accentColor': '#FFD447',
    }

    comp_json = os.path.join(ASSETS_DIR, str(vid), 'comp.json')
    with open(comp_json, 'w') as f:
        json.dump(props, f, indent=2)
    return comp_json, total_frames


def validate_edit_plan(script, durations):
    """Final structural QA before Remotion consumes the storyboard."""
    scenes = script.get('scenes', [])
    if not scenes or not durations or durations[0] > 3.1:
        raise Exception("First-three-second QA failed: opening scene exceeds 3.10s.")
    evidence = (script.get('_research') or {}).get('evidence_ledger', [])
    chart_expected = any(item.get('chart_recommended') and item.get('chart_unit')
                         and 2 <= len(item.get('chart_points') or []) <= 6
                         for item in evidence)
    if chart_expected and not any(scene.get('chart') for scene in scenes):
        raise Exception("Chart QA failed: comparable sourced metrics were not visualized.")


def make_public_symlinks(video_id):
    public = os.path.join(REMOTION_DIR, 'public')
    os.makedirs(public, exist_ok=True)
    links = [
        (os.path.join(ASSETS_DIR, str(video_id)), os.path.join(public, str(video_id))),
        (os.path.join(ASSETS_DIR, 'music'), os.path.join(public, 'music')),
        (os.path.join(ASSETS_DIR, 'sfx'), os.path.join(public, 'sfx')),
    ]
    for target, link in links:
        if os.path.islink(link) or os.path.exists(link):
            if os.path.islink(link):
                os.remove(link)
        if not os.path.exists(link):
            os.symlink(target, link)


def remove_public_symlinks(video_id):
    public = os.path.join(REMOTION_DIR, 'public')
    for name in [str(video_id), 'music', 'sfx']:
        link = os.path.join(public, name)
        if os.path.islink(link):
            os.remove(link)


def render_remotion(comp_json, out_path, composition='ShortVideo'):
    cmd = ['npx', 'remotion', 'render', 'src/index.ts', composition, out_path,
           '--props', comp_json, '--concurrency', '2']
    r = subprocess.run(cmd, cwd=REMOTION_DIR, capture_output=True, text=True,
                       timeout=1800)
    if r.returncode != 0:
        tail = '\n'.join((r.stderr or r.stdout).splitlines()[-25:])
        raise Exception(f"Remotion render failed:\n{tail}")


# ─── FFmpeg fallback renderer (duration-correct, no fancy captions) ──────────

def render_ffmpeg_fallback(clips, durations, voiceover, out_path):
    filter_parts = []
    for i, dur in enumerate(durations):
        filter_parts.append(
            f"[{i}:v]{BASE_VF},trim=duration={dur:.3f},setpts=PTS-STARTPTS[v{i}]; ")
    n = len(clips)
    concat_in = ''.join(f'[v{i}]' for i in range(n))
    graph = ''.join(filter_parts) + f"{concat_in}concat=n={n}:v=1:a=0[outv]"

    cmd = [FFMPEG, '-y']
    for p in clips:
        cmd += ['-stream_loop', '-1', '-i', p]
    cmd += ['-i', voiceover,
            '-filter_complex', graph,
            '-map', '[outv]', '-map', f'{n}:a',
            '-c:v', 'libx264', '-preset', 'fast', '-crf', '23',
            '-c:a', 'aac', '-shortest', out_path]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        tail = '\n'.join(r.stderr.splitlines()[-25:])
        raise Exception(f"FFmpeg fallback failed:\n{tail}")


# ─── Metadata stamp (stream copy, no re-encode) ──────────────────────────────

def stamp_metadata(video, rendered_path, final_path):
    cmd = [FFMPEG, '-y', '-i', rendered_path,
           '-metadata', f"comment=AI-Assisted | {SCRIPT_MODEL}",
           '-metadata', f"copyright=© {video['account_id']}",
           '-c', 'copy', final_path]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        shutil.move(rendered_path, final_path)  # metadata is nice-to-have
    elif os.path.exists(rendered_path):
        os.remove(rendered_path)


# ─── Main render ─────────────────────────────────────────────────────────────

def render_video(video):
    vid = video['id']
    vid_dir = os.path.join(ASSETS_DIR, str(vid))
    os.makedirs(vid_dir, exist_ok=True)

    voiceover = resolve_voiceover(video)
    audio_dur = probe_duration(voiceover)

    clip_groups = find_scene_clips(video)
    if not clip_groups:
        raise Exception("No scene clips found on disk. Re-run asset fetch (Pending_Assets).")

    try:
        script = json.loads(video['script'])
    except Exception:
        script = {}
    scenes = script.get('scenes', [])
    mood = script.get('music_mood', 'neutral') or 'neutral'

    durations = load_scene_durations(video, len(clip_groups), scenes, audio_dur)
    validate_edit_plan(script, durations)
    words = load_captions_words(video)
    clip_count = sum(len(group) for group in clip_groups)
    print(f"Node 4: video {vid}: {len(clip_groups)} scenes/{clip_count} clips, audio {audio_dur:.1f}s, "
          f"scene durations {[f'{d:.1f}' for d in durations]}, {len(words)} caption words")

    final_path = os.path.join(vid_dir, 'final.mp4')
    rendered = os.path.join(vid_dir, 'rendered.mp4')

    try:
        # Preprocess scene clips for Remotion
        for i, (scene_clips, dur) in enumerate(zip(clip_groups, durations)):
            hint = scenes[i].get('transition_hint', 'crossfade') if i < len(scenes) else 'crossfade'
            _, tframes = TRANSITION_MAP.get(hint, TRANSITION_MAP['crossfade'])
            media = scenes[i].get('licensed_media') or {} if i < len(scenes) else {}
            source_audio = media.get('playback_mode') == 'source_audio'
            needed = (dur + tframes / FPS + 0.2 if source_audio
                      else dur / len(scene_clips) + tframes / FPS + 0.5)
            for j, clip in enumerate(scene_clips):
                dst = os.path.join(vid_dir, f'prepped_scene_{i}_clip_{j}.mp4')
                keep_audio = source_audio and clip_has_audio(clip)
                preprocess_clip(clip, dst, needed, keep_audio=keep_audio)

        comp_json, total_frames = build_props(video, clip_groups, scenes, durations, words, mood)
        ensure_sfx_assets()
        make_public_symlinks(vid)
        print(f"Node 4: Rendering {total_frames} frames via Remotion...")
        render_remotion(comp_json, rendered)
    except Exception as e:
        rich_edit = any(
            scene.get('chart')
            or (scene.get('licensed_media') or {}).get('playback_mode') == 'source_audio'
            for scene in scenes
        )
        if rich_edit:
            raise Exception(f"Remotion required for chart/source-audio scene: {e}")
        print(f"Node 4: Remotion path failed ({e})\nNode 4: Falling back to plain FFmpeg render.")
        render_ffmpeg_fallback([group[0] for group in clip_groups], durations, voiceover, rendered)
    finally:
        remove_public_symlinks(vid)

    stamp_metadata(video, rendered, final_path)

    out_dur = probe_duration(final_path)
    if out_dur < audio_dur - 2.0:
        raise Exception(
            f"Render sanity check failed: output {out_dur:.1f}s < voiceover {audio_dur:.1f}s.")
    print(f"Node 4: Final video {out_dur:.1f}s → {final_path}")

    # Cleanup intermediates
    for p in glob.glob(os.path.join(vid_dir, 'prepped_*.mp4')):
        os.remove(p)

    return final_path


# ─── Long-form render (Phase 6): beats.json → LongVideo composition ─────────

MOOD_KEYWORDS = {
    'tense': ('tense', 'tension', 'dark', 'urgent', 'dramatic', 'ominous'),
    'uplifting': ('uplift', 'hope', 'bright', 'triumph', 'optimis', 'inspir'),
    'mysterious': ('myster', 'eerie', 'curious', 'wonder', 'suspense', 'intrigu'),
}


def music_mood_from_beats(beats):
    """Map free-text music_cue lines onto the four music mood folders."""
    votes = []
    for beat in beats:
        cue = str(beat.get('music_cue') or '').lower()
        votes.append(next((mood for mood, keys in MOOD_KEYWORDS.items()
                           if any(k in cue for k in keys)), 'neutral'))
    non_neutral = [v for v in votes if v != 'neutral']
    return max(set(non_neutral), key=non_neutral.count) if non_neutral else 'neutral'


def beat_windows(beats):
    """Continuous [from, until) seconds per beat — mirrors LongVideo.tsx."""
    if not all(isinstance(b.get('start'), (int, float))
               and isinstance(b.get('end'), (int, float)) for b in beats):
        raise Exception("beats.json is missing narration timing (start/end). Re-run Node 2b.")
    last_until = float(beats[-1]['end']) + 0.4
    windows = []
    for i, beat in enumerate(beats):
        start = 0.0 if i == 0 else float(beat['start'])
        until = float(beats[i + 1]['start']) if i + 1 < len(beats) else last_until
        windows.append((start, max(start + 0.5, until)))
    return windows


def preprocess_long_brolls(vid_dir, beats, windows):
    """Normalize every realized broll clip to 1920×1080@FPS covering its window."""
    for i, (beat, (w_from, w_until)) in enumerate(zip(beats, windows)):
        for j, el in enumerate(beat.get('elements', [])):
            src = el.get('src')
            if not src or not str(src).endswith('.mp4'):
                continue
            window = (w_until - w_from) - float(el.get('start_offset_sec') or 0)
            needed = float(el.get('duration_sec') or window) + 0.5
            abs_src = os.path.join(vid_dir, src)
            if not os.path.exists(abs_src):
                raise Exception(f"Missing broll clip {src} for beat {beat.get('order')}.")
            name = f'prepped_long_{i}_{j}.mp4'
            preprocess_clip(abs_src, os.path.join(vid_dir, name),
                            max(1.0, needed), vf=LONG_VF)
            el['src'] = name


def build_long_props(video, beats_data, words):
    vid = video['id']
    music_src = pick_music(vid, music_mood_from_beats(beats_data['beats']))
    props = {
        'fps': FPS, 'width': LONG_WIDTH, 'height': LONG_HEIGHT,
        'assetBase': str(vid),
        'beats': beats_data['beats'],
        'voiceoverSrc': f"{vid}/voiceover.mp3",
        'captions': [{'word': w['word'], 'start': w['start'], 'end': w['end']}
                     for w in words],
        'music': ({'src': music_src, 'volumeDb': -24, 'fadeOutSec': 2}
                  if music_src else None),
        'accentColor': '#FFD447',
    }
    comp_json = os.path.join(ASSETS_DIR, str(vid), 'comp_long.json')
    with open(comp_json, 'w') as f:
        json.dump(props, f, indent=2)
    return comp_json


def render_long_video(video):
    """Phase 6: render beats.json through LongVideo. Remotion required — no ffmpeg fallback."""
    vid = video['id']
    vid_dir = os.path.join(ASSETS_DIR, str(vid))
    beats_path = os.path.join(vid_dir, 'beats.json')
    if not os.path.exists(beats_path):
        raise Exception("beats.json not found — re-run storyboard (Pending_Storyboard).")
    with open(beats_path) as f:
        beats_data = json.load(f)
    beats = beats_data.get('beats') or []
    if not beats:
        raise Exception("beats.json contains no beats.")

    voiceover = resolve_voiceover(video)
    audio_dur = probe_duration(voiceover)
    words = load_captions_words(video)
    windows = beat_windows(beats)
    expected_dur = windows[-1][1]
    print(f"Node 4: long video {vid}: {len(beats)} beats, audio {audio_dur:.1f}s, "
          f"{len(words)} caption words")

    preprocess_long_brolls(vid_dir, beats, windows)
    comp_json = build_long_props(video, beats_data, words)
    rendered = os.path.join(vid_dir, 'rendered_long.mp4')
    final_path = os.path.join(vid_dir, 'final.mp4')
    make_public_symlinks(vid)
    try:
        print(f"Node 4: Rendering LongVideo ({expected_dur:.1f}s) via Remotion...")
        render_remotion(comp_json, rendered, composition='LongVideo')
    finally:
        remove_public_symlinks(vid)
    stamp_metadata(video, rendered, final_path)

    out_dur = probe_duration(final_path)
    if abs(out_dur - expected_dur) > 1.0:
        raise Exception(f"Long render sanity check failed: output {out_dur:.1f}s "
                        f"vs expected {expected_dur:.1f}s (narration {audio_dur:.1f}s).")
    for p in glob.glob(os.path.join(vid_dir, 'prepped_long_*.mp4')):
        os.remove(p)
    print(f"Node 4: Long-form final {out_dur:.1f}s → {final_path}")
    return final_path


# ─── Worker loop ─────────────────────────────────────────────────────────────

def _merged_compliance(video):
    """Phase 7: keep the owner's disclosure checklist across re-renders."""
    try:
        meta = json.loads(video.get('compliance_metadata') or '{}')
        if not isinstance(meta, dict):
            meta = {}
    except (json.JSONDecodeError, TypeError):
        meta = {}
    meta.update(ai_disclosure='AI-Assisted', model=SCRIPT_MODEL,
                sponsored=bool(video.get('is_sponsored')))
    return json.dumps(meta)


def run():
    print("Node 4: Render worker started.")
    videos = database.fetch_videos_by_status('Pending_Render')

    for video in videos:
        print(f"Node 4: Rendering video {video['id']} — '{video['topic']}'")
        try:
            final_path = render_video(video)
            next_status = 'Ready_To_Publish' if video.get('auto_approve') else 'QA_Final'
            database.update_video(video['id'], {
                'final_path': final_path,   # video_path (scene list) is preserved
                'status': next_status,
                'compliance_metadata': json.dumps({
                    'ai_disclosure': 'AI-Assisted',
                    'model': SCRIPT_MODEL,
                    'sponsored': bool(video.get('is_sponsored')),
                }),
                'error_message': None,
            })
            database.resolve_pipeline_errors(video['id'], 'Node 4')
            print(f"Node 4: Video {video['id']} → {next_status}. Output: {final_path}")

        except Exception as e:
            msg = str(e)
            print(f"Node 4: FAILED video {video['id']}: {msg}")
            database.fail_video(video['id'], 'Node 4', 'RENDER_FAILED', msg)

    for video in database.fetch_videos_by_status('Pending_LongRender'):
        if video.get('format') != 'long':
            continue
        print(f"Node 4: Long-form render for video {video['id']} — '{video['topic']}'")
        try:
            final_path = render_long_video(video)
            database.update_video(video['id'], {
                'final_path': final_path,
                'status': 'QA_Final',
                'compliance_metadata': _merged_compliance(video),
                'error_message': None,
            })
            database.resolve_pipeline_errors(video['id'], 'Node 4')
            print(f"Node 4: Video {video['id']} → QA_Final. Output: {final_path}")
        except Exception as e:
            print(f"Node 4: FAILED long video {video['id']}: {e}")
            database.fail_video(video['id'], 'Node 4', 'LONG_RENDER_FAILED', str(e))


if __name__ == "__main__":
    while True:
        run()
        time.sleep(10)