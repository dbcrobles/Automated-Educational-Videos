import os
import sys
import json
import time
import hashlib
import requests
import re
import subprocess

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from database import database

PEXELS_API_KEY = os.environ.get('PEXELS_API_KEY')
PIXABAY_API_KEY = os.environ.get('PIXABAY_API_KEY')

COST_VEO_GENERATION = 0.40
ASSETS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'assets')

def clean_query(query):
    q = re.sub(r'[\[\]]', '', query)
    q = re.sub(r'^(Pexels:|Pixabay:)\s*', '', q, flags=re.IGNORECASE)
    return q.strip()

def cache_path(query):
    h = hashlib.sha1(query.lower().strip().encode()).hexdigest()[:16]
    cache_dir = os.path.join(ASSETS_DIR, 'cache')
    os.makedirs(cache_dir, exist_ok=True)
    return os.path.join(cache_dir, f'{h}.mp4')

def fetch_from_pexels(keyword, min_duration=0):
    """Return ranked list of (source_id, url) tuples from Pexels."""
    if not PEXELS_API_KEY:
        raise Exception("PEXELS_API_KEY not set")

    url = f"https://api.pexels.com/videos/search?query={keyword}&orientation=portrait&per_page=5"
    headers = {"Authorization": PEXELS_API_KEY}
    response = requests.get(url, headers=headers, timeout=15)
    response.raise_for_status()
    data = response.json()

    candidates = []
    for video in data.get('videos', []):
        sid = str(video['id'])
        dur = video.get('duration', 0)
        if dur < min_duration:
            continue
        files = [f for f in video['video_files'] if f['width'] <= 1080 and f['height'] <= 1920]
        if not files:
            files = video['video_files']
        files = sorted(files, key=lambda x: (x['height'] > x['width'], x['width'] * x['height']), reverse=True)
        if files:
            candidates.append((sid, files[0]['link']))

    if not candidates:
        raise Exception("No videos found on Pexels")
    return candidates

def fetch_from_pixabay(keyword, min_duration=0):
    """Return ranked list of (source_id, url) tuples from Pixabay."""
    if not PIXABAY_API_KEY:
        raise Exception("PIXABAY_API_KEY not set")

    url = f"https://pixabay.com/api/videos/?key={PIXABAY_API_KEY}&q={keyword}&video_type=film&per_page=10"
    response = requests.get(url, timeout=15)
    response.raise_for_status()
    data = response.json()

    candidates = []
    for hit in data.get('hits', []):
        sid = str(hit['id'])
        dur = hit.get('duration', 0)
        if dur < min_duration:
            continue
        videos = hit.get('videos', {})
        large = videos.get('large', {})
        medium = videos.get('medium', {})
        small = videos.get('small', {})
        for v in [large, medium, small]:
            if v and v.get('url'):
                is_portrait = v.get('height', 0) > v.get('width', 0)
                if is_portrait or not candidates:
                    candidates.append((sid, v['url']))
                    break

    if not candidates:
        raise Exception("No videos found on Pixabay")
    return candidates

def generate_veo_video(prompt, destination_path):
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise Exception("GEMINI_API_KEY not set. Required for Veo 3.1 fallback.")

    print(f"Calling Veo 3.1 API for prompt: '{prompt}'...")
    from google import genai
    from google.genai import types
    client = genai.Client(api_key=api_key)

    try:
        response = client.models.generate_videos(
            model='veo-3.1-generate-preview',
            prompt=prompt,
            config=types.GenerateVideoConfig(
                aspect_ratio="9:16",
                duration_seconds=5
            )
        )
        if not response.generated_videos:
            raise Exception("Veo API returned empty video list.")

        with open(destination_path, 'wb') as f:
            f.write(response.generated_videos[0].video.video_bytes)
    except AttributeError:
        print("Veo API SDK method not found. Ensure latest google-genai package is installed.")
        raise Exception("Veo 3.1 SDK Error")

def validate_clip(path, keyword):
    """Return True if the downloaded clip looks like real video."""
    if os.path.getsize(path) < 50_000:
        print(f"Node 3: Clip for '{keyword}' is suspiciously small ({os.path.getsize(path)} bytes) — rejecting.")
        return False

    probe = subprocess.run(
        ['/opt/homebrew/bin/ffprobe', '-v', 'error',
         '-select_streams', 'v:0',
         '-show_entries', 'stream=nb_read_frames,duration',
         '-count_frames',
         '-of', 'json', path],
        capture_output=True, text=True, timeout=15
    )
    try:
        info = json.loads(probe.stdout)
        streams = info.get('streams', [])
        if not streams:
            print(f"Node 3: Clip for '{keyword}' has no video stream — rejecting.")
            return False
    except Exception:
        pass

    sig = subprocess.run(
        ['/opt/homebrew/bin/ffmpeg', '-y',
         '-ss', '1',
         '-i', path,
         '-vframes', '1',
         '-vf', 'signalstats',
         '-f', 'null', '-'],
        capture_output=True, text=True, timeout=15
    )
    stderr = sig.stderr
    yavg, ydif = None, None
    for line in stderr.splitlines():
        if 'YAVG' in line:
            try: yavg = float(line.split(':')[-1].strip())
            except: pass
        if 'YDIF' in line:
            try: ydif = float(line.split(':')[-1].strip())
            except: pass

    if ydif is not None and ydif == 0.0:
        print(f"Node 3: Clip for '{keyword}' is a solid-colour frame (YDIF=0) — rejecting.")
        return False

    print(f"Node 3: Clip for '{keyword}' passed validation (YAVG={yavg}, YDIF={ydif}).")
    return True

def download_asset(url, destination_path):
    if url.startswith('http'):
        response = requests.get(url, stream=True, timeout=60)
        response.raise_for_status()
        with open(destination_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
    else:
        import shutil
        shutil.copy(url, destination_path)

def _load_timing(video_id):
    """Load timing.json if present, return list of {scene_index, start, end}."""
    timing_path = database.asset_path(video_id, 'timing.json')
    if os.path.exists(timing_path):
        try:
            with open(timing_path) as f:
                return json.load(f)
        except Exception:
            pass
    return None

def run():
    print("Node 3: Asset Fetching worker started.")
    videos = database.fetch_videos_by_status('Pending_Assets')

    for video in videos:
        print(f"Fetching assets for video ID {video['id']}")

        try:
            script_data = json.loads(video['script'])
            scenes = script_data.get('scenes', [])
        except Exception as e:
            database.update_video(video['id'], {'status': 'Failed', 'error_message': f"Node 3 JSON Parse Error: {e}"})
            continue

        downloaded_paths = []
        video_assets_dir = os.path.join(ASSETS_DIR, str(video['id']))
        os.makedirs(video_assets_dir, exist_ok=True)
        veo_generation_count = 0
        used_sources = set()

        timing = _load_timing(video['id'])

        try:
            for idx, scene in enumerate(scenes):
                raw_query = scene.get('visual_search_query', '')
                keyword = clean_query(raw_query)
                if not keyword:
                    keyword = "abstract background"

                min_duration = 2
                if timing and idx < len(timing):
                    min_duration = timing[idx]['end'] - timing[idx]['start'] + 0.5
                else:
                    pacing = scene.get('pacing_style', 'standard')
                    min_duration = {'rapid': 2, 'standard': 4, 'slow_pan': 8}.get(pacing, 4)

                print(f"Fetching scene {idx+1}: {keyword} (min_dur={min_duration:.1f}s)")
                dest_path = os.path.join(video_assets_dir, f"scene_{idx}.mp4")

                cp = cache_path(keyword)
                cache_key = hashlib.sha1(keyword.lower().strip().encode()).hexdigest()[:16]
                scene_success = False

                if os.path.exists(cp) and cache_key not in used_sources:
                    import shutil
                    shutil.copy(cp, dest_path)
                    if validate_clip(dest_path, keyword):
                        scene_success = True
                        used_sources.add(cache_key)
                        print(f"Node 3: Cache hit for '{keyword}'")

                if not scene_success:
                    try:
                        candidates = fetch_from_pexels(keyword, min_duration)
                        for sid, url in candidates:
                            if sid in used_sources:
                                continue
                            try:
                                download_asset(url, dest_path)
                                if validate_clip(dest_path, keyword):
                                    scene_success = True
                                    used_sources.add(sid)
                                    import shutil
                                    shutil.copy(dest_path, cp)
                                    print(f"Node 3: Fetched from Pexels for '{keyword}' (id={sid})")
                                    break
                                else:
                                    if os.path.exists(dest_path):
                                        os.remove(dest_path)
                            except Exception as e:
                                print(f"Node 3: Pexels candidate {sid} failed: {e}")
                                if os.path.exists(dest_path):
                                    os.remove(dest_path)
                    except Exception as e:
                        print(f"Node 3: Pexels failed for {keyword}: {e}")

                if not scene_success:
                    try:
                        candidates = fetch_from_pixabay(keyword, min_duration)
                        for sid, url in candidates:
                            if sid in used_sources:
                                continue
                            try:
                                download_asset(url, dest_path)
                                if validate_clip(dest_path, keyword):
                                    scene_success = True
                                    used_sources.add(sid)
                                    import shutil
                                    shutil.copy(dest_path, cp)
                                    print(f"Node 3: Fetched from Pixabay for '{keyword}' (id={sid})")
                                    break
                                else:
                                    if os.path.exists(dest_path):
                                        os.remove(dest_path)
                            except Exception as e:
                                print(f"Node 3: Pixabay candidate {sid} failed: {e}")
                                if os.path.exists(dest_path):
                                    os.remove(dest_path)
                    except Exception as e:
                        print(f"Node 3: Pixabay failed for {keyword}: {e}")

                if not scene_success:
                    if veo_generation_count >= 3:
                        raise Exception("Safety Limit: More than 3 Veo generations for a single video.")

                    try:
                        generate_veo_video(keyword, dest_path)
                        if validate_clip(dest_path, keyword):
                            scene_success = True
                            veo_generation_count += 1
                            database.add_cost(video['id'], COST_VEO_GENERATION)
                            print(f"Node 3: Veo generated for '{keyword}' ({veo_generation_count}/3)")
                        else:
                            if os.path.exists(dest_path):
                                os.remove(dest_path)
                    except Exception as e:
                        print(f"Node 3: Veo fallback failed: {e}")
                        if os.path.exists(dest_path):
                            os.remove(dest_path)

                if not scene_success:
                    raise Exception(f"Failed to fetch any valid asset for scene {idx}: '{keyword}'")

                downloaded_paths.append(dest_path)

            database.update_video(video['id'], {
                'video_path': json.dumps(downloaded_paths),
                'status': 'Pending_Render',
                'error_message': None
            })
            print(f"Updated video ID {video['id']} to Pending_Render with {len(downloaded_paths)} assets.")

        except Exception as e:
            error_str = str(e)
            print(f"Failed to fetch assets: {error_str}")
            database.update_video(video['id'], {
                'status': 'Failed',
                'error_message': f"Node 3 (Assets) Error: {error_str}"
            })

if __name__ == "__main__":
    while True:
        run()
        time.sleep(10)