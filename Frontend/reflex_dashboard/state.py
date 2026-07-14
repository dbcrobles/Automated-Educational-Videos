"""Dashboard state: config constants, data models, and the Reflex State class.

PIPELINE_STAGES and STATUS_META live HERE and only here — later phases must
extend these dicts rather than defining new ones.
"""
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
from schemas.research_artifact import ResearchArtifact
from nodes.research.prompts import paste_normalize_prompt
from .longform_state import (
    LongFormQAMixin, ensure_storyboard_asset_link, parse_storyboard_beats,
)
from .final_qa_state import FinalQAMixin, final_qa_view, publish_blockers

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
    "Pending_Research", "QA_Research", "Pending_BeatScript",
    "QA_BeatScript", "Pending_Storyboard", "QA_Storyboard",
    "Pending_Script", "QA_Script", "Awaiting_Narration",
    "Pending_LongRender", "Pending_Assets", "Pending_Render",
    "QA_Final", "Ready_To_Publish", "Published"
]

STATUS_META = {
    "Pending_Research":  {"label": "Researching…",     "color": "cyan"},
    "QA_Research":       {"label": "Research QA",      "color": "blue"},
    "Pending_BeatScript":{"label": "Awaiting Beats",   "color": "indigo"},
    "QA_BeatScript":     {"label": "Beat Script QA",   "color": "orange"},
    "Pending_Storyboard":{"label": "Storyboard…",      "color": "indigo"},
    "QA_Storyboard":    {"label": "Storyboard QA",     "color": "orange"},
    "Awaiting_Narration":{"label": "Awaiting Narration","color": "teal"},
    "Pending_Script":    {"label": "Scripting…",      "color": "indigo"},
    "QA_Script":         {"label": "Awaiting Approval","color": "orange"},
    "Pending_Assets":    {"label": "Fetching Assets…", "color": "blue"},
    "Pending_Render":    {"label": "Rendering…",       "color": "purple"},
    "Pending_LongRender":{"label": "Long Render…",     "color": "purple"},
    "QA_Final":          {"label": "Final Check",      "color": "amber"},
    "Ready_To_Publish":  {"label": "Publishing…",      "color": "teal"},
    "Published":         {"label": "Published ✓",      "color": "green"},
    "Paused_Cost":       {"label": "Paused (Cost)",    "color": "yellow"},
    "Failed":            {"label": "Failed",            "color": "red"},
}

class SourceLinkModel(BaseModel):
    label: str
    href: str
    role: str = "supporting"

class NarrationBeatModel(BaseModel):
    order: int
    spoken_text: str

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
    research_thesis: str = ""
    core_thesis: str = ""
    research_as_of: str = ""
    core_sources: list[SourceLinkModel] = []
    readable_sources: list[SourceLinkModel] = []
    currentness_warnings: list[str] = []
    video_format: str = "short"
    artifact_origin: str = ""
    artifact_claims: list[dict] = []
    artifact_data_points: list[dict] = []
    use_degraded_model: bool = False
    beat_script_json: str = ""
    beat_script_beats: list[dict] = []
    beat_script_title: str = ""
    beat_script_duration: float = 0.0
    beats_json_str: str = ""
    storyboard_beats: list[dict] = []
    narration_beats: list[NarrationBeatModel] = []
    citation_issues: list[dict] = []
    citation_unresolved: int = 0
    citation_checked: bool = False
    disclosure_altered: bool = False
    disclosure_ai: bool = False
    disclosure_sources: bool = False
    disclosure_disclaimer: bool = False

class BatchSplitOutput(BaseModel):
    sub_topics: list[str]

class State(LongFormQAMixin, FinalQAMixin, rx.State):
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
    narration_video_id: int = 0

    # Account Settings
    settings_account: str = "personal_finance"
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

    # Long-form creation fields
    long_form_topic: str = ""
    research_mode: str = "automated"  # "automated" or "paste"
    deep_research_paste: str = ""
    is_processing_paste: bool = False

    @rx.event
    def set_long_form_topic(self, val: str):
        self.long_form_topic = val

    @rx.event
    def set_research_mode(self, val: str):
        self.research_mode = val

    @rx.event
    def set_deep_research_paste(self, val: str):
        self.deep_research_paste = val

    def add_long_form_video(self):
        """Create a long-form video row — automated path queues for Node 0."""
        if not self.long_form_topic:
            return
        conn = database.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO videos (topic, account_id, format, status) VALUES (?, ?, 'long', 'Pending_Research')",
            (self.long_form_topic, self.new_category))
        conn.commit()
        conn.close()
        self.long_form_topic = ""
        self.load_videos()

    def paste_deep_research(self):
        """Paste path: one Gemini call normalizes the export into a ResearchArtifact."""
        if not self.long_form_topic or not self.deep_research_paste:
            return
        self.is_processing_paste = True
        yield
        try:
            api_key = os.environ.get("GEMINI_API_KEY")
            client = genai.Client(api_key=api_key)
            response = client.models.generate_content(
                model="gemini-3.5-flash",
                contents=paste_normalize_prompt(self.long_form_topic, self.deep_research_paste),
                config=genai.types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=ResearchArtifact,
                    temperature=0.2,
                ),
            )
            artifact = ResearchArtifact.model_validate_json(response.text)
            conn = database.get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO videos (topic, account_id, format, status, research_artifact) "
                "VALUES (?, ?, 'long', 'QA_Research', ?)",
                (self.long_form_topic, self.new_category, artifact.model_dump_json()))
            video_id = cursor.lastrowid
            conn.commit()
            conn.close()
            database.log_cost(video_id, 0.02, 'research',
                              provider='google', model='gemini-3.5-flash')
        except Exception as e:
            print(f"Paste normalization failed: {e}")
        self.long_form_topic = ""
        self.deep_research_paste = ""
        self.is_processing_paste = False
        self.load_videos()

    def approve_research(self, video_id: int):
        database.update_video(video_id, {'status': 'Pending_BeatScript'})
        self.load_videos()

    def rerun_research(self, video_id: int):
        database.update_video(video_id, {
            'status': 'Pending_Research', 'error_message': None,
            'research_dossier': None, 'research_artifact': None,
        })
        self.load_videos()

    def repaste_research(self, video_id: int):
        """Clear the artifact so the card shows the paste form again."""
        database.update_video(video_id, {
            'research_artifact': None, 'error_message': None,
        })
        self.load_videos()

    def cost_continue(self, video_id: int):
        database.update_video(video_id, {'status': 'Pending_Research', 'error_message': None})
        self.load_videos()

    def cost_degrade(self, video_id: int):
        database.update_video(video_id, {
            'status': 'Pending_Research', 'error_message': None,
            'use_degraded_model': 1})
        self.load_videos()

    def cost_stop(self, video_id: int):
        """Keep what's built — leave Paused_Cost status, just clear the error message."""
        database.update_video(video_id, {'error_message': None})
        self.load_videos()

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
        ensure_storyboard_asset_link()
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

        def _research_view(row):
            try:
                dossier = json.loads(row.get('research_dossier') or '{}')
            except (json.JSONDecodeError, TypeError):
                dossier = {}
            try:
                script_data = json.loads(row.get('script') or '{}')
            except (json.JSONDecodeError, TypeError):
                script_data = {}
            core = [SourceLinkModel(
                label=anchor.get('title') or anchor.get('url', 'Core article'),
                href=anchor.get('access_url') or anchor.get('url', ''), role='core')
                for anchor in dossier.get('anchors', []) if anchor.get('url')]
            readable = [SourceLinkModel(
                label=("Core article — " if item.get('role') == 'core' else "Supporting — ")
                      + (item.get('title') or item.get('url', 'Source')),
                href=item.get('access_url') or item.get('url', ''),
                role=item.get('role', 'supporting'))
                for item in script_data.get('source_details', [])
                if item.get('access_url') or item.get('url')]
            if not readable:
                readable = core + [SourceLinkModel(label=url, href=url)
                                   for url in json.loads(row.get('script_sources') or '[]')]
            return dossier, core, readable

        def _artifact_view(row):
            try:
                art = json.loads(row.get('research_artifact') or '{}')
            except (json.JSONDecodeError, TypeError):
                art = {}
            return (art.get('origin', ''), art.get('claims', []),
                    art.get('data_points', []))

        def _beat_script_view(row):
            try:
                bs = json.loads(row.get('beat_script') or '{}')
            except (json.JSONDecodeError, TypeError):
                bs = {}
            beats = bs.get('beats', [])
            duration = sum(b.get('target_duration_sec', 0) for b in beats)
            return bs.get('title', ''), beats, duration

        videos = []
        for row in rows_dicts:
            dossier, core, readable = _research_view(row)
            art_origin, art_claims, art_dps = _artifact_view(row)
            bs_title, bs_beats, bs_duration = _beat_script_view(row)
            realized_beats = parse_storyboard_beats(row.get("beats_json"))
            try:
                legacy_scenes = json.loads(row.get("script") or "{}").get("scenes", [])
            except (json.JSONDecodeError, TypeError):
                legacy_scenes = []
            narration_beats = realized_beats or bs_beats or [
                {"order": index, "spoken_text": scene.get("narration", "")}
                for index, scene in enumerate(legacy_scenes)]
            videos.append(VideoModel(
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
                research_thesis=dossier.get('thesis', ''),
                core_thesis=dossier.get('core_thesis', ''),
                research_as_of=dossier.get('as_of_date', ''),
                core_sources=core,
                readable_sources=readable,
                currentness_warnings=dossier.get('currentness_warnings', []),
                video_format=row.get('format') or 'short',
                artifact_origin=art_origin,
                artifact_claims=art_claims,
                artifact_data_points=art_dps,
                use_degraded_model=bool(row.get('use_degraded_model', 0)),
                beat_script_json=row.get('beat_script') or "",
                beat_script_beats=bs_beats,
                beat_script_title=bs_title,
                beat_script_duration=bs_duration,
                beats_json_str=row.get("beats_json") or "",
                storyboard_beats=realized_beats,
                narration_beats=narration_beats,
                **final_qa_view(row),
            ))
        self.videos = videos

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
        database.update_video(video_id, {'status': 'Awaiting_Narration'})
        self.load_videos()


    def approve_video(self, video_id: int):
        """Phase 7: long-form publish is gated on the citation check + checklist."""
        conn = database.get_connection()
        conn.row_factory = database.sqlite3.Row
        row = conn.execute(
            "SELECT format, citation_qa_result, compliance_metadata "
            "FROM videos WHERE id = ?", (video_id,)).fetchone()
        conn.close()
        if row and row['format'] == 'long':
            blockers = publish_blockers(dict(row))
            if blockers:
                return rx.toast.error("Cannot publish yet: " + "; ".join(blockers))
        database.update_video(video_id, {'status': 'Ready_To_Publish'})
        self.load_videos()

    def retry_video(self, video_id: int):
        """Smart retry: resume from the furthest stage that already has valid output on disk.

        Stage order (earliest → latest):
          Pending_Script → (QA_Script) → Awaiting_Narration → Pending_Assets
          → Pending_Render → (QA_Final) → Ready_To_Publish → Published

        Checks (most advanced first):
          1. voiceover_path exists on disk AND stock video assets exist on disk
             → resume at Pending_Render  (skips scripting, alignment, and asset fetch)
          2. voiceover_path exists on disk only
             → resume at Pending_Assets  (skips scripting and alignment)
          3. script JSON exists in DB (QA was approved)
             → resume at Awaiting_Narration  (skips scripting + QA)
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
            resume_status = 'Awaiting_Narration'

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
        # Reset the repair counter so a human note re-enables the auto-repair loop
        # (still bounded by the $0.25 soft / $0.55 hard script-cost caps).
        updates = {'status': resume_status, 'error_message': None, 'script_retry_count': 0}
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

    def refresh_research(self, video_id: int):
        """Discard only research, then rebuild it and rewrite using the editor's factual note."""
        note = str(self.rejection_notes.get(video_id, "")).strip()
        conn = database.get_connection()
        row = conn.execute("SELECT script FROM videos WHERE id = ?", (video_id,)).fetchone()
        conn.close()
        database.update_video(video_id, {
            'status': 'Pending_Script', 'error_message': None,
            'research_dossier': None,
            'storyboard_draft': row[0] if row and row[0] else None,
            'script_retry_count': 0,
            'qa_feedback': note or 'Refresh the research, verify what changed, then rewrite factual claims.',
        })
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
        self.default_cta_text = acc.get('default_cta', "")
        self.snapchat_ad_account_id = acc.get('snapchat_ad_account_id', "")
        self.x_handle = acc.get('x_handle', "")

    def update_settings_account(self, val: str):
        self.settings_account = val
        self.load_settings()

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
        with open(ACCOUNTS_CONFIG_PATH, 'r') as f:
            config = json.load(f)
        if self.settings_account in config:
            config[self.settings_account]['default_cta'] = self.default_cta_text
            config[self.settings_account]['snapchat_ad_account_id'] = self.snapchat_ad_account_id
            config[self.settings_account]['x_handle'] = self.x_handle
        with open(ACCOUNTS_CONFIG_PATH, 'w') as f:
            json.dump(config, f, indent=2)