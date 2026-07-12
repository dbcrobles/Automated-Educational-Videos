import os
import sys
import re
import json
import time
import glob
import random
import shutil
import subprocess

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

GEMINI_MODEL_STRUCTURED = "gemini-2.5-flash"

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

def _scene_index(path):
    m = re.search(r'scene_(\d+)\.mp4$', path)
    return int(m.group(1)) if m else 0


def find_scene_clips(video):
    """Locate the per-scene source clips. Canonical: assets/{id}/scene_N.mp4."""
    vid = video['id']
    clips = sorted(
        glob.glob(os.path.join(ASSETS_DIR, str(vid), 'scene_*.mp4')),
        key=_scene_index)
    if clips:
        return clips

    # Fallback 1: DB video_path holds a JSON array (pre-fix behaviour)
    try:
        paths = json.loads(video.get('video_path') or '')
        if isinstance(paths, list):
            paths = [p for p in paths if os.path.exists(p)]
            if paths:
                return paths
    except Exception:
        pass

    # Fallback 2: legacy flat layout video_{id}_scene_N.mp4
    clips = sorted(
        glob.glob(os.path.join(ASSETS_DIR, f'video_{vid}_scene_*.mp4')),
        key=_scene_index)
    return clips


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


# ─── Preprocessing (FFmpeg normalisation for Remotion) ───────────────────────

BASE_VF = (f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,"
           f"crop={WIDTH}:{HEIGHT},setsar=1,fps={FPS}")


def preprocess_clip(src, dst, needed_sec, keep_audio=False):
    src_dur = probe_duration(src)
    cmd = [FFMPEG, '-y']
    if src_dur < needed_sec:
        cmd += ['-stream_loop', '-1']
    cmd += ['-i', src, '-t', f'{needed_sec:.3f}', '-vf', BASE_VF]
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
    dur = probe_duration(src)
    preprocess_clip(src, dst, dur + 0.1, keep_audio=True)
    frames = round(probe_duration(dst) * FPS)
    print(f"Node 4: Intro prepped ({frames} frames): {os.path.basename(src)}")
    return {'src': f"{video['id']}/prepped_intro.mp4", 'durationInFrames': frames}


# ─── Props + Remotion render ─────────────────────────────────────────────────

def build_props(video, clips, scenes, durations, words, mood):
    vid = video['id']
    scene_props = []
    for i, dur in enumerate(durations):
        hint = scenes[i].get('transition_hint', 'crossfade') if i < len(scenes) else 'crossfade'
        ttype, tframes = TRANSITION_MAP.get(hint, TRANSITION_MAP['crossfade'])
        scene_props.append({
            'src': f"{vid}/prepped_scene_{i}.mp4",
            'durationInFrames': round(dur * FPS),
            'sceneIndex': i,
            'pacingStyle': scenes[i].get('pacing_style', 'standard') if i < len(scenes) else 'standard',
            'transitionAfter': None if i == len(durations) - 1
                               else {'type': ttype, 'durationInFrames': tframes},
        })

    intro = preprocess_intro(video)
    intro_frames = intro['durationInFrames'] if intro else 0
    total_frames = intro_frames + sum(s['durationInFrames'] for s in scene_props)

    music_src = pick_music(vid, mood)
    compliance_text = "#ad | AI-Assisted" if video.get('is_sponsored') else "AI-Assisted"

    props = {
        'fps': FPS, 'width': WIDTH, 'height': HEIGHT,
        'durationInFrames': total_frames,
        'intro': intro,
        'scenes': scene_props,
        'voiceoverSrc': f"{vid}/voiceover.mp3",
        'captions': [{'word': w['word'],
                      'startFrame': round(w['start'] * FPS),
                      'endFrame': round(w['end'] * FPS)} for w in words],
        'music': ({'src': music_src, 'volumeDb': -18, 'fadeOutSec': 2}
                  if music_src else None),
        'compliance': {'text': compliance_text,
                       'fullDuration': bool(video.get('is_sponsored'))},
        'accentColor': '#FFD447',
    }

    comp_json = os.path.join(ASSETS_DIR, str(vid), 'comp.json')
    with open(comp_json, 'w') as f:
        json.dump(props, f, indent=2)
    return comp_json, total_frames


def make_public_symlinks(video_id):
    public = os.path.join(REMOTION_DIR, 'public')
    os.makedirs(public, exist_ok=True)
    links = [
        (os.path.join(ASSETS_DIR, str(video_id)), os.path.join(public, str(video_id))),
        (os.path.join(ASSETS_DIR, 'music'), os.path.join(public, 'music')),
    ]
    for target, link in links:
        if os.path.islink(link) or os.path.exists(link):
            if os.path.islink(link):
                os.remove(link)
        if not os.path.exists(link):
            os.symlink(target, link)


def remove_public_symlinks(video_id):
    public = os.path.join(REMOTION_DIR, 'public')
    for name in [str(video_id), 'music']:
        link = os.path.join(public, name)
        if os.path.islink(link):
            os.remove(link)


def render_remotion(comp_json, out_path):
    cmd = ['npx', 'remotion', 'render', 'src/index.ts', 'ShortVideo', out_path,
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
           '-metadata', f"comment=AI-Assisted | {GEMINI_MODEL_STRUCTURED}",
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

    clips = find_scene_clips(video)
    if not clips:
        raise Exception("No scene clips found on disk. Re-run asset fetch (Pending_Assets).")

    try:
        script = json.loads(video['script'])
    except Exception:
        script = {}
    scenes = script.get('scenes', [])
    mood = script.get('music_mood', 'neutral') or 'neutral'

    durations = load_scene_durations(video, len(clips), scenes, audio_dur)
    words = load_captions_words(video)
    print(f"Node 4: video {vid}: {len(clips)} clips, audio {audio_dur:.1f}s, "
          f"scene durations {[f'{d:.1f}' for d in durations]}, {len(words)} caption words")

    final_path = os.path.join(vid_dir, 'final.mp4')
    rendered = os.path.join(vid_dir, 'rendered.mp4')

    try:
        # Preprocess scene clips for Remotion
        for i, (clip, dur) in enumerate(zip(clips, durations)):
            hint = scenes[i].get('transition_hint', 'crossfade') if i < len(scenes) else 'crossfade'
            _, tframes = TRANSITION_MAP.get(hint, TRANSITION_MAP['crossfade'])
            needed = dur + tframes / FPS + 0.2
            preprocess_clip(clip, os.path.join(vid_dir, f'prepped_scene_{i}.mp4'), needed)

        comp_json, total_frames = build_props(video, clips, scenes, durations, words, mood)
        make_public_symlinks(vid)
        print(f"Node 4: Rendering {total_frames} frames via Remotion...")
        render_remotion(comp_json, rendered)
    except Exception as e:
        print(f"Node 4: Remotion path failed ({e})\nNode 4: Falling back to plain FFmpeg render.")
        render_ffmpeg_fallback(clips, durations, voiceover, rendered)
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


# ─── Worker loop ─────────────────────────────────────────────────────────────

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
                    'model': GEMINI_MODEL_STRUCTURED,
                    'sponsored': bool(video.get('is_sponsored')),
                }),
                'error_message': None,
            })
            print(f"Node 4: Video {video['id']} → {next_status}. Output: {final_path}")

        except Exception as e:
            msg = str(e)
            print(f"Node 4: FAILED video {video['id']}: {msg}")
            database.update_video(video['id'], {
                'status': 'Failed',
                'error_message': f"Node 4 (Render) Error: {msg}",
            })


if __name__ == "__main__":
    while True:
        run()
        time.sleep(10)