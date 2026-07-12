import sqlite3
import json
import os

DB_PATH = os.path.join(os.path.dirname(__file__), 'db.sqlite')
ASSETS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'assets')

def get_connection():
    return sqlite3.connect(DB_PATH)

def migrate():
    """Safe, idempotent schema migrations.  Add new columns here as the pipeline evolves."""
    conn = get_connection()
    cursor = conn.cursor()
    migrations = [
        ("qa_feedback", "TEXT"),
        ("hook_score", "REAL"),
        ("retention_estimate", "REAL"),
        ("cta_text", "TEXT"),
        ("is_sponsored", "INTEGER DEFAULT 0"),
        ("compliance_metadata", "TEXT"),
        ("post_snapchat", "INTEGER DEFAULT 0"),
        ("post_x", "INTEGER DEFAULT 0"),
        ("affiliate_url", "TEXT"),
        ("error_message", "TEXT"),
        ("auto_approve", "INTEGER DEFAULT 0"),
        ("use_human_intro", "INTEGER DEFAULT 0"),
        ("post_yt", "INTEGER DEFAULT 1"),
        ("post_ig", "INTEGER DEFAULT 1"),
        ("post_tt", "INTEGER DEFAULT 1"),
        ("save_to_desktop", "INTEGER DEFAULT 1"),
        ("script_retry_count", "INTEGER DEFAULT 0"),
        ("api_cost_estimate", "REAL DEFAULT 0"),
        ("final_path", "TEXT"),
        ("voice_name", "TEXT"),
    ]
    for col, defn in migrations:
        try:
            cursor.execute(f"ALTER TABLE videos ADD COLUMN {col} {defn}")
            conn.commit()
            print(f"DB migrate: added column '{col}'")
        except sqlite3.OperationalError:
            pass

    # One-time status-value migration (idempotent)
    status_remaps = [
        ("Pending_Voiceover", "Pending_Voice"),
        ("Pending_QA", "QA_Script"),
    ]
    for old, new in status_remaps:
        cursor.execute("UPDATE videos SET status=? WHERE status=?", (new, old))
    conn.commit()
    conn.close()

def add_cost(video_id, usd):
    """Accumulate API cost estimate for a video."""
    conn = get_connection()
    conn.execute(
        "UPDATE videos SET api_cost_estimate = COALESCE(api_cost_estimate, 0) + ? WHERE id = ?",
        (usd, video_id))
    conn.commit()
    conn.close()

def asset_path(video_id, filename):
    """Resolve new per-video path first, then legacy flat path."""
    new_path = os.path.join(ASSETS_DIR, str(video_id), filename)
    if os.path.exists(new_path):
        return new_path
    legacy_map = {
        'voiceover.mp3': f'voiceover_{video_id}.mp3',
        'timing.json': f'timing_{video_id}.json',
        'captions.json': f'captions_{video_id}.json',
        'final.mp4': f'final_{video_id}.mp4',
    }
    legacy_name = legacy_map.get(filename, filename)
    legacy_path = os.path.join(ASSETS_DIR, legacy_name)
    if os.path.exists(legacy_path):
        return legacy_path
    return new_path

# Auto-migrate on import so every worker and the dashboard always have the latest schema.
try:
    migrate()
except Exception:
    pass  # Table may not exist yet on very first run — main.py will create it

def fetch_videos_by_status(status, extra_condition=""):
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    query = f"SELECT * FROM videos WHERE status = ? {extra_condition}"
    cursor.execute(query, (status,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def update_video(video_id, updates):
    conn = get_connection()
    cursor = conn.cursor()
    set_clause = ", ".join([f"{k} = ?" for k in updates.keys()])
    values = list(updates.values())
    values.append(video_id)

    cursor.execute(f"UPDATE videos SET {set_clause}, updated_at = CURRENT_TIMESTAMP WHERE id = ?", values)
    conn.commit()
    conn.close()
