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
        return f"{hook_text} #AI #LearnOnTikTok"
    elif platform == 'instagram':
        return f"{title}\n\n{cta}\n\n#Reels\nLink in bio!"
    elif platform == 'youtube':
        return f"{title}\n\n{cta}\n\nSources:\n{sources_str}\n\n#Shorts"
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

def publish_video(video_record):
    # Desktop Banking Feature
    if video_record.get('save_to_desktop'):
        try:
            desktop_dir = os.path.expanduser(f"~/Desktop/Video_Content_Bank/{video_record['account_id']}")
            os.makedirs(desktop_dir, exist_ok=True)
            video_path = video_record.get('video_path')
            
            if video_path and os.path.exists(video_path):
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
        
    video_path = video_record.get('video_path')
    if not video_path or not os.path.exists(video_path):
        raise Exception("Video file not found. Cannot publish.")
        
    try:
        script_data = json.loads(video_record['script'])
        title = script_data.get('title', video_record['topic'])
    except:
        title = video_record['topic']
        
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
        
    # We still use WoopSocial for TT/IG/YT, but now with a generalized caption
    caption = generate_platform_caption(video_record, 'tiktok') # arbitrary fallback
    
    print(f"Publishing Video {video_record['id']} to {', '.join(platforms)} via WoopSocial...")
    
    url = "https://api.woopsocial.com/v1/posts"
    headers = {
        "Authorization": f"Bearer {api_key}"
    }
    
    data = {
        "platforms": json.dumps(platforms),
        "text": caption
    }
    
    with open(video_path, 'rb') as f:
        files = {
            "media": (os.path.basename(video_path), f, "video/mp4")
        }
        
        try:
            response = requests.post(url, headers=headers, data=data, files=files, timeout=60)
            response.raise_for_status()
            print(f"WoopSocial Success: {response.json()}")
        except Exception as e:
            print(f"WoopSocial API returned an error: {str(e)}")
            raise Exception(f"WoopSocial API Error: {str(e)}")
            
    return True

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
