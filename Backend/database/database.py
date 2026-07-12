import sqlite3
import json
import os
import hashlib
import re

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
        ("research_dossier", "TEXT"),
        ("storyboard_draft", "TEXT"),
        ("script_cost_estimate", "REAL DEFAULT 0"),
        ("visual_qa_result", "TEXT"),
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
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS pipeline_errors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            video_id INTEGER NOT NULL,
            node TEXT NOT NULL,
            error_code TEXT NOT NULL,
            fingerprint TEXT NOT NULL,
            message TEXT NOT NULL,
            details_json TEXT,
            attempt INTEGER DEFAULT 1,
            cost_snapshot REAL DEFAULT 0,
            occurrence_count INTEGER DEFAULT 1,
            status TEXT DEFAULT 'open',
            auto_recovered INTEGER DEFAULT 0,
            first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            resolved_at TIMESTAMP,
            FOREIGN KEY(video_id) REFERENCES videos(id) ON DELETE CASCADE
        )
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_pipeline_errors_video_status
        ON pipeline_errors(video_id, status, last_seen)
    """)
    cursor.execute("""
        INSERT INTO pipeline_errors
            (video_id, node, error_code, fingerprint, message, attempt,
             cost_snapshot, status)
        SELECT id, 'Legacy', 'LEGACY_FAILURE', printf('legacy-%d', id),
               error_message, COALESCE(script_retry_count, 1),
               COALESCE(api_cost_estimate, 0), 'open'
        FROM videos v
        WHERE status='Failed' AND error_message IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM pipeline_errors e WHERE e.video_id=v.id
          )
    """)
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

def add_script_cost(video_id, usd):
    """Track Node 1 spend separately so research retries stay visible."""
    conn = get_connection()
    conn.execute("""
        UPDATE videos
        SET api_cost_estimate = COALESCE(api_cost_estimate, 0) + ?,
            script_cost_estimate = COALESCE(script_cost_estimate, 0) + ?
        WHERE id = ?
    """, (usd, usd, video_id))
    conn.commit()
    conn.close()

def record_pipeline_error(video_id, node, error_code, message, details=None,
                          attempt=1, auto_recovered=False):
    """Create or increment one stable incident instead of losing repeat history."""
    normalized = re.sub(r'https?://\S+', '<url>', str(message).lower())
    normalized = re.sub(r'\d+(?:\.\d+)?', '<n>', normalized)
    fingerprint = hashlib.sha256(
        f"{node}|{error_code}|{normalized}".encode()).hexdigest()[:16]
    conn = get_connection()
    row = conn.execute("""
        SELECT id, occurrence_count FROM pipeline_errors
        WHERE video_id=? AND node=? AND fingerprint=? AND status='open'
        ORDER BY id DESC LIMIT 1
    """, (video_id, node, fingerprint)).fetchone()
    cost_row = conn.execute(
        "SELECT COALESCE(api_cost_estimate, 0) FROM videos WHERE id=?", (video_id,)
    ).fetchone()
    cost_snapshot = cost_row[0] if cost_row else 0
    if row:
        count = row[1] + 1
        conn.execute("""
            UPDATE pipeline_errors SET message=?, details_json=?, attempt=?,
                cost_snapshot=?, occurrence_count=?, auto_recovered=?,
                last_seen=CURRENT_TIMESTAMP WHERE id=?
        """, (str(message), json.dumps(details or {}), attempt, cost_snapshot,
              count, int(auto_recovered), row[0]))
    else:
        count = 1
        conn.execute("""
            INSERT INTO pipeline_errors
                (video_id, node, error_code, fingerprint, message, details_json,
                 attempt, cost_snapshot, auto_recovered)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (video_id, node, error_code, fingerprint, str(message),
              json.dumps(details or {}), attempt, cost_snapshot, int(auto_recovered)))
    conn.commit()
    conn.close()
    return fingerprint, count

def resolve_pipeline_errors(video_id, node, auto_recovered=True):
    """Close a node's incidents only after that node succeeds."""
    conn = get_connection()
    conn.execute("""
        UPDATE pipeline_errors SET status='resolved', auto_recovered=?,
            resolved_at=CURRENT_TIMESTAMP, last_seen=CURRENT_TIMESTAMP
        WHERE video_id=? AND node=? AND status='open'
    """, (int(auto_recovered), video_id, node))
    conn.commit()
    conn.close()

def fail_video(video_id, node, error_code, message, details=None, attempt=1):
    """Persist an incident and expose its stable code on the video card."""
    fingerprint, count = record_pipeline_error(
        video_id, node, error_code, message, details, attempt)
    update_video(video_id, {
        'status': 'Failed',
        'error_message': f"{node} [{error_code}] (seen {count}x): {message}",
    })
    return fingerprint, count

def asset_path(video_id, filename):
    """Resolve new per-video path first, then legacy flat path."""
    new_path = os.path.join(ASSETS_DIR, str(video_id), str(filename))
    if os.path.exists(new_path):
        return new_path
    legacy_map = {
        'voiceover.mp3': f'voiceover_{video_id}.mp3',
        'timing.json': f'timing_{video_id}.json',
        'captions.json': f'captions_{video_id}.json',
        'final.mp4': f'final_{video_id}.mp4',
    }
    legacy_name = legacy_map.get(filename) or filename
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
