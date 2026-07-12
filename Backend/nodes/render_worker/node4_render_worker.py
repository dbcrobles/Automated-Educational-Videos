import os
import sys
import re
import json
import time
import random
import subprocess

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from database import database


# ─── SRT Parser ───────────────────────────────────────────────────────────────

def srt_timestamp_to_seconds(ts: str) -> float:
    ts = ts.strip().replace(',', '.')
    h, m, s = ts.split(':')
    return int(h) * 3600 + int(m) * 60 + float(s)


def parse_srt(srt_path: str) -> list:
    with open(srt_path, 'r', encoding='utf-8') as f:
        content = f.read()
    captions = []
    blocks = [b.strip() for b in re.split(r'\n\s*\n', content) if b.strip()]
    for block in blocks:
        lines = [l.strip() for l in block.splitlines() if l.strip()]
        ts_idx = next((i for i, l in enumerate(lines) if '-->' in l), None)
        if ts_idx is None:
            continue
        parts = lines[ts_idx].split('-->')
        if len(parts) != 2:
            continue
        try:
            start = srt_timestamp_to_seconds(parts[0])
            end   = srt_timestamp_to_seconds(parts[1])
        except Exception:
            continue
        text = ' '.join(lines[ts_idx + 1:]).strip()
        if text:
            captions.append({'text': text, 'start': start, 'end': end})
    return captions


# ─── Caption rendering (Pillow → VP9 WebM alpha overlay) ─────────────────────
#
# Background: Homebrew FFmpeg 8.1.2 is built WITHOUT libfreetype or libass,
# so neither 'drawtext' nor 'subtitles'/'ass' filters are available.
# Instead we:
#   1. Use Pillow to render caption text onto transparent RGBA PNGs
#   2. Create a timed caption track via FFmpeg concat demuxer
#   3. Encode it to VP9 WebM with alpha (libvpx-vp9 IS built into this FFmpeg)
#   4. Composite with the main video using the 'overlay' filter

def _find_font(size: int = 55):
    """Return an ImageFont, falling back to the PIL default if no TTF is found."""
    from PIL import ImageFont
    candidates = [
        '/System/Library/Fonts/Supplemental/Arial Bold.ttf',
        '/System/Library/Fonts/Supplemental/Arial.ttf',
        '/Library/Fonts/Arial Bold.ttf',
        '/Library/Fonts/Arial.ttf',
        '/System/Library/Fonts/Helvetica.ttc',
        '/System/Library/Fonts/Geneva.ttf',
    ]
    for path in candidates:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    # Fall back to Pillow's built-in bitmap font (smaller but always works)
    return ImageFont.load_default()


def _make_caption_png(text: str, path: str, width: int = 1080, height: int = 1920,
                       font=None) -> str:
    """Create a full-frame RGBA PNG with white text + black outline, transparent background."""
    from PIL import Image, ImageDraw

    img  = Image.new('RGBA', (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    try:
        bbox = draw.textbbox((0, 0), text, font=font)
        tw   = bbox[2] - bbox[0]
        th   = bbox[3] - bbox[1]
    except AttributeError:
        # Pillow < 9 fallback
        tw, th = draw.textsize(text, font=font)

    x = (width - tw) // 2
    y = height - 290 - th // 2

    # Black outline (3 px in every direction)
    for ox in range(-3, 4):
        for oy in range(-3, 4):
            if ox or oy:
                draw.text((x + ox, y + oy), text, font=font, fill=(0, 0, 0, 255))

    # White text fill
    draw.text((x, y), text, font=font, fill=(240, 240, 240, 255))
    img.save(path)
    return path


def add_captions(captions: list, main_video_path: str, output_path: str,
                 assets_dir: str, video_id: str | int) -> str:
    """
    Composite timed caption text onto main_video_path → output_path.

    Returns output_path on success, or main_video_path if caption rendering fails
    (so the pipeline still produces a usable video).
    """
    from PIL import Image

    # ── Probe video dimensions ───────────────────────────────────────────────
    probe = subprocess.run(
        ['/opt/homebrew/bin/ffprobe', '-v', 'error',
         '-select_streams', 'v:0',
         '-show_entries', 'stream=width,height',
         '-show_entries', 'format=duration',
         '-of', 'json', main_video_path],
        capture_output=True, text=True
    )
    info   = json.loads(probe.stdout)
    width  = info['streams'][0]['width']
    height = info['streams'][0]['height']
    total_dur = float(info['format']['duration'])

    font = _find_font(55)

    # ── Create PIL images for each unique caption text ───────────────────────
    blank_path = os.path.join(assets_dir, f'cap_{video_id}_blank.png')
    Image.new('RGBA', (width, height), (0, 0, 0, 0)).save(blank_path)

    cap_images: dict[str, str] = {}
    for i, cap in enumerate(captions):
        t = cap['text']
        if t not in cap_images:
            p = os.path.join(assets_dir, f'cap_{video_id}_{i}.png')
            _make_caption_png(t, p, width, height, font)
            cap_images[t] = p

    # ── Build ffconcat manifest ───────────────────────────────────────────────
    manifest_path = os.path.join(assets_dir, f'cap_manifest_{video_id}.txt')
    overlay_webm  = os.path.join(assets_dir, f'cap_overlay_{video_id}.webm')

    lines   = ['ffconcat version 1.0']
    current = 0.0

    for cap in sorted(captions, key=lambda c: c['start']):
        gap = cap['start'] - current
        if gap > 0.02:
            lines += [f"file '{blank_path}'", f"duration {gap:.4f}"]
        dur = max(0.05, cap['end'] - cap['start'])
        lines += [f"file '{cap_images[cap['text']]}'", f"duration {dur:.4f}"]
        current = cap['end']

    if current < total_dur - 0.02:
        lines += [f"file '{blank_path}'", f"duration {total_dur - current:.4f}"]
    lines.append(f"file '{blank_path}'")  # ffconcat: last file must repeat

    with open(manifest_path, 'w') as f:
        f.write('\n'.join(lines))

    # ── Composite main video + caption overlay directly ───────────────────────
    composite_cmd = [
        '/opt/homebrew/bin/ffmpeg', '-y',
        '-i', main_video_path,
        '-f', 'concat', '-safe', '0',
        '-i', manifest_path,
        '-filter_complex', '[0:v][1:v]overlay=shortest=1[outv]',
        '-map', '[outv]',
        '-map', '0:a',
        '-c:v', 'libx264', '-preset', 'fast', '-crf', '23',
        '-c:a', 'copy',
        output_path
    ]
    r = subprocess.run(composite_cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"Node 4: Caption composite failed:\n{''.join(r.stderr.splitlines()[-20:])}")
        return main_video_path  # graceful fallback

    print(f"Node 4: Captions composited successfully → {output_path}")
    return output_path


# ─── Main render function ─────────────────────────────────────────────────────

def render_video(video_record):
    voiceover_audio = video_record.get('voiceover_path')
    if not voiceover_audio or not os.path.exists(voiceover_audio):
        raise Exception("Voiceover audio missing. Cannot render.")

    assets_dir  = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'assets')
    raw_path    = os.path.join(assets_dir, f"raw_{video_record['id']}.mp4")
    output_path = os.path.join(assets_dir, f"final_{video_record['id']}.mp4")
    srt_path    = os.path.join(assets_dir, f"captions_{video_record['id']}.srt")

    # ── Load clip paths ──────────────────────────────────────────────────────
    try:
        downloaded_paths = json.loads(video_record['video_path'])
    except Exception:
        downloaded_paths = [video_record['video_path']]

    downloaded_paths = [p for p in downloaded_paths if os.path.exists(p)]
    if not downloaded_paths:
        raise Exception("All video assets are missing from disk.")

    num_clips = len(downloaded_paths)

    try:
        scenes = json.loads(video_record['script']).get('scenes', [])
    except Exception:
        scenes = []

    # ── Build per-clip scale/zoom filter parts ────────────────────────────────
    filter_parts = []

    for i in range(num_clips):
        pacing = scenes[i].get('pacing_style', 'standard') if i < len(scenes) else 'standard'

        # Base chain: scale to fill 9:16, crop to exact 1080x1920, normalise
        # NOTE: zoompan is an IMAGE filter (reads only frame 0) — never use it on
        #       video clips. For a subtle Ken-Burns effect on real footage, we
        #       over-scale slightly and animate the crop position instead.

        if pacing == "rapid":
            duration    = 2
            full_filter = "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1,fps=30"

        elif pacing == "standard":
            duration = 4
            # Slight 5 % over-scale → animate crop to simulate gentle zoom
            if i % 2 == 0:
                # Slow zoom-in: crop window shrinks towards centre over time
                full_filter = (
                    "scale=1134:2016:force_original_aspect_ratio=increase,"
                    "crop=1080:1920:(iw-1080)/2*(1-t/4):(ih-1920)/2*(1-t/4),"
                    "setsar=1,fps=30"
                )
            else:
                # Slow zoom-out: crop window expands from centre over time
                full_filter = (
                    "scale=1134:2016:force_original_aspect_ratio=increase,"
                    "crop=1080:1920:(iw-1080)/2*(t/4):(ih-1920)/2*(t/4),"
                    "setsar=1,fps=30"
                )

        elif pacing == "slow_pan":
            duration = 8
            full_filter = (
                "scale=1134:2016:force_original_aspect_ratio=increase,"
                "crop=1080:1920:(iw-1080)/2*(1-t/8):(ih-1920)/2*(1-t/8),"
                "setsar=1,fps=30"
            )

        else:
            duration    = 4
            full_filter = "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1,fps=30"

        filter_parts.append(
            f"[{i}:v]{full_filter},trim=duration={duration},setpts=PTS-STARTPTS[v{i}]; "
        )

    concat_inputs = "".join(f"[v{i}]" for i in range(num_clips))
    full_filter   = "".join(filter_parts) + f"{concat_inputs}concat=n={num_clips}:v=1:a=0[outv]"

    # ── Pass 1: Render base video (no captions yet) ───────────────────────────
    cmd = ["/opt/homebrew/bin/ffmpeg", "-y"]
    for p in downloaded_paths:
        cmd.extend(["-stream_loop", "-1", "-i", p])
    cmd.extend(["-i", voiceover_audio])
    cmd.extend([
        "-filter_complex", full_filter,
        "-map", "[outv]",
        "-map", f"{num_clips}:a",
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-c:a", "aac",
        "-shortest",
        raw_path
    ])

    print(f"Node 4: FFmpeg Pass 1 — {num_clips} clips, video {video_record['id']}...")
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        tail = '\n'.join(r.stderr.splitlines()[-40:])
        raise Exception(f"FFmpeg error:\n{tail}")

    current_path = raw_path

    # ── Pass 2: Composite captions (Pillow → VP9 overlay) ────────────────────
    if os.path.exists(srt_path):
        try:
            captions = parse_srt(srt_path)
            if captions:
                print(f"Node 4: Adding {len(captions)} caption segments via Pillow overlay...")
                captioned_path = os.path.join(assets_dir, f"captioned_{video_record['id']}.mp4")
                current_path = add_captions(
                    captions, current_path, captioned_path,
                    assets_dir, video_record['id']
                )
            else:
                print("Node 4: SRT is empty — no captions to add.")
        except Exception as e:
            print(f"Node 4: Caption pass failed ({e}) — continuing with uncaptioned video.")

    # ── Pass 3 (optional): Splice human hook intro ───────────────────────────
    if video_record.get('use_human_intro'):
        intro_dir = os.path.join(assets_dir, 'intros', video_record['account_id'])
        if os.path.exists(intro_dir):
            intros = [f for f in os.listdir(intro_dir) if f.endswith('.mp4')]
            if intros:
                intro_file  = os.path.join(intro_dir, random.choice(intros))
                spliced_out = os.path.join(assets_dir, f"spliced_{video_record['id']}.mp4")
                print(f"Node 4: Splicing intro: {intro_file}")

                splice_cmd = [
                    "/opt/homebrew/bin/ffmpeg", "-y",
                    "-i", intro_file,
                    "-i", current_path,
                    "-filter_complex",
                    "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,"
                    "crop=1080:1920,setsar=1,fps=30[v0];"
                    "[0:a]aformat=sample_rates=44100:channel_layouts=stereo[a0];"
                    "[1:v]scale=1080:1920:force_original_aspect_ratio=increase,"
                    "crop=1080:1920,setsar=1,fps=30[v1];"
                    "[1:a]aformat=sample_rates=44100:channel_layouts=stereo[a1];"
                    "[v0][a0][v1][a1]concat=n=2:v=1:a=1[outv][outa]",
                    "-map", "[outv]", "-map", "[outa]",
                    "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                    "-c:a", "aac",
                    spliced_out
                ]
                r2 = subprocess.run(splice_cmd, capture_output=True, text=True)
                if r2.returncode == 0:
                    current_path = spliced_out
                else:
                    print(f"Node 4: Intro splice failed — using AI-only video.")

    # Rename current_path to the canonical output_path
    if current_path != output_path:
        import shutil
        shutil.move(current_path, output_path)

    return output_path


# ─── Worker loop ─────────────────────────────────────────────────────────────

def run():
    print("Node 4: Render worker started.")
    videos = database.fetch_videos_by_status('Pending_Render')

    for video in videos:
        print(f"Node 4: Rendering video {video['id']} — '{video['topic']}'")
        try:
            output_path = render_video(video)
            database.update_video(video['id'], {
                'video_path':    output_path,
                'status':        'Ready_To_Publish',
                'error_message': None
            })
            print(f"Node 4: Video {video['id']} → Ready_To_Publish. Output: {output_path}")

        except Exception as e:
            msg = str(e)
            print(f"Node 4: FAILED video {video['id']}: {msg}")
            database.update_video(video['id'], {
                'status':        'Failed',
                'error_message': f"Node 4 (Render) Error: {msg}"
            })


if __name__ == "__main__":
    while True:
        run()
        time.sleep(10)
