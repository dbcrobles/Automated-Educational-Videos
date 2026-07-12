import reflex as rx
import sys
import os
import json
from dotenv import load_dotenv
from google import genai
from pydantic import BaseModel

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), '.env'))

# Add parent directory to access database and router
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'Backend'))
from database import database

POPULAR_VOICES = {
    "Brian (American, deep)": "nPczCjzI2devNBz1zQrb",
    "Charlie (American, natural)": "IKne3meq5aSn9XLyUdCD",
    "George (British, warm)": "JBFqnCBsd6RMkjVDRZzb",
    "Liam (American, articulate)": "TX3LPaxmHKxFdv7VOQHJ",
    "Will (American, friendly)": "bIHbv24MWmeRgasZH58o",
    "Aria (American, expressive)": "9BWtsMINqrJLrRacOk9x",
    "Sarah (American, calm)": "EXAVITQu4vr4xnSDxMaL",
    "Laura (American, upbeat)": "FGY2WhTYpPnrIDTdsKH5",
    "Alice (British, confident)": "Xb7hH8MSUJpSbSDYk0k2",
    "River (American, neutral)": "SAz9YHcvj6GT2YYXdXww"
}
VOICE_IDS_TO_NAMES = {v: k for k, v in POPULAR_VOICES.items()}
ACCOUNTS_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    'Backend', 'accounts_config.json')

def _configured_account_ids():
    try:
        with open(ACCOUNTS_CONFIG_PATH, 'r') as f:
            return list(json.load(f).keys())
    except (OSError, json.JSONDecodeError):
        return ["personal_finance", "health_economics", "health_tech"]

ACCOUNT_IDS = _configured_account_ids()

GEMINI_MODEL = "gemini-3.1-pro"

# Pipeline stage order for progress bar display
PIPELINE_STAGES = [
    "Pending_Script", "QA_Script",
    "Pending_Voice", "Pending_Assets", "Pending_Render",
    "QA_Final", "Ready_To_Publish", "Published"
]

STATUS_META = {
    "Pending_Script":    {"label": "Scripting…",      "color": "indigo"},
    "QA_Script":         {"label": "Awaiting Approval","color": "orange"},
    "Pending_Voice": {"label": "Voiceover…",       "color": "violet"},
    "Pending_Assets":    {"label": "Fetching Assets…", "color": "blue"},
    "Pending_Render":    {"label": "Rendering…",       "color": "purple"},
    "QA_Final":          {"label": "Final Check",      "color": "amber"},
    "Ready_To_Publish":  {"label": "Publishing…",      "color": "teal"},
    "Published":         {"label": "Published ✓",      "color": "green"},
    "Failed":            {"label": "Failed",            "color": "red"},
}

class VideoModel(BaseModel):
    id: int
    topic: str
    account_id: str
    status: str
    script: str
    script_sources: str
    video_path: str
    error_message: str
    script_sources_list: list[str]
    hook_score: float
    retention_estimate: float
    is_sponsored: bool
    cta_text: str
    compliance_metadata: str
    post_snapchat: bool
    post_x: bool
    affiliate_url: str
    api_cost_estimate: float = 0.0
    final_path: str = ""
    voice_name: str = ""
    script_cost_estimate: float = 0.0
    visual_qa_result: str = ""
    error_code: str = ""
    error_repeat_count: int = 0
    error_attempt: int = 0
    error_cost_snapshot: float = 0.0
    stage_pct: int = 0

class BatchSplitOutput(BaseModel):
    sub_topics: list[str]

class State(rx.State):
    videos: list[VideoModel] = []
    engine_online: bool = False

    # Form fields
    new_topic: str = ""
    new_category: str = "personal_finance"
    batch_size: str = "1"
    feedback_text: str = ""           # kept for Ollama quick-edit path
    rejection_notes: dict = {}         # per-video rejection note, keyed by video id
    is_generating: bool = False
    night_mode: bool = False
    use_human_intro: bool = True
    post_yt: bool = True
    post_ig: bool = True
    post_tt: bool = True
    post_snapchat: bool = False
    post_x: bool = False
    save_to_desktop: bool = True

    # Content Config
    cta_text: str = ""
    affiliate_url: str = ""
    api_cost_estimate: float = 0.0
    is_sponsored: bool = False

    # Intro Management
    upload_account: str = "personal_finance"
    intro_files: list[str] = []

    # Account Settings
    settings_account: str = "personal_finance"
    selected_voice_name: str = "Brian (American, deep)"
    default_cta_text: str = ""
    snapchat_ad_account_id: str = ""
    x_handle: str = ""

    @rx.event
    def set_new_topic(self, val: str):
        self.new_topic = val

    @rx.event
    def set_new_category(self, val: str):
        self.new_category = val

    @rx.event
    def set_batch_size(self, val: str):
        self.batch_size = val

    @rx.event
    def set_feedback_text(self, val: str):
        self.feedback_text = val

    @rx.event
    def set_rejection_note(self, video_id: int, val: str):
        """Store per-video rejection note as the user types."""
        self.rejection_notes[video_id] = val

    @rx.event
    def set_night_mode(self, val: bool):
        self.night_mode = val

    @rx.event
    def set_use_human_intro(self, val: bool):
        self.use_human_intro = val

    @rx.event
    def set_post_yt(self, val: bool):
        self.post_yt = val

    @rx.event
    def set_post_ig(self, val: bool):
        self.post_ig = val

    @rx.event
    def set_post_tt(self, val: bool):
        self.post_tt = val

    @rx.event
    def set_post_snapchat(self, val: bool):
        self.post_snapchat = val

    @rx.event
    def set_post_x(self, val: bool):
        self.post_x = val

    @rx.event
    def set_save_to_desktop(self, val: bool):
        self.save_to_desktop = val

    @rx.event
    def set_cta_text(self, val: str):
        self.cta_text = val

    @rx.event
    def set_affiliate_url(self, val: str):
        self.affiliate_url = val

    @rx.event
    def set_is_sponsored(self, val: bool):
        self.is_sponsored = val

    def on_load(self):
        self.load_videos()
        self.load_intros()
        self.load_settings()

    @rx.event
    def tick(self, date: str):
        """Auto-refresh driven by an invisible rx.moment timer."""
        self.load_videos()

    def _check_engine(self):
        """Orchestrator heartbeat: main.py touches this file every loop."""
        hb = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'Backend', 'orchestrator.heartbeat')
        try:
            import time as _time
            self.engine_online = (_time.time() - os.path.getmtime(hb)) < 60
        except OSError:
            self.engine_online = False

    def load_videos(self):
        conn = database.get_connection()
        conn.row_factory = database.sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM videos ORDER BY id DESC")
        rows = cursor.fetchall()
        conn.close()

        # Convert sqlite3.Row to dict to allow .get() with fallbacks
        rows_dicts = [dict(row) for row in rows]
        conn = database.get_connection()
        conn.row_factory = database.sqlite3.Row
        incident_rows = conn.execute("""
            SELECT e.* FROM pipeline_errors e
            JOIN (
                SELECT video_id, MAX(id) AS max_id FROM pipeline_errors
                WHERE status='open' GROUP BY video_id
            ) latest ON latest.max_id=e.id
        """).fetchall()
        conn.close()
        incidents = {row['video_id']: dict(row) for row in incident_rows}

        def _stage_pct(status):
            if status in PIPELINE_STAGES:
                return round((PIPELINE_STAGES.index(status) + 1) * 100 / len(PIPELINE_STAGES))
            return 0

        self.videos = [
            VideoModel(
                id=row['id'],
                topic=row['topic'],
                account_id=row['account_id'],
                status=row['status'],
                script=row['script'] or "",
                script_sources=row['script_sources'] or "[]",
                video_path=row['video_path'] or "",
                error_message=row['error_message'] or "",
                script_sources_list=json.loads(row['script_sources']) if row['script_sources'] else [],
                hook_score=row.get('hook_score') or 0.0,
                retention_estimate=row.get('retention_estimate') or 0.0,
                is_sponsored=bool(row.get('is_sponsored', 0)),
                cta_text=row.get('cta_text') or "",
                compliance_metadata=row.get('compliance_metadata') or "",
                post_snapchat=bool(row.get('post_snapchat', 0)),
                post_x=bool(row.get('post_x', 0)),
                affiliate_url=row.get('affiliate_url') or "",
                api_cost_estimate=row.get('api_cost_estimate') or 0.0,
                final_path=row.get('final_path') or "",
                voice_name=row.get('voice_name') or "",
                script_cost_estimate=row.get('script_cost_estimate') or 0.0,
                visual_qa_result=row.get('visual_qa_result') or "",
                error_code=incidents.get(row['id'], {}).get('error_code', ''),
                error_repeat_count=incidents.get(row['id'], {}).get('occurrence_count', 0),
                error_attempt=incidents.get(row['id'], {}).get('attempt', 0),
                error_cost_snapshot=incidents.get(row['id'], {}).get('cost_snapshot', 0.0),
                stage_pct=_stage_pct(row['status']),
            )
            for row in rows_dicts
        ]

        # Prepare video previews for QA_Final videos
        for row in rows_dicts:
            if row.get('status') == 'QA_Final':
                self.prepare_preview(row['id'])

        self._check_engine()

    def add_video(self):
        if not self.new_topic:
            return

        self.is_generating = True
        yield

        try:
            batch_count = int(self.batch_size)
        except Exception:
            batch_count = 1

        topics_to_insert = [self.new_topic]

        if batch_count > 1:
            try:
                api_key = os.environ.get("GEMINI_API_KEY")
                # FIX: Pass api_key explicitly to avoid GOOGLE_API_KEY vs GEMINI_API_KEY confusion
                client = genai.Client(api_key=api_key)
                prompt = f"Break down the broad topic '{self.new_topic}' into {batch_count} distinct, highly engaging sub-topics suitable for short-form viral videos."
                response = client.models.generate_content(
                    model=GEMINI_MODEL,
                    contents=prompt,
                    config=genai.types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=BatchSplitOutput,
                    ),
                )
                output = json.loads(response.text)
                topics_to_insert = output.get("sub_topics", [self.new_topic])
            except Exception as e:
                print(f"Batch generation failed: {e}. Falling back to single topic.")
                topics_to_insert = [self.new_topic]

        conn = database.get_connection()
        cursor = conn.cursor()
        for topic in topics_to_insert:
            cursor.execute(
                "INSERT INTO videos (topic, account_id, auto_approve, use_human_intro, post_yt, post_ig, post_tt, post_snapchat, post_x, save_to_desktop, cta_text, affiliate_url, is_sponsored) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (topic, self.new_category, self.night_mode, self.use_human_intro, self.post_yt, self.post_ig, self.post_tt, self.post_snapchat, self.post_x, self.save_to_desktop, self.cta_text, self.affiliate_url, 1 if self.is_sponsored else 0)
            )
        conn.commit()
        conn.close()

        self.new_topic = ""
        self.is_generating = False
        self.load_videos()

    def approve_script(self, video_id: int):
        database.update_video(video_id, {'status': 'Pending_Voice'})
        self.load_videos()


    def approve_video(self, video_id: int):
        database.update_video(video_id, {'status': 'Ready_To_Publish'})
        self.load_videos()

    def retry_video(self, video_id: int):
        """Smart retry: resume from the furthest stage that already has valid output on disk.

        Stage order (earliest → latest):
          Pending_Script → (QA_Script) → Pending_Voice → Pending_Assets
          → Pending_Render → (QA_Final) → Ready_To_Publish → Published

        Checks (most advanced first):
          1. voiceover_path exists on disk AND stock video assets exist on disk
             → resume at Pending_Render  (skips scripting + ElevenLabs + asset fetch)
          2. voiceover_path exists on disk only
             → resume at Pending_Assets  (skips scripting + ElevenLabs)
          3. script JSON exists in DB (QA was approved)
             → resume at Pending_Voice  (skips scripting + QA)
          4. Fallback → Pending_Script  (full restart)
        """
        conn = database.get_connection()
        conn.row_factory = database.sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM videos WHERE id = ?", (video_id,))
        row = cursor.fetchone()
        conn.close()

        if row is None:
            return

        video = dict(row)
        resume_status = 'Pending_Script'  # default: full restart

        # Check 3: script exists (QA_Script was approved)
        if video.get('script'):
            resume_status = 'Pending_Voice'

        # Check 2: voiceover file is on disk
        vpath = video.get('voiceover_path') or ''
        if vpath and os.path.exists(vpath):
            resume_status = 'Pending_Assets'

        # Check 1: voiceover AND stock video assets are all on disk
        vpath_field = video.get('video_path') or ''
        if vpath and os.path.exists(vpath) and vpath_field:
            try:
                asset_paths = json.loads(vpath_field) if vpath_field.startswith('[') else [vpath_field]
                if asset_paths and all(os.path.exists(p) for p in asset_paths):
                    resume_status = 'Pending_Render'
            except (json.JSONDecodeError, TypeError):
                pass

        note = str(self.rejection_notes.get(video_id, "")).strip()
        updates = {'status': resume_status, 'error_message': None}
        if note:
            updates['qa_feedback'] = note
        print(f"Smart retry: video {video_id} → {resume_status}" + (f" (with note)" if note else ""))
        database.update_video(video_id, updates)
        self.rejection_notes = {k: v for k, v in self.rejection_notes.items() if k != video_id}
        self.load_videos()

    def retry_from_scratch(self, video_id: int):
        """Hard reset — always starts from Node 1 (scripting)."""
        note = str(self.rejection_notes.get(video_id, "")).strip()
        updates = {
            'status': 'Pending_Script', 'error_message': None,
            'research_dossier': None, 'storyboard_draft': None,
            'script_retry_count': 0, 'script_cost_estimate': 0,
        }
        if note:
            updates['qa_feedback'] = note
        database.update_video(video_id, updates)
        self.rejection_notes = {k: v for k, v in self.rejection_notes.items() if k != video_id}
        self.load_videos()

    def reject_to_script(self, video_id: int):
        """Revise the storyboard while preserving the expensive research checkpoint."""
        note = str(self.rejection_notes.get(video_id, "")).strip()
        conn = database.get_connection()
        row = conn.execute("SELECT script FROM videos WHERE id = ?", (video_id,)).fetchone()
        conn.close()
        updates = {
            'status': 'Pending_Script', 'error_message': None,
            'storyboard_draft': row[0] if row and row[0] else None,
            'script_retry_count': 0,
        }
        if note:
            updates['qa_feedback'] = note
        database.update_video(video_id, updates)
        self.rejection_notes = {k: v for k, v in self.rejection_notes.items() if k != video_id}
        self.load_videos()

    def reject_to_voiceover(self, video_id: int):
        """Send back to Node 2b (ElevenLabs) with editor note — re-record only."""
        note = str(self.rejection_notes.get(video_id, "")).strip()
        updates = {'status': 'Pending_Voice', 'error_message': None}
        if note:
            updates['qa_feedback'] = note
        database.update_video(video_id, updates)
        self.rejection_notes = {k: v for k, v in self.rejection_notes.items() if k != video_id}
        self.load_videos()

    def reject_to_render(self, video_id: int):
        """Send back to Node 4 (FFmpeg render) with editor note — cheapest retry."""
        note = str(self.rejection_notes.get(video_id, "")).strip()
        updates = {'status': 'Pending_Render', 'error_message': None}
        if note:
            updates['qa_feedback'] = note
        database.update_video(video_id, updates)
        self.rejection_notes = {k: v for k, v in self.rejection_notes.items() if k != video_id}
        self.load_videos()

    def reject_to_assets(self, video_id: int):
        """Replace stock visuals while preserving approved script, voice, and research."""
        note = str(self.rejection_notes.get(video_id, "")).strip()
        feedback = f"[VISUAL_REPLACEMENT] {note or 'Replace the rejected visual choices.'}"
        database.update_video(video_id, {
            'status': 'Pending_Assets', 'qa_feedback': feedback,
            'error_message': None, 'visual_qa_result': None,
        })
        self.rejection_notes = {k: v for k, v in self.rejection_notes.items() if k != video_id}
        self.load_videos()


    def prepare_preview(self, video_id: int):
        """Symlink final.mp4 into Frontend/assets/ so Reflex can serve it."""
        frontend_assets = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'assets')
        os.makedirs(frontend_assets, exist_ok=True)
        preview_path = os.path.join(frontend_assets, f'preview_{video_id}.mp4')
        conn = database.get_connection()
        conn.row_factory = database.sqlite3.Row
        row = conn.execute("SELECT final_path, video_path FROM videos WHERE id = ?", (video_id,)).fetchone()
        conn.close()
        src = None
        if row:
            src = row['final_path'] or database.asset_path(video_id, 'final.mp4')
            if (not src or not os.path.exists(src)) and row['video_path'] and not str(row['video_path']).startswith('['):
                src = row['video_path']
        if src and os.path.exists(src):
            if os.path.exists(preview_path) or os.path.islink(preview_path):
                os.remove(preview_path)
            os.symlink(src, preview_path)

    def delete_video(self, video_id: int):
        preview_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'assets', f'preview_{video_id}.mp4')
        if os.path.exists(preview_path) or os.path.islink(preview_path):
            os.remove(preview_path)
        conn = database.get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM videos WHERE id = ?", (video_id,))
        conn.commit()
        conn.close()
        self.load_videos()

    # Intro Management Methods
    def update_upload_account(self, val: str):
        self.upload_account = val
        self.load_intros()

    def load_intros(self):
        assets_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'Backend', 'assets', 'intros', self.upload_account)
        if not os.path.exists(assets_dir):
            os.makedirs(assets_dir, exist_ok=True)
            self.intro_files = []
        else:
            self.intro_files = [f for f in os.listdir(assets_dir) if f.endswith('.mp4')]

    async def handle_upload(self, files: list[rx.UploadFile]):
        assets_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'Backend', 'assets', 'intros', self.upload_account)
        for file in files:
            upload_data = await file.read()
            outfile = os.path.join(assets_dir, file.filename)
            with open(outfile, "wb") as file_object:
                file_object.write(upload_data)
        self.load_intros()

    def delete_intro(self, filename: str):
        filepath = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'Backend', 'assets', 'intros', self.upload_account, filename)
        if os.path.exists(filepath):
            os.remove(filepath)
        self.load_intros()

    # Account Settings Methods
    def load_settings(self):
        with open(ACCOUNTS_CONFIG_PATH, 'r') as f:
            config = json.load(f)
        acc = config.get(self.settings_account, {})
        voice_id = acc.get('elevenlabs_voice_id', POPULAR_VOICES["Brian (American, deep)"])
        self.selected_voice_name = VOICE_IDS_TO_NAMES.get(voice_id, "Brian (American, deep)")
        self.default_cta_text = acc.get('default_cta', "")
        self.snapchat_ad_account_id = acc.get('snapchat_ad_account_id', "")
        self.x_handle = acc.get('x_handle', "")

    def update_settings_account(self, val: str):
        self.settings_account = val
        self.load_settings()

    def save_voice_name(self, val: str):
        self.selected_voice_name = val
        self._save_settings()

    @rx.event
    def set_default_cta_text(self, val: str):
        self.default_cta_text = val
        self._save_settings()

    @rx.event
    def set_snapchat_ad_account_id(self, val: str):
        self.snapchat_ad_account_id = val
        self._save_settings()

    @rx.event
    def set_x_handle(self, val: str):
        self.x_handle = val
        self._save_settings()

    def _save_settings(self):
        voice_id = POPULAR_VOICES.get(self.selected_voice_name, POPULAR_VOICES["Brian (American, deep)"])
        with open(ACCOUNTS_CONFIG_PATH, 'r') as f:
            config = json.load(f)
        if self.settings_account in config:
            config[self.settings_account]['elevenlabs_voice_id'] = voice_id
            config[self.settings_account]['elevenlabs_voice_name'] = self.selected_voice_name
            config[self.settings_account]['voice_mode'] = 'fixed'
            config[self.settings_account].pop('voice_profiles', None)
            config[self.settings_account]['default_cta'] = self.default_cta_text
            config[self.settings_account]['snapchat_ad_account_id'] = self.snapchat_ad_account_id
            config[self.settings_account]['x_handle'] = self.x_handle
        with open(ACCOUNTS_CONFIG_PATH, 'w') as f:
            json.dump(config, f, indent=2)


# ─── UI HELPERS ───────────────────────────────────────────────────────────────

def toggle_row(label: str, icon: str, state_val, handler) -> rx.Component:
    """A clean labelled toggle with icon."""
    return rx.hstack(
        rx.text(icon, font_size="18px"),
        rx.text(label, size="2", color="gray", weight="medium"),
        rx.spacer(),
        rx.switch(checked=state_val, on_change=handler, size="2"),
        align="center",
        width="100%",
        padding_x="1",
    )


def section_label(text: str) -> rx.Component:
    return rx.text(
        text,
        size="1",
        weight="bold",
        color="gray",
        text_transform="uppercase",
        letter_spacing="0.08em",
        margin_bottom="2",
    )


def status_badge(status: str) -> rx.Component:
    """Colour-coded badge using STATUS_META dict."""
    # We can't do dict lookup inside rx.cond chains easily, so we cascade
    def make_badge(s, label, color):
        return rx.cond(
            status == s,
            rx.badge(label, color_scheme=color, variant="soft", radius="full"),
            rx.fragment(),
        )

    return rx.fragment(
        make_badge("Pending_Script",    "⚙️  Scripting…",        "indigo"),
        make_badge("QA_Script",         "✋ Awaiting Approval",   "orange"),
        make_badge("Pending_Voice", "🎙️  Voiceover…",        "violet"),
        make_badge("Pending_Assets",    "📦 Fetching Assets…",    "blue"),
        make_badge("Pending_Render",    "🎬 Rendering…",          "purple"),
        make_badge("QA_Final",          "👁️  Final Check",        "amber"),
        make_badge("Ready_To_Publish",  "📡 Publishing…",         "teal"),
        make_badge("Published",         "✅ Published",            "green"),
        make_badge("Failed",            "❌ Failed",               "red"),
    )


def render_video_card(video: VideoModel) -> rx.Component:
    return rx.box(
        rx.vstack(
            # ── Card Header ──────────────────────────────────────────
            rx.hstack(
                rx.vstack(
                    rx.heading(video.topic, size="4", weight="bold"),
                    rx.hstack(
                        rx.badge(
                            video.account_id.replace("_", " ").title(),
                            color_scheme="gray",
                            variant="outline",
                            radius="full",
                            size="1",
                        ),
                        rx.text(f"ID #{video.id}", size="1", color="gray"),
                        rx.cond(
                            video.hook_score > 0,
                            rx.badge(
                                f"🎣 Hook: {video.hook_score}/10",
                                color_scheme=rx.cond(video.hook_score >= 7.5, "green", rx.cond(video.hook_score >= 5, "amber", "red")),
                                radius="full", size="1"
                            )
                        ),
                        rx.cond(
                            video.retention_estimate > 0,
                            rx.badge(
                                f"👁 Ret: {video.retention_estimate}%",
                                color_scheme="blue", radius="full", size="1"
                            )
                        ),
                        rx.cond(
                            video.api_cost_estimate > 0,
                            rx.badge(
                                f"💲{video.api_cost_estimate:.2f}",
                                color_scheme="grass", radius="full", size="1"
                            )
                        ),
                        rx.cond(
                            video.script_cost_estimate > 0,
                            rx.badge(
                                f"🧠 Script: ${video.script_cost_estimate:.2f}",
                                color_scheme="amber", radius="full", size="1"
                            )
                        ),
                        rx.cond(
                            video.voice_name != "",
                            rx.badge(
                                f"🎙 {video.voice_name}",
                                color_scheme="violet", radius="full", size="1"
                            )
                        ),
                        spacing="2",
                        align="center",
                    ),
                    align="start",
                    spacing="1",
                ),
                rx.spacer(),
                rx.vstack(
                    status_badge(video.status),
                    align="end",
                ),
                align="start",
                width="100%",
            ),

            # ── Pipeline progress stepper ─────────────────────────────
            rx.cond(
                (video.status != "Failed") & (video.status != "Published"),
                rx.progress(value=video.stage_pct, size="1", color_scheme="blue", width="100%"),
            ),

            rx.divider(margin_y="2"),

            # ── Failed state ─────────────────────────────────────────
            rx.cond(
                video.status == "Failed",
                rx.vstack(
                    rx.box(
                        rx.vstack(
                            rx.hstack(
                                rx.badge(video.error_code, color_scheme="red", size="1"),
                                rx.text(
                                    f"Attempt {video.error_attempt} · repeated {video.error_repeat_count}x · cost at error ${video.error_cost_snapshot:.2f}",
                                    size="1", color="gray",
                                ),
                                spacing="2", wrap="wrap",
                            ),
                            rx.text(video.error_message, size="2", color="tomato"),
                            align="start", spacing="2",
                        ),
                        background="var(--red-2)",
                        border="1px solid var(--red-5)",
                        border_radius="8px",
                        padding="3",
                        width="100%",
                    ),
                    rx.vstack(
                        rx.text_area(
                            placeholder="Optional note for AI (e.g. 'The X statistic is wrong — please verify before rewriting')",
                            on_change=lambda val: State.set_rejection_note(video.id, val),
                            width="100%",
                            rows="2",
                            size="2",
                        ),
                        rx.hstack(
                            rx.button(
                                "↺  Smart Retry",
                                color_scheme="blue",
                                variant="soft",
                                size="2",
                                title="Resumes from the furthest completed stage (saves API calls)",
                                on_click=lambda: State.retry_video(video.id),
                            ),
                            rx.button(
                                "↺  Full Restart",
                                color_scheme="gray",
                                variant="soft",
                                size="2",
                                title="Discards all progress and restarts from scripting",
                                on_click=lambda: State.retry_from_scratch(video.id),
                            ),
                            rx.button(
                                "🗑  Delete",
                                color_scheme="red",
                                variant="soft",
                                size="2",
                                on_click=lambda: State.delete_video(video.id),
                            ),
                            spacing="2",
                            wrap="wrap",
                        ),
                        align="start",
                        spacing="2",
                        width="100%",
                    ),
                    align="start",
                    spacing="3",
                    width="100%",
                ),
            ),

            # ── QA_Script: script review ─────────────────────────────
            rx.cond(
                video.status == "QA_Script",
                rx.vstack(
                    rx.text("Review the generated script below, then approve or send back with notes.", size="2", color="gray"),
                    rx.box(
                        rx.code_block(video.script, language="json", show_line_numbers=True),
                        width="100%",
                        max_height="360px",
                        overflow_y="auto",
                        border_radius="8px",
                        border="1px solid var(--gray-4)",
                    ),
                    rx.cond(
                        video.script_sources_list.length() > 0,
                        rx.vstack(
                            rx.text("📎 Sources", size="2", weight="bold", color="gray"),
                            rx.foreach(
                                video.script_sources_list,
                                lambda src: rx.link(src, href=src, is_external=True, color="blue", size="2"),
                            ),
                            align="start",
                            spacing="1",
                        ),
                    ),
                    # ── Rejection note + targeted send-back ──────────
                    rx.box(
                        rx.vstack(
                            rx.text("↩  Send Back for Rewrite", size="2", weight="bold", color="gray"),
                            rx.text_area(
                                placeholder="What needs fixing? e.g. 'The stat about X is wrong' or 'Hook is too generic — try a controversy angle'",
                                on_change=lambda val: State.set_rejection_note(video.id, val),
                                width="100%",
                                rows="3",
                                size="2",
                            ),
                            rx.button(
                                "↩  Send Back for Rewrite",
                                color_scheme="orange",
                                variant="soft",
                                size="2",
                                on_click=lambda: State.reject_to_script(video.id),
                            ),
                            align="start",
                            spacing="2",
                            width="100%",
                        ),
                        background="var(--orange-2)",
                        border="1px solid var(--orange-4)",
                        border_radius="8px",
                        padding="3",
                        width="100%",
                    ),
                    # ── Approve ──────────────────────────────────────
                    rx.hstack(
                        rx.button(
                            "✅  Approve Script",
                            color_scheme="green",
                            size="2",
                            on_click=lambda: State.approve_script(video.id),
                        ),
                        rx.button(
                            "🗑  Delete",
                            color_scheme="red",
                            variant="ghost",
                            size="2",
                            on_click=lambda: State.delete_video(video.id),
                        ),
                        spacing="2",
                    ),
                    align="start",
                    spacing="3",
                    width="100%",
                ),
            ),

            # ── QA_Final: approve for publishing ─────────────────────
            rx.cond(
                video.status == "QA_Final",
                rx.vstack(
                    rx.box(
                        rx.hstack(
                            rx.text("📁", font_size="18px"),
                            rx.text(video.final_path, size="2", font_family="monospace", color="gray"),
                            spacing="2",
                            align="center",
                        ),
                        background="var(--gray-2)",
                        border_radius="8px",
                        padding="3",
                        width="100%",
                    ),
                    rx.cond(
                        video.final_path != "",
                        rx.video(
                            src=f"/preview_{video.id}.mp4",
                            width="100%",
                            max_height="400px",
                        ),
                    ),
                    rx.callout(
                        "Final QA: confirm the first 3 seconds hook immediately, the voice matches the account, "
                        "effects feel justified, visuals match the narration, and cited comparisons appear as a chart.",
                        icon="info", color_scheme="blue", size="1", width="100%",
                    ),
                    rx.cond(
                        video.visual_qa_result != "",
                        rx.box(
                            rx.text("Automated visual review", size="2", weight="bold"),
                            rx.code(video.visual_qa_result, size="1"),
                            width="100%", padding="3", border_radius="8px",
                            background="var(--gray-2)",
                        ),
                    ),
                    rx.cond(
                        video.script_sources_list.length() > 0,
                        rx.vstack(
                            rx.text("📎 Sources", size="2", weight="bold", color="gray"),
                            rx.foreach(
                                video.script_sources_list,
                                lambda src: rx.link(src, href=src, is_external=True, color="blue", size="2"),
                            ),
                            align="start",
                            spacing="1",
                        ),
                    ),
                    # ── Targeted send-back with note ──────────────────
                    rx.box(
                        rx.vstack(
                            rx.text("↩  Send Back", size="2", weight="bold", color="gray"),
                            rx.text(
                                "Add a note, then pick how far back to send it. The note goes to the AI so it can fix the exact issue.",
                                size="1", color="gray",
                            ),
                            rx.text_area(
                                placeholder="e.g. 'Factual error: X statistic is wrong' / 'Weird cut after scene 3' / 'Re-record — pacing too slow'",
                                on_change=lambda val: State.set_rejection_note(video.id, val),
                                width="100%",
                                rows="3",
                                size="2",
                            ),
                            rx.hstack(
                                rx.button(
                                    "↩ Fix Script",
                                    color_scheme="red",
                                    variant="soft",
                                    size="2",
                                    title="Revises with GPT-5.6 Luna when configured, then regenerates downstream stages.",
                                    on_click=lambda: State.reject_to_script(video.id),
                                ),
                                rx.button(
                                    "↩ Re-record Voice",
                                    color_scheme="orange",
                                    variant="soft",
                                    size="2",
                                    title="Re-records voiceover only — skips scripting. Uses ElevenLabs.",
                                    on_click=lambda: State.reject_to_voiceover(video.id),
                                ),
                                rx.button(
                                    "↩ Replace Visuals",
                                    color_scheme="purple",
                                    variant="soft",
                                    size="2",
                                    title="Keeps the approved script and voice, excludes prior stock sources, then fetches and reviews new visuals.",
                                    on_click=lambda: State.reject_to_assets(video.id),
                                ),
                                rx.button(
                                    "↩ Re-render Only",
                                    color_scheme="blue",
                                    variant="soft",
                                    size="2",
                                    title="Re-runs FFmpeg only — free, no API calls.",
                                    on_click=lambda: State.reject_to_render(video.id),
                                ),
                                spacing="2",
                                wrap="wrap",
                            ),
                            align="start",
                            spacing="2",
                            width="100%",
                        ),
                        background="var(--amber-2)",
                        border="1px solid var(--amber-4)",
                        border_radius="8px",
                        padding="3",
                        width="100%",
                    ),
                    # ── Approve ──────────────────────────────────────
                    rx.hstack(
                        rx.button(
                            "📡  Approve & Publish",
                            color_scheme="green",
                            size="2",
                            on_click=lambda: State.approve_video(video.id),
                        ),
                        rx.button(
                            "🗑  Delete",
                            color_scheme="red",
                            variant="ghost",
                            size="2",
                            on_click=lambda: State.delete_video(video.id),
                        ),
                        spacing="2",
                    ),
                    align="start",
                    spacing="3",
                    width="100%",
                ),
            ),

            # ── In-progress: show only a delete option ────────────────
            rx.cond(
                (video.status != "Failed") &
                (video.status != "QA_Script") &
                (video.status != "QA_Final") &
                (video.status != "Published"),
                rx.hstack(
                    rx.spinner(size="2", color="blue"),
                    rx.text("Pipeline running…", size="2", color="gray"),
                    rx.spacer(),
                    rx.button(
                        "🗑",
                        color_scheme="red",
                        variant="ghost",
                        size="1",
                        on_click=lambda: State.delete_video(video.id),
                        title="Delete this video",
                    ),
                    align="center",
                    width="100%",
                ),
            ),

            # ── Published ─────────────────────────────────────────────
            rx.cond(
                video.status == "Published",
                rx.hstack(
                    rx.text("🎉 Video successfully published to all selected platforms.", size="2", color="green"),
                    rx.spacer(),
                    rx.button(
                        "🗑  Remove",
                        color_scheme="red",
                        variant="ghost",
                        size="1",
                        on_click=lambda: State.delete_video(video.id),
                    ),
                    align="center",
                    width="100%",
                ),
            ),

            spacing="2",
            align="stretch",
            width="100%",
        ),
        background="white",
        border="1px solid var(--gray-4)",
        border_radius="12px",
        padding="5",
        width="100%",
        box_shadow="0 1px 4px rgba(0,0,0,0.06)",
    )


# ─── PAGES ────────────────────────────────────────────────────────────────────

def pipeline_tab() -> rx.Component:
    return rx.vstack(
        # ── Create New Video Card ────────────────────────────────────
        rx.box(
            rx.vstack(
                rx.hstack(
                    rx.heading("Create New Video", size="5", weight="bold"),
                    rx.spacer(),
                    rx.cond(
                        State.is_generating,
                        rx.hstack(
                            rx.spinner(size="2"),
                            rx.text("Generating topics…", size="2", color="gray"),
                            spacing="2",
                            align="center",
                        ),
                    ),
                    align="center",
                    width="100%",
                ),

                # Topic + Account row
                rx.hstack(
                    rx.input(
                        placeholder="Topic (e.g. 'How the Alma Ata Declaration changed global health')",
                        on_change=State.set_new_topic,
                        value=State.new_topic,
                        flex="3",
                        size="3",
                    ),
                    rx.select(
                        ACCOUNT_IDS,
                        placeholder="Category",
                        on_change=State.set_new_category,
                        value=State.new_category,
                        flex="1",
                        size="3",
                    ),
                    rx.select(
                        ["1", "3", "5"],
                        placeholder="# Videos",
                        on_change=State.set_batch_size,
                        value=State.batch_size,
                        width="100px",
                        size="3",
                    ),
                    spacing="3",
                    width="100%",
                ),

                rx.divider(margin_y="1"),

                # Options in two columns
                rx.grid(
                    # Left column: Output options
                    rx.vstack(
                        section_label("Output Options"),
                        toggle_row("Night Mode (Auto-Approve)",  "🌙", State.night_mode,        State.set_night_mode),
                        toggle_row("Use Human Hook Intro",       "🎥", State.use_human_intro,   State.set_use_human_intro),
                        align="start",
                        spacing="2",
                        width="100%",
                    ),
                    # Right column: Publish targets (3x3 grid)
                    rx.vstack(
                        section_label("Publish To"),
                        rx.grid(
                            toggle_row("YouTube",   "▶️", State.post_yt, State.set_post_yt),
                            toggle_row("Instagram", "📸", State.post_ig, State.set_post_ig),
                            toggle_row("TikTok",    "🎵", State.post_tt, State.set_post_tt),
                            toggle_row("Snapchat",  "👻", State.post_snapchat, State.set_post_snapchat),
                            toggle_row("X (Twitter)","🐦", State.post_x, State.set_post_x),
                            toggle_row("Save Desk",  "💾", State.save_to_desktop, State.set_save_to_desktop),
                            columns="2",
                            spacing="4",
                            width="100%",
                        ),
                        align="start",
                        spacing="2",
                        width="100%",
                    ),
                    columns="2",
                    spacing="6",
                    width="100%",
                ),

                rx.divider(margin_y="1"),
                
                # Content Config
                rx.vstack(
                    section_label("Content Config"),
                    rx.grid(
                        rx.vstack(
                            rx.text("Custom CTA Text (Optional)", size="2", color="gray"),
                            rx.input(placeholder="Overrides default CTA...", on_change=State.set_cta_text, value=State.cta_text, size="2", width="100%"),
                            width="100%"
                        ),
                        rx.vstack(
                            rx.text("Affiliate URL (X only)", size="2", color="gray"),
                            rx.input(placeholder="https://...", on_change=State.set_affiliate_url, value=State.affiliate_url, size="2", width="100%"),
                            width="100%"
                        ),
                        rx.vstack(
                            rx.text("Compliance", size="2", color="gray"),
                            toggle_row("Is Sponsored", "🎯", State.is_sponsored, State.set_is_sponsored),
                            width="100%",
                            padding_top="4"
                        ),
                        columns="3",
                        spacing="4",
                        width="100%"
                    ),
                    width="100%"
                ),

                rx.button(
                    rx.cond(State.is_generating, "Generating Topics…", "🚀  Start Pipeline"),
                    on_click=State.add_video,
                    disabled=State.is_generating,
                    size="3",
                    color_scheme="blue",
                    width="100%",
                    margin_top="2",
                ),

                spacing="4",
                align="stretch",
                width="100%",
            ),
            background="white",
            border="1px solid var(--gray-4)",
            border_radius="12px",
            padding="6",
            width="100%",
            box_shadow="0 1px 4px rgba(0,0,0,0.06)",
        ),

        # ── Video Queue ──────────────────────────────────────────────
        rx.hstack(
            rx.heading("Video Queue", size="4", weight="bold"),
            rx.spacer(),
            rx.button(
                "↻  Refresh",
                on_click=State.load_videos,
                variant="soft",
                color_scheme="gray",
                size="2",
            ),
            align="center",
            width="100%",
            margin_top="2",
        ),

        rx.cond(
            State.videos.length() == 0,
            rx.box(
                rx.vstack(
                    rx.text("🎬", font_size="48px"),
                    rx.text("No videos in the queue yet.", size="3", color="gray", weight="medium"),
                    rx.text("Enter a topic above and click Start Pipeline to begin.", size="2", color="gray"),
                    align="center",
                    spacing="2",
                ),
                background="var(--gray-1)",
                border="1px dashed var(--gray-5)",
                border_radius="12px",
                padding="10",
                width="100%",
                text_align="center",
            ),
            rx.foreach(State.videos, render_video_card),
        ),

        spacing="4",
        align="stretch",
        width="100%",
    )


def intros_tab() -> rx.Component:
    return rx.box(
        rx.vstack(
            rx.heading("Manage Hook Intros", size="5", weight="bold"),
            rx.text(
                "Upload short 9:16 vertical videos of yourself to splice as hooks (e.g. 'Did you know…'). "
                "Leave blank to generate fully AI-directed videos.",
                size="2",
                color="gray",
            ),
            rx.divider(margin_y="1"),
            rx.hstack(
                rx.text("Account Category:", size="2", weight="medium"),
                rx.select(
                    ACCOUNT_IDS,
                    on_change=State.update_upload_account,
                    value=State.upload_account,
                    size="2",
                ),
                align="center",
                spacing="3",
            ),
            rx.upload(
                rx.vstack(
                    rx.text("🎥", font_size="32px"),
                    rx.text("Drop .mp4 files here or click to browse", size="2", weight="medium"),
                    rx.text("9:16 vertical, 2–3s hook clip (longer uploads are trimmed)", size="1", color="gray"),
                    align="center",
                    spacing="1",
                    padding="6",
                ),
                id="upload_intro",
                multiple=True,
                accept={"video/mp4": [".mp4"]},
                border="2px dashed var(--gray-5)",
                border_radius="10px",
                width="100%",
                background="var(--gray-1)",
            ),
            rx.button(
                "⬆️  Upload to Account",
                on_click=State.handle_upload(rx.upload_files(upload_id="upload_intro")),
                color_scheme="blue",
                size="2",
            ),
            rx.heading("Current Intros", size="3", margin_top="4"),
            rx.cond(
                State.intro_files.length() == 0,
                rx.text("No intros uploaded for this account yet.", size="2", color="gray"),
                rx.vstack(
                    rx.foreach(
                        State.intro_files,
                        lambda filename: rx.hstack(
                            rx.text("🎬", font_size="16px"),
                            rx.text(filename, size="2", flex="1"),
                            rx.button(
                                "Delete",
                                color_scheme="red",
                                variant="soft",
                                size="1",
                                on_click=lambda: State.delete_intro(filename),
                            ),
                            align="center",
                            spacing="3",
                            background="var(--gray-1)",
                            border_radius="8px",
                            padding_x="3",
                            padding_y="2",
                            width="100%",
                        ),
                    ),
                    spacing="2",
                    width="100%",
                ),
            ),
            spacing="4",
            align="start",
            width="100%",
        ),
        background="white",
        border="1px solid var(--gray-4)",
        border_radius="12px",
        padding="6",
        width="100%",
        box_shadow="0 1px 4px rgba(0,0,0,0.06)",
    )


def settings_tab() -> rx.Component:
    return rx.box(
        rx.vstack(
            rx.heading("Account Configuration", size="5", weight="bold"),
            rx.text("Settings are saved automatically and apply to all future videos for the selected account.", size="2", color="gray"),
            rx.divider(margin_y="1"),
            rx.grid(
                rx.vstack(
                    section_label("Account"),
                    rx.select(
                        ACCOUNT_IDS,
                        on_change=State.update_settings_account,
                        value=State.settings_account,
                        size="3",
                        width="100%",
                    ),
                    spacing="2",
                    width="100%",
                ),
                rx.vstack(
                    section_label("ElevenLabs Voiceover"),
                    rx.select(
                        list(POPULAR_VOICES.keys()),
                        on_change=State.save_voice_name,
                        value=State.selected_voice_name,
                        size="3",
                        width="100%",
                    ),
                    spacing="2",
                    width="100%",
                ),
                columns="2",
                spacing="6",
                width="100%",
            ),
            rx.divider(margin_y="2"),
            rx.grid(
                rx.vstack(
                    section_label("Default CTA Text"),
                    rx.input(on_change=State.set_default_cta_text, value=State.default_cta_text, size="2", width="100%"),
                    width="100%"
                ),
                rx.vstack(
                    section_label("Snapchat Ad Account ID"),
                    rx.input(on_change=State.set_snapchat_ad_account_id, value=State.snapchat_ad_account_id, size="2", width="100%"),
                    width="100%"
                ),
                rx.vstack(
                    section_label("X (Twitter) Handle"),
                    rx.input(on_change=State.set_x_handle, value=State.x_handle, size="2", width="100%"),
                    width="100%"
                ),
                columns="3",
                spacing="4",
                width="100%",
            ),
            rx.box(
                rx.hstack(
                    rx.text("ℹ️", font_size="16px"),
                    rx.text(
                        "Voice changes take effect on the next video in the queue. Already-processing voiceovers will use the previous setting.",
                        size="2",
                        color="gray",
                    ),
                    spacing="2",
                    align="start",
                ),
                background="var(--blue-2)",
                border="1px solid var(--blue-5)",
                border_radius="8px",
                padding="3",
                width="100%",
                margin_top="4",
            ),
            spacing="4",
            align="start",
            width="100%",
        ),
        background="white",
        border="1px solid var(--gray-4)",
        border_radius="12px",
        padding="6",
        width="100%",
        box_shadow="0 1px 4px rgba(0,0,0,0.06)",
    )

def compliance_tab() -> rx.Component:
    def format_compliance_row(v: VideoModel):
        return rx.table.row(
            rx.table.cell(v.topic, weight="bold"),
            rx.table.cell(v.compliance_metadata),
            rx.table.cell(rx.cond(v.is_sponsored, "✅ Yes", "No")),
            rx.table.cell(v.video_path),
        )

    # Filter to only Published videos
    published_videos = State.videos.to(list)  # Need to filter in reflex, or just show all
    # Reflex doesn't support complex filtering in foreach well, but we can display conditionally
    
    return rx.box(
        rx.vstack(
            rx.heading("Compliance Log", size="5", weight="bold"),
            rx.text("Audit trail of FTC and AI disclosures for published videos.", size="2", color="gray"),
            rx.divider(margin_y="1"),
            rx.box(
                rx.text(f"Audit log tracks C2PA/IPTC tags and burn-in overlays.", size="2", color="gray"),
                background="var(--blue-2)",
                border="1px solid var(--blue-5)",
                border_radius="8px",
                padding="3",
                width="100%",
            ),
            rx.table.root(
                rx.table.header(
                    rx.table.row(
                        rx.table.column_header_cell("Topic"),
                        rx.table.column_header_cell("Compliance Meta"),
                        rx.table.column_header_cell("Sponsored"),
                        rx.table.column_header_cell("File"),
                    ),
                ),
                rx.table.body(
                    rx.foreach(
                        State.videos,
                        lambda v: rx.cond(
                            (v.status == "Published") & (v.compliance_metadata != ""),
                            format_compliance_row(v),
                            rx.fragment()
                        )
                    )
                ),
                width="100%",
                variant="surface",
                size="2"
            ),
            spacing="4",
            align="start",
            width="100%",
        ),
        background="white",
        border="1px solid var(--gray-4)",
        border_radius="12px",
        padding="6",
        width="100%",
        box_shadow="0 1px 4px rgba(0,0,0,0.06)",
    )


def index() -> rx.Component:
    return rx.box(
        rx.container(
            rx.vstack(
                # ── Header ───────────────────────────────────────────
                rx.box(
                    rx.hstack(
                        rx.vstack(
                            rx.heading("🎬 Video Pipeline", size="8", weight="bold"),
                            rx.text("Automated short-form content generation & publishing", size="2", color="gray"),
                            spacing="1",
                            align="start",
                        ),
                        rx.spacer(),
                        rx.cond(
                            State.engine_online,
                            rx.box(
                                rx.hstack(
                                    rx.box(width="8px", height="8px", border_radius="50%", background="green", display="inline-block"),
                                    rx.text("Engine Running", size="2", color="green", weight="medium"),
                                    spacing="2",
                                    align="center",
                                ),
                                background="var(--green-2)",
                                border="1px solid var(--green-5)",
                                border_radius="full",
                                padding_x="3",
                                padding_y="1",
                            ),
                            rx.box(
                                rx.hstack(
                                    rx.box(width="8px", height="8px", border_radius="50%", background="red", display="inline-block"),
                                    rx.text("Engine Stopped — run Backend/main.py", size="2", color="red", weight="medium"),
                                    spacing="2",
                                    align="center",
                                ),
                                background="var(--red-2)",
                                border="1px solid var(--red-5)",
                                border_radius="full",
                                padding_x="3",
                                padding_y="1",
                            ),
                        ),
                        align="center",
                        width="100%",
                    ),
                    margin_bottom="6",
                ),

                # Invisible timer: refreshes the queue every 5 seconds
                rx.moment(interval=5000, on_change=State.tick, display="none"),

                # ── Tabs ─────────────────────────────────────────────
                rx.tabs.root(
                    rx.tabs.list(
                        rx.tabs.trigger("🚀 Pipeline", value="pipeline"),
                        rx.tabs.trigger("🎥 Intros", value="intros"),
                        rx.tabs.trigger("⚖️ Compliance", value="compliance"),
                        rx.tabs.trigger("⚙️ Settings", value="settings"),
                        size="2",
                        margin_bottom="4",
                    ),
                    rx.tabs.content(pipeline_tab(), value="pipeline"),
                    rx.tabs.content(intros_tab(), value="intros"),
                    rx.tabs.content(compliance_tab(), value="compliance"),
                    rx.tabs.content(settings_tab(), value="settings"),
                    default_value="pipeline",
                    width="100%",
                ),

                spacing="0",
                align="stretch",
                width="100%",
            ),
            max_width="860px",
            padding_x="4",
            padding_y="8",
        ),
        background="var(--gray-1)",
        min_height="100vh",
        on_mount=State.on_load,
    )


app = rx.App()
app.add_page(index)
