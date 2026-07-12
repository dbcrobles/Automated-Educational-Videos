import os
import sys
import json
import time
import hashlib
import requests
import re
import subprocess
import glob
from io import BytesIO
from PIL import Image, ImageDraw

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from database import database

PEXELS_API_KEY = os.environ.get('PEXELS_API_KEY')
PIXABAY_API_KEY = os.environ.get('PIXABAY_API_KEY')

COST_VEO_GENERATION = 0.40
COST_VISUAL_REVIEW = 0.01
ASSETS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'assets')
FFMPEG = '/opt/homebrew/bin/ffmpeg'
APPROVED_RIGHTS = {'owned', 'licensed', 'permission', 'public_domain'}

def clean_query(query):
    q = re.sub(r'[\[\]]', '', query)
    q = re.sub(r'^(Pexels:|Pixabay:)\s*', '', q, flags=re.IGNORECASE)
    return q.strip()

def cache_path(query):
    h = hashlib.sha1(query.lower().strip().encode()).hexdigest()[:16]
    cache_dir = os.path.join(ASSETS_DIR, 'cache')
    os.makedirs(cache_dir, exist_ok=True)
    return os.path.join(cache_dir, f'{h}.mp4')

def fetch_from_pexels(keyword, min_duration=0, portrait=True):
    """Return ranked list of (source_id, url) tuples from Pexels."""
    if not PEXELS_API_KEY:
        raise Exception("PEXELS_API_KEY not set")

    orientation = "&orientation=portrait" if portrait else ""
    url = f"https://api.pexels.com/videos/search?query={keyword}{orientation}&per_page=8"
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

def fetch_stock_images(keyword):
    """Return provider/source/url tuples for still-image fallback."""
    candidates = []
    if PEXELS_API_KEY:
        response = requests.get(
            "https://api.pexels.com/v1/search",
            params={"query": keyword, "orientation": "portrait", "per_page": 5},
            headers={"Authorization": PEXELS_API_KEY}, timeout=15)
        if response.ok:
            candidates.extend(
                ("PexelsPhoto", str(photo['id']), photo['src'].get('large2x') or photo['src']['original'])
                for photo in response.json().get('photos', []))
    if PIXABAY_API_KEY:
        response = requests.get(
            "https://pixabay.com/api/",
            params={"key": PIXABAY_API_KEY, "q": keyword, "image_type": "photo",
                    "orientation": "vertical", "per_page": 10}, timeout=15)
        if response.ok:
            candidates.extend(
                ("PixabayPhoto", str(hit['id']), hit.get('largeImageURL') or hit['webformatURL'])
                for hit in response.json().get('hits', []))
    return candidates

def image_to_video(url, destination_path, duration):
    """Turn a stock still into a restrained vertical push-in shot."""
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    image = Image.open(BytesIO(response.content)).convert('RGB')
    still_path = destination_path + '.jpg'
    image.save(still_path, quality=92)
    frames = max(1, round(duration * 30))
    command = [
        FFMPEG, '-y', '-loop', '1', '-i', still_path, '-t', f'{duration:.2f}',
        '-vf', ("scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
                f"zoompan=z='min(zoom+0.0005,1.06)':d={frames}:s=1080x1920:fps=30"),
        '-an', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', destination_path,
    ]
    result = subprocess.run(command, capture_output=True, text=True)
    os.remove(still_path)
    if result.returncode != 0:
        raise Exception(result.stderr.splitlines()[-1])

def generate_veo_video(prompt, destination_path):
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise Exception("GEMINI_API_KEY not set. Required for Veo 3.1 fallback.")

    print(f"Calling Veo 3.1 API for prompt: '{prompt}'...")
    from google import genai
    from google.genai import types
    client = genai.Client(api_key=api_key)

    try:
        operation = client.models.generate_videos(
            model='veo-3.1-generate-preview',
            prompt=prompt,
            config=types.GenerateVideosConfig(
                aspect_ratio="9:16",
                duration_seconds=5
            )
        )
        deadline = time.time() + 180
        while not operation.done and time.time() < deadline:
            time.sleep(5)
            operation = client.operations.get(operation)
        response = operation.result or operation.response
        if not operation.done or not response or not response.generated_videos:
            raise Exception("Veo API returned empty video list.")

        with open(destination_path, 'wb') as f:
            video = response.generated_videos[0].video
            if video is None:
                raise Exception("Veo response did not contain downloadable video data.")
            f.write(video.video_bytes or client.files.download(file=video))
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

def _scene_queries(scene):
    """Return ordered primary/fallback searches, with old scripts supported."""
    queries = scene.get('visual_search_queries')
    if not isinstance(queries, list):
        queries = [scene.get('visual_search_query', '')]
    cleaned = []
    for query in queries:
        query = clean_query(str(query))
        if query and query.lower() not in {q.lower() for q in cleaned}:
            cleaned.append(query)
    return cleaned[:3] or ["people walking city"]

def _approved_media_by_id():
    catalog_path = os.path.join(ASSETS_DIR, 'source_media', 'catalog.json')
    if not os.path.exists(catalog_path):
        return {}
    with open(catalog_path) as f:
        data = json.load(f)
    entries = data.get('media', []) if isinstance(data, dict) else data
    source_dir = os.path.realpath(os.path.dirname(catalog_path))
    approved = {}
    for entry in entries:
        path = os.path.realpath(os.path.join(source_dir, str(entry.get('filename', ''))))
        valid_window = entry.get('approved_end_seconds', 0) > entry.get('approved_start_seconds', 0)
        platforms = entry.get('allowed_platforms', [])
        required_metadata = all(entry.get(key) for key in (
            'id', 'source_name', 'creator', 'source_url', 'credit_text'))
        if (entry.get('rights_status') in APPROVED_RIGHTS and valid_window
                and path.startswith(source_dir + os.sep) and os.path.isfile(path)
                and 'all' in platforms and required_metadata):
            approved[entry.get('id')] = {**entry, '_path': path}
    return approved

def _prepare_licensed_media(entry, destination_path, duration, keep_audio):
    """Extract only the catalog-approved interval from a rights-cleared local file."""
    approved_duration = entry['approved_end_seconds'] - entry['approved_start_seconds']
    if duration > approved_duration + 0.05:
        raise Exception(f"Requested {duration:.1f}s exceeds approved window for {entry.get('id')}")
    command = [
        FFMPEG, '-y', '-ss', str(entry['approved_start_seconds']), '-i', entry['_path'],
        '-t', f'{duration:.3f}', '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '20',
        '-pix_fmt', 'yuv420p',
    ]
    command += ['-c:a', 'aac'] if keep_audio else ['-an']
    command.append(destination_path)
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0 or not validate_clip(destination_path, entry.get('id', 'licensed media')):
        raise Exception(f"Could not prepare licensed media {entry.get('id')}")

def _try_stock_query(keyword, destination_path, min_duration, used_sources, rejected_sources):
    """Try cache, portrait and broad video providers, then a stock still."""
    cp = cache_path(keyword)
    cache_key = f"cache:{hashlib.sha1(keyword.lower().strip().encode()).hexdigest()[:16]}"
    metadata_path = cp + '.json'
    cached_source = cache_key
    try:
        with open(metadata_path) as f:
            cached_source = json.load(f).get('source_id', cache_key)
    except (OSError, json.JSONDecodeError):
        pass
    if (os.path.exists(cp) and cache_key not in used_sources
            and cache_key not in rejected_sources
            and cached_source not in rejected_sources):
        import shutil
        shutil.copy(cp, destination_path)
        if validate_clip(destination_path, keyword):
            used_sources.update({cache_key, cached_source})
            print(f"Node 3: Cache hit for '{keyword}'")
            return {'provider': 'Cache', 'source_id': cached_source, 'query': keyword}
        os.remove(cp)

    providers = (
        ("PexelsPortrait", lambda q, d: fetch_from_pexels(q, d, portrait=True)),
        ("PexelsBroad", lambda q, d: fetch_from_pexels(q, d, portrait=False)),
        ("Pixabay", fetch_from_pixabay),
    )
    for provider_name, fetcher in providers:
        try:
            for source_id, url in fetcher(keyword, min_duration):
                unique_id = f"{provider_name}:{source_id}"
                provider_root_id = f"Pexels:{source_id}" if provider_name.startswith('Pexels') else unique_id
                if (unique_id in used_sources or provider_root_id in used_sources
                        or provider_root_id in rejected_sources):
                    continue
                try:
                    download_asset(url, destination_path)
                    if validate_clip(destination_path, keyword):
                        used_sources.update({unique_id, provider_root_id, cache_key})
                        import shutil
                        shutil.copy(destination_path, cp)
                        with open(metadata_path, 'w') as f:
                            json.dump({'source_id': provider_root_id, 'provider': provider_name}, f)
                        print(f"Node 3: Fetched from {provider_name} for '{keyword}' (id={source_id})")
                        return {'provider': provider_name, 'source_id': provider_root_id, 'query': keyword}
                except Exception as e:
                    print(f"Node 3: {provider_name} candidate {source_id} failed: {e}")
                if os.path.exists(destination_path):
                    os.remove(destination_path)
        except Exception as e:
            print(f"Node 3: {provider_name} failed for '{keyword}': {e}")
    for provider, source_id, url in fetch_stock_images(keyword):
        unique_id = f"{provider}:{source_id}"
        if unique_id in used_sources or unique_id in rejected_sources:
            continue
        try:
            image_to_video(url, destination_path, max(2, min_duration))
            if validate_clip(destination_path, keyword):
                used_sources.add(unique_id)
                print(f"Node 3: Using {provider} still for '{keyword}' (id={source_id})")
                return {'provider': provider, 'source_id': unique_id, 'query': keyword}
        except Exception as e:
            print(f"Node 3: {provider} still {source_id} failed: {e}")
        if os.path.exists(destination_path):
            os.remove(destination_path)
    return None

def _contact_sheet(scene_paths):
    """Create one labelled representative frame per scene for multimodal QA."""
    thumbs = []
    for index, path in enumerate(scene_paths):
        frame_path = path + '.qa.jpg'
        result = subprocess.run(
            [FFMPEG, '-y', '-ss', '1', '-i', path, '-frames:v', '1',
             '-vf', 'scale=270:480:force_original_aspect_ratio=increase,crop=270:480', frame_path],
            capture_output=True, text=True)
        if result.returncode == 0 and os.path.exists(frame_path):
            image = Image.open(frame_path).convert('RGB')
            ImageDraw.Draw(image).rectangle((0, 0, 78, 34), fill='black')
            ImageDraw.Draw(image).text((8, 8), f"Scene {index + 1}", fill='white')
            thumbs.append(image.copy())
            os.remove(frame_path)
    if not thumbs:
        return None
    columns, width, height = min(4, len(thumbs)), 270, 480
    sheet = Image.new('RGB', (columns * width, ((len(thumbs) + columns - 1) // columns) * height))
    for index, image in enumerate(thumbs):
        sheet.paste(image, ((index % columns) * width, (index // columns) * height))
    buffer = BytesIO()
    sheet.save(buffer, format='JPEG', quality=82)
    return buffer.getvalue()

def review_visuals(script, scene_paths):
    """Return only clearly mismatched or duplicate scenes; uncertainty passes."""
    api_key = os.environ.get('GEMINI_API_KEY')
    sheet = _contact_sheet(scene_paths)
    if not api_key or not sheet:
        return []
    from google import genai
    from google.genai import types
    scenes = [{'scene_index': index, 'narration': scene.get('narration', ''),
               'queries': _scene_queries(scene)}
              for index, scene in enumerate(script.get('scenes', []))]
    response = genai.Client(api_key=api_key).models.generate_content(
        model='gemini-3.5-flash',
        contents=[
            """Act as a conservative stock-footage editor. Compare each labelled frame to its scene narration.
            Reject only footage that is clearly irrelevant, misleading, bizarre, or a duplicate of another scene.
            Do not reject merely for being generic. Return JSON with `rejected`: a list containing scene_index,
            brief reason, and 1-3 replacement_queries of 2-5 concrete visual words. Return an empty list if unsure.
            Scene plan: """ + json.dumps(scenes),
            types.Part.from_bytes(data=sheet, mime_type='image/jpeg'),
        ],
        config=types.GenerateContentConfig(response_mime_type='application/json', temperature=0.1),
    )
    try:
        rejected = json.loads(response.text or '{}').get('rejected', [])
        return [item for item in rejected
                if isinstance(item.get('scene_index'), int)
                and 0 <= item['scene_index'] < len(scene_paths)]
    except (json.JSONDecodeError, AttributeError):
        return []

def _load_asset_manifest(video_assets_dir):
    try:
        with open(os.path.join(video_assets_dir, 'asset_manifest.json')) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}

def _scene_files(video_assets_dir, scene_index):
    primary = os.path.join(video_assets_dir, f'scene_{scene_index}.mp4')
    return ([primary] if os.path.exists(primary) else []) + sorted(
        glob.glob(os.path.join(video_assets_dir, f'scene_{scene_index}_clip_*.mp4')))

def _replace_flagged_scene(video_assets_dir, scene_index, duration, queries,
                           used_sources, rejected_sources):
    """Fetch one genuinely different visual before deleting the current scene."""
    temporary = os.path.join(video_assets_dir, f'qa_replacement_{scene_index}.mp4')
    for query in queries:
        result = _try_stock_query(
            clean_query(str(query)), temporary, max(2, duration + 0.5),
            used_sources, rejected_sources)
        if result:
            for old_path in _scene_files(video_assets_dir, scene_index):
                os.remove(old_path)
            destination = os.path.join(video_assets_dir, f'scene_{scene_index}.mp4')
            os.replace(temporary, destination)
            return destination, result
    if os.path.exists(temporary):
        os.remove(temporary)
    return None, None

def run():
    print("Node 3: Asset Fetching worker started.")
    videos = database.fetch_videos_by_status('Pending_Assets')

    for video in videos:
        print(f"Fetching assets for video ID {video['id']}")

        try:
            script_data = json.loads(video['script'])
            scenes = script_data.get('scenes', [])
        except Exception as e:
            database.fail_video(video['id'], 'Node 3', 'SCRIPT_JSON_INVALID', str(e))
            continue

        video_assets_dir = os.path.join(ASSETS_DIR, str(video['id']))
        os.makedirs(video_assets_dir, exist_ok=True)
        previous_manifest = _load_asset_manifest(video_assets_dir)
        replacement_requested = str(video.get('qa_feedback') or '').startswith('[VISUAL_REPLACEMENT]')
        rejected_sources = set()
        if replacement_requested:
            rejected_sources = {
                source.get('source_id')
                for entry in previous_manifest.get('scenes', [])
                for source in entry.get('sources', [])
                if source.get('source_id')
            }
            rejected_sources.update(
                f"cache:{hashlib.sha1(query.lower().strip().encode()).hexdigest()[:16]}"
                for scene in scenes for query in _scene_queries(scene))
        for old_clip in glob.glob(os.path.join(video_assets_dir, 'scene_*.mp4')):
            os.remove(old_clip)
        veo_generation_count = 0
        used_sources = set()
        approved_media = _approved_media_by_id()
        manifest_scenes = []

        timing = _load_timing(video['id'])

        try:
            for idx, scene in enumerate(scenes):
                queries = _scene_queries(scene)

                scene_duration = 2
                if timing and idx < len(timing):
                    scene_duration = timing[idx]['end'] - timing[idx]['start']
                else:
                    try:
                        scene_duration = float(scene.get('duration_seconds', 0)) or 2
                    except (TypeError, ValueError):
                        pacing = scene.get('pacing_style', 'standard')
                        scene_duration = {'rapid': 2, 'standard': 4, 'slow_pan': 8}.get(pacing, 4)

                target_count = min(len(queries), 3) if scene_duration >= 5 else 1
                clip_min_duration = max(2, scene_duration / target_count + 0.5)
                scene_paths = []
                scene_sources = []
                print(f"Fetching scene {idx+1}: {queries} ({target_count} clip target, min_dur={clip_min_duration:.1f}s)")

                media_spec = {} if replacement_requested else (scene.get('licensed_media') or {})
                if media_spec:
                    entry = approved_media.get(media_spec.get('media_id'))
                    if not entry:
                        raise Exception(f"Scene {idx + 1} selected unapproved media ID")
                    keep_audio = media_spec.get('playback_mode') == 'source_audio'
                    if keep_audio and not entry.get('allow_original_audio'):
                        raise Exception(f"Original audio is not approved for {entry.get('id')}")
                    dest_path = os.path.join(video_assets_dir, f"scene_{idx}.mp4")
                    _prepare_licensed_media(entry, dest_path, scene_duration, keep_audio)
                    scene_paths.append(dest_path)
                    scene_sources.append({
                        'provider': 'LicensedMedia',
                        'source_id': f"LicensedMedia:{entry.get('id')}",
                        'query': entry.get('description') or entry.get('source_name'),
                    })
                    print(f"Node 3: Prepared rights-cleared media '{entry.get('id')}'")

                for query in queries if not media_spec else []:
                    if len(scene_paths) >= target_count:
                        break
                    suffix = '' if not scene_paths else f'_clip_{len(scene_paths)}'
                    dest_path = os.path.join(video_assets_dir, f"scene_{idx}{suffix}.mp4")
                    result = _try_stock_query(
                        query, dest_path, clip_min_duration, used_sources, rejected_sources)
                    if result:
                        scene_paths.append(dest_path)
                        scene_sources.append(result)

                if not scene_paths:
                    if veo_generation_count >= 3:
                        raise Exception("Safety Limit: More than 3 Veo generations for a single video.")

                    dest_path = os.path.join(video_assets_dir, f"scene_{idx}.mp4")
                    try:
                        generate_veo_video(queries[0], dest_path)
                        if validate_clip(dest_path, queries[0]):
                            scene_paths.append(dest_path)
                            scene_sources.append({
                                'provider': 'Veo',
                                'source_id': f"Veo:{hashlib.sha1(queries[0].encode()).hexdigest()[:12]}",
                                'query': queries[0],
                            })
                            veo_generation_count += 1
                            database.add_cost(video['id'], COST_VEO_GENERATION)
                            print(f"Node 3: Veo generated for '{queries[0]}' ({veo_generation_count}/3)")
                        else:
                            if os.path.exists(dest_path):
                                os.remove(dest_path)
                    except Exception as e:
                        print(f"Node 3: Veo fallback failed: {e}")
                        if os.path.exists(dest_path):
                            os.remove(dest_path)

                if not scene_paths:
                    raise Exception(f"Failed to fetch any valid asset for scene {idx}: {queries}")

                manifest_scenes.append({
                    'scene_index': idx,
                    'narration': scene.get('narration', ''),
                    'sources': scene_sources,
                })

            representatives = [_scene_files(video_assets_dir, index)[0]
                               for index in range(len(scenes))]
            review_results = []
            try:
                flagged = review_visuals(script_data, representatives)
                if os.environ.get('GEMINI_API_KEY'):
                    database.add_cost(video['id'], COST_VISUAL_REVIEW)
                for item in flagged:
                    index = item['scene_index']
                    prior_ids = {
                        source.get('source_id') for source in manifest_scenes[index]['sources']
                        if source.get('source_id')
                    }
                    replacement_path, replacement_source = _replace_flagged_scene(
                        video_assets_dir, index,
                        float(scenes[index].get('duration_seconds', 4)),
                        item.get('replacement_queries') or _scene_queries(scenes[index]),
                        used_sources, rejected_sources | prior_ids)
                    repaired = bool(replacement_path)
                    item['repaired'] = repaired
                    review_results.append(item)
                    if repaired:
                        manifest_scenes[index]['sources'] = [replacement_source]
                if flagged:
                    print(f"Node 3: Visual QA flagged {len(flagged)} scene(s); "
                          f"replaced {sum(bool(item.get('repaired')) for item in review_results)}.")
            except Exception as review_error:
                review_results = [{'warning': f'Visual review skipped: {review_error}'}]
                print(f"Node 3: Visual review skipped: {review_error}")

            downloaded_paths = [path for index in range(len(scenes))
                                for path in _scene_files(video_assets_dir, index)]
            manifest = {
                'replacement_requested': replacement_requested,
                'previous_sources_excluded': sorted(rejected_sources),
                'scenes': manifest_scenes,
                'visual_review': review_results,
            }
            with open(os.path.join(video_assets_dir, 'asset_manifest.json'), 'w') as f:
                json.dump(manifest, f, indent=2)

            database.update_video(video['id'], {
                'video_path': json.dumps(downloaded_paths),
                'visual_qa_result': json.dumps(review_results),
                'status': 'Pending_Render',
                'error_message': None,
                'qa_feedback': None,
            })
            database.resolve_pipeline_errors(video['id'], 'Node 3')
            print(f"Updated video ID {video['id']} to Pending_Render with {len(downloaded_paths)} assets.")

        except Exception as e:
            error_str = str(e)
            print(f"Failed to fetch assets: {error_str}")
            database.fail_video(video['id'], 'Node 3', 'ASSET_FETCH', error_str)

if __name__ == "__main__":
    while True:
        run()
        time.sleep(10)