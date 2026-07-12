"""One-time music library setup.

Downloads public-domain background tracks (the former FreePD.com library,
mirrored on the Internet Archive — no API key required, free for commercial
use) into Backend/assets/music/{mood}/.

Run:  python3 Backend/scripts/fetch_music.py

If a mood folder ends up empty (URLs can change), grab free tracks manually:
  - https://pixabay.com/music/   (free, no attribution required)
  - https://archive.org/details/allfreepdmusicbykuronekony4n   (public domain)
and drop the .mp3 files into Backend/assets/music/{tense,uplifting,mysterious,neutral}/
"""
import os
import subprocess
import urllib.parse
import requests

ASSETS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'assets')
MUSIC_DIR = os.path.join(ASSETS_DIR, 'music')
FFPROBE = "/opt/homebrew/bin/ffprobe"
MAX_PER_MOOD = 3

# Public-domain FreePD mirror on archive.org (verified file list)
ARCHIVE_BASE = ("https://archive.org/download/allfreepdmusicbykuronekony4n/"
                "content/drive/My Drive/Download/all freepd music (by kuronekony4n)/")

# Candidate tracks per mood — the script tolerates dead links and keeps
# whatever validates, up to MAX_PER_MOOD per folder.
CANDIDATES = {
    "tense": [
        "Behind Enemy Lines", "Evil Incoming", "The Enemy",
        "Assassin", "Epic Boss Battle",
    ],
    "uplifting": [
        "City Sunshine", "Funshine", "Happy Whistling Ukulele",
        "Spring Chicken", "Motions",
    ],
    "mysterious": [
        "Night Vigil", "Ancient Rite", "Big Eyes",
        "Black Knight", "The Ice Giants",
    ],
    "neutral": [
        "Study and Relax", "Be Chillin", "Relaxing Ballad",
        "Screen Saver", "Still Pickin",
    ],
}


def is_valid_mp3(path):
    if not os.path.exists(path) or os.path.getsize(path) < 200_000:
        return False
    r = subprocess.run(
        [FFPROBE, '-v', 'error', '-select_streams', 'a:0',
         '-show_entries', 'stream=codec_type', '-of', 'csv=p=0', path],
        capture_output=True, text=True)
    return 'audio' in r.stdout


def fetch(title, dest):
    url = ARCHIVE_BASE.replace(' ', '%20') + urllib.parse.quote(f"{title}.mp3")
    try:
        resp = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=120)
        resp.raise_for_status()
        with open(dest, 'wb') as f:
            f.write(resp.content)
    except Exception as e:
        print(f"  ✗ {title}: {e}")
        if os.path.exists(dest):
            os.remove(dest)
        return False
    if not is_valid_mp3(dest):
        print(f"  ✗ {title}: downloaded file is not valid audio")
        os.remove(dest)
        return False
    print(f"  ✓ {title} ({os.path.getsize(dest) // 1024} KB)")
    return True


def main():
    for mood, titles in CANDIDATES.items():
        mood_dir = os.path.join(MUSIC_DIR, mood)
        os.makedirs(mood_dir, exist_ok=True)
        have = len([f for f in os.listdir(mood_dir) if f.endswith('.mp3')])
        print(f"\n[{mood}] existing tracks: {have}")
        for title in titles:
            if have >= MAX_PER_MOOD:
                break
            safe = title.replace(' ', '_').replace('-', '_') + '.mp3'
            dest = os.path.join(mood_dir, safe)
            if os.path.exists(dest):
                continue
            if fetch(title, dest):
                have += 1
        if have == 0:
            print(f"  ⚠ No tracks for '{mood}' — add MP3s manually (see docstring).")

    print("\nDone. Library contents:")
    for mood in CANDIDATES:
        mood_dir = os.path.join(MUSIC_DIR, mood)
        files = [f for f in os.listdir(mood_dir) if f.endswith('.mp3')] if os.path.isdir(mood_dir) else []
        print(f"  {mood}: {len(files)} track(s) {files}")


if __name__ == "__main__":
    main()