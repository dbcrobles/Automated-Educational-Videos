"""Critical long-form QA state handlers shared by the dashboard State."""
import json
import os
import sys

import reflex as rx

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(os.path.join(PROJECT_ROOT, "Backend"))
from database import database


def ensure_storyboard_asset_link():
    """Expose canonical backend assets to Reflex without copying media files."""
    frontend_assets = os.path.join(PROJECT_ROOT, "Frontend", "assets")
    link_path = os.path.join(frontend_assets, "storyboards")
    os.makedirs(frontend_assets, exist_ok=True)
    if not os.path.lexists(link_path):
        os.symlink(os.path.join(PROJECT_ROOT, "Backend", "assets"), link_path)


def parse_storyboard_beats(raw_json):
    """Return storyboard beats without letting one bad checkpoint break the dashboard."""
    try:
        payload = json.loads(raw_json or "{}")
    except (json.JSONDecodeError, TypeError):
        return []
    beats = payload.get("beats", []) if isinstance(payload, dict) else []
    return beats if isinstance(beats, list) else []


class LongFormQAMixin(rx.State, mixin=True):
    """Beat-script and storyboard events mixed into the main Reflex State."""

    def approve_beat_script(self, video_id: int):
        database.update_video(video_id, {"status": "Pending_Storyboard"})
        self.load_videos()

    def reject_beat_script(self, video_id: int):
        note = str(self.rejection_notes.get(video_id, "")).strip()
        updates = {
            "status": "Pending_BeatScript", "error_message": None,
            "script_retry_count": 0,
        }
        if note:
            updates["qa_feedback"] = note
        database.update_video(video_id, updates)
        self.rejection_notes = {
            key: value for key, value in self.rejection_notes.items() if key != video_id}
        self.load_videos()

    def approve_storyboard(self, video_id: int):
        database.update_video(video_id, {"status": "Awaiting_Narration"})
        self.load_videos()

    def reject_storyboard(self, video_id: int):
        note = str(self.rejection_notes.get(video_id, "")).strip()
        feedback = f"[VISUAL_REPLACEMENT] {note or 'Replace the rejected visual choices.'}"
        database.update_video(video_id, {
            "status": "Pending_Storyboard", "qa_feedback": feedback,
            "error_message": None,
        })
        self.rejection_notes = {
            key: value for key, value in self.rejection_notes.items() if key != video_id}
        self.load_videos()

    def select_broll_candidate(self, video_id: int, beat_order: int, candidate_path: str):
        """Persist a candidate path and its source ID to beats.json and the DB."""
        beats_path = os.path.join(
            PROJECT_ROOT, "Backend", "assets", str(video_id), "beats.json")
        try:
            with open(beats_path) as source:
                data = json.load(source)
            for beat in data.get("beats", []):
                if beat.get("order") != beat_order:
                    continue
                for element in beat.get("elements", []):
                    if (element.get("kind") == "broll"
                            and candidate_path in element.get("candidates", [])):
                        element["src"] = candidate_path
                        candidate_sources = element.get("candidate_sources", {})
                        if candidate_path in candidate_sources:
                            element["source_id"] = candidate_sources[candidate_path]
            with open(beats_path, "w") as destination:
                json.dump(data, destination, indent=2)
            database.update_video(video_id, {"beats_json": json.dumps(data)})
        except (OSError, json.JSONDecodeError) as error:
            print(f"select_broll_candidate failed: {error}")
        self.load_videos()