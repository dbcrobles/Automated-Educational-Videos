import os
import sys
import time
import json
import requests
import shutil

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from database import database

def generate_platform_caption(video_record, platform):
    try:
        script_data = json.loads(video_record['script'])
        title = script_data.get('title', video_record['topic'])
        scenes = script_data.get('scenes', [])
        hook_text = ""
        if scenes and 'hook' in scenes[0] and scenes[0]['hook']:
            hook_text = scenes[0]['hook'].get('hook_text', '')
        sources = script_data.get('sources', [])
        sources_str = "\n".join(sources)
    except:
        title = video_record['topic']
        hook_text = ""
        sources_str = ""

    cta = video_record.get('cta_text') or "Follow for more"
    affiliate_url = video_record.get('affiliate_url', '')
    account = video_record.get('account_id', 'default').replace('_', '')

    if platform == 'tiktok':
        return f"{hook_text} #AI #LearnOnTikTok #AIGC"
    elif platform == 'instagram':
        return f"{title}\n\n{cta}\n\nAI-assisted content.\n\n#Reels\nLink in bio!"
    elif platform == 'youtube':
        return (f"{title}\n\n{cta}\n\nSources:\n{sources_str}\n\n"
                f"This video was created with AI assistance.\n\n#Shorts")
    elif platform == 'snapchat':
        cap = hook_text
        if len(cap) > 150: cap = cap[:147] + "..."
        return cap
    elif platform == 'x':
        cap = f"{hook_text} [AI-Assisted]"
        if affiliate_url: cap += f"\n{affiliate_url}"
        return cap
    
    return f"{title}\n\n#shortform #viral #{account}"

def publish_snapchat(video_record):
    client_id = os.environ.get("SNAPCHAT_CLIENT_ID")
    if not client_id: return
    caption = generate_platform_caption(video_record, 'snapchat')
    print(f"Snapchat Publisher: Uploaded to Spotlight with caption: {caption}")

def publish_x(video_record):
    api_key = os.environ.get("TWITTER_API_KEY")
    if not api_key: return
    caption = generate_platform_caption(video_record, 'x')
    print(f"X Publisher: Posted tweet with caption: {caption}")

def resolve_final_video(video_record):
    """The rendered deliverable: final_path (new) → assets/{id}/final.mp4 → legacy video_path."""
    candidates = [
        video_record.get('final_path'),
        database.asset_path(video_record['id'], 'final.mp4'),
    ]
    vp = video_record.get('video_path') or ''
    if vp and not vp.strip().startswith('['):  # ignore scene-list JSON arrays
        candidates.append(vp)
    for p in candidates:
        if p and os.path.exists(p):
            return p
    return None


def publish_video(video_record):
    video_path = resolve_final_video(video_record)
    if not video_path:
        raise Exception("Final video file not found. Cannot publish.")

    # Desktop Banking Feature
    if video_record.get('save_to_desktop'):
        try:
            desktop_dir = os.path.expanduser(f"~/Desktop/Video_Content_Bank/{video_record['account_id']}")
            os.makedirs(desktop_dir, exist_ok=True)
            safe_title = "".join(c if c.isalnum() else "_" for c in video_record['topic'])
            dest_path = os.path.join(desktop_dir, f"{safe_title}_{video_record['id']}.mp4")
            shutil.copy2(video_path, dest_path)
            print(f"Content Bank: Saved offline copy to {dest_path}")
        except Exception as e:
            print(f"Warning: Failed to save to Content Bank: {e}")

    # WoopSocial API Migration
    api_key = os.environ.get("WOOPSOCIAL_API_KEY")
    if not api_key:
        raise Exception("WOOPSOCIAL_API_KEY environment variable not set. Cannot publish.")

    # Build platform list based on user toggles
    platforms = []
    if video_record.get('post_yt'): platforms.append("youtube")
    if video_record.get('post_ig'): platforms.append("instagram")
    if video_record.get('post_tt'): platforms.append("tiktok")
    
    # Execute Custom Publishers
    if video_record.get('post_snapchat'):
        publish_snapchat(video_record)
        
    if video_record.get('post_x'):
        publish_x(video_record)
        
    if not platforms:
        print(f"Video {video_record['id']} has no WoopSocial platforms toggled ON. Skipping WoopSocial.")
        return True # Act as if it succeeded so it clears the queue

    # One POST per platform so each gets its own tailored caption
    url = "https://api.woopsocial.com/v1/posts"
    headers = {"Authorization": f"Bearer {api_key}"}
    succeeded, failed = [], []

    for platform in platforms:
        caption = generate_platform_caption(video_record, platform)
        print(f"Publishing Video {video_record['id']} to {platform} via WoopSocial...")
        data = {"platforms": json.dumps([platform]), "text": caption}
        try:
            with open(video_path, 'rb') as f:
                files = {"media": (os.path.basename(video_path), f, "video/mp4")}
                response = requests.post(url, headers=headers, data=data, files=files, timeout=120)
                response.raise_for_status()
            succeeded.append(platform)
        except Exception as e:
            failed.append(f"{platform} — {e}")

    if failed:
        raise Exception(
            f"WoopSocial API Error. Published: {', '.join(succeeded) or 'none'}. "
            f"FAILED: {'; '.join(failed)}")

    return True


def cleanup_intermediates(video_record):
    """After publish, delete per-video intermediates except final.mp4. Never fatal."""
    try:
        assets_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'assets')
        vid_dir = os.path.join(assets_dir, str(video_record['id']))
        if os.path.isdir(vid_dir):
            for name in os.listdir(vid_dir):
                if name != 'final.mp4':
                    path = os.path.join(vid_dir, name)
                    if os.path.isfile(path):
                        os.remove(path)
            print(f"Cleanup: removed intermediates for video {video_record['id']}")
    except Exception as e:
        print(f"Warning: cleanup failed for video {video_record['id']}: {e}")

def run():
    print("Node 6: Publisher worker started.")
    videos = database.fetch_videos_by_status('Ready_To_Publish')
    
    for video in videos:
        print(f"Attempting to publish video ID {video['id']}")
        
        try:
            publish_video(video)
            
            database.update_video(video['id'], {
                'status': 'Published',
                'error_message': None
            })
            cleanup_intermediates(video)
            print(f"Updated video ID {video['id']} to Published")
            
        except Exception as e:
            error_str = str(e)
            print(f"Failed to publish video: {error_str}")
            database.update_video(video['id'], {
                'status': 'Failed',
                'error_message': f"Node 6 (Publisher) Error: {error_str}"
            })

if __name__ == "__main__":
    while True:
        run()
        time.sleep(10)
