"""Phase 7 — QA_Final long-form state: beat reinjection, citation gate, disclosures."""
import json
import os
import sys

import reflex as rx

from .longform_state import PROJECT_ROOT

sys.path.append(os.path.join(PROJECT_ROOT, "Backend"))
from database import database

DISCLOSURE_LABELS = {
    "altered_content": "altered-content answered",
    "ai_assistance_disclosed": "AI assistance disclosed",
    "sources_cited": "sources cited",
    "medical_disclaimer": "medical disclaimer",
}


def _beats_json_path(video_id):
    return os.path.join(PROJECT_ROOT, "Backend", "assets", str(video_id), "beats.json")


def parse_citation(raw):
    """(issues-with-index, unresolved_count, checked). Empty column = not checked yet."""
    try:
        payload = json.loads(raw or "")
    except (json.JSONDecodeError, TypeError):
        return [], 0, False
    issues = payload.get("issues", []) if isinstance(payload, dict) else []
    for index, issue in enumerate(issues):
        issue["index"] = index
    return issues, sum(1 for issue in issues if not issue.get("resolved")), True


def parse_disclosure(raw_compliance):
    """Four checklist booleans out of the compliance_metadata JSON."""
    try:
        meta = json.loads(raw_compliance or "{}")
    except (json.JSONDecodeError, TypeError):
        meta = {}
    d = meta.get("disclosure", {}) if isinstance(meta, dict) else {}
    return {
        "altered_content": d.get("altered_content") in ("yes", "no"),
        "ai_assistance_disclosed": bool(d.get("ai_assistance_disclosed")),
        "sources_cited": bool(d.get("sources_cited")),
        "medical_disclaimer": bool(d.get("medical_disclaimer")),
    }


def final_qa_view(row):
    """VideoModel kwargs for the citation gate + disclosure checklist."""
    issues, unresolved, checked = parse_citation(row.get("citation_qa_result"))
    d = parse_disclosure(row.get("compliance_metadata"))
    return {
        "citation_issues": issues, "citation_unresolved": unresolved,
        "citation_checked": checked,
        "disclosure_altered": d["altered_content"],
        "disclosure_ai": d["ai_assistance_disclosed"],
        "disclosure_sources": d["sources_cited"],
        "disclosure_disclaimer": d["medical_disclaimer"],
    }


def publish_blockers(row):
    """Reasons a long-form video may NOT move to Ready_To_Publish."""
    _, unresolved, checked = parse_citation(row.get("citation_qa_result"))
    blockers = []
    if not checked:
        blockers.append("the citation check has not completed yet")
    elif unresolved:
        blockers.append(f"{unresolved} unresolved citation issue(s)")
    d = parse_disclosure(row.get("compliance_metadata"))
    missing = [label for key, label in DISCLOSURE_LABELS.items() if not d[key]]
    if missing:
        blockers.append("disclosure checklist incomplete: " + ", ".join(missing))
    return blockers


class FinalQAMixin(rx.State, mixin=True):
    """Per-beat QA_Final controls, citation resolution, and the disclosure checklist."""

    beat_notes: dict = {}       # "{video_id}:{order}" → note text
    beat_edit_texts: dict = {}  # "{video_id}:{order}" → revised spoken_text

    @rx.event
    def set_beat_note(self, video_id: int, beat_order: int, val: str):
        self.beat_notes[f"{video_id}:{beat_order}"] = val

    @rx.event
    def set_beat_edit_text(self, video_id: int, beat_order: int, val: str):
        self.beat_edit_texts[f"{video_id}:{beat_order}"] = val

    def redo_beat_visuals(self, video_id: int, beat_order: int):
        """Refetch ONE beat's b-roll (excluding prior sources), then full re-render."""
        note = str(self.beat_notes.get(f"{video_id}:{beat_order}", "")).strip()
        database.update_video(video_id, {
            "status": "Pending_Storyboard",
            "qa_feedback": f"[BEAT_VISUALS:{beat_order}] "
                           + (note or "Replace the visuals for this beat."),
            "error_message": None,
        })
        self.load_videos()
        return rx.toast.success(
            f"Beat {beat_order}: refetching visuals, then the whole video re-renders.")

    def apply_beat_text_edit(self, video_id: int, beat_order: int):
        """Change one beat's spoken_text — requires re-recording that narration."""
        new_text = str(self.beat_edit_texts.get(f"{video_id}:{beat_order}", "")).strip()
        if not new_text:
            return rx.toast.error("Edit the beat text first, then save.")
        beats_path = _beats_json_path(video_id)
        try:
            with open(beats_path) as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as error:
            return rx.toast.error(f"Could not read beats.json: {error}")
        if not any(b.get("order") == beat_order for b in data.get("beats", [])):
            return rx.toast.error(f"Beat {beat_order} not found in beats.json.")
        for beat in data["beats"]:
            if beat.get("order") == beat_order:
                beat["spoken_text"] = new_text
        with open(beats_path, "w") as f:
            json.dump(data, f, indent=2)

        updates = {
            "beats_json": json.dumps(data),
            "citation_qa_result": None,      # spoken words changed → re-run the gate
            "status": "Awaiting_Narration",  # re-record before the re-render
            "error_message": None,
        }
        row = database.fetch_videos_by_status("QA_Final", f"AND id = {int(video_id)}")
        if row and row[0].get("beat_script"):
            try:
                bs = json.loads(row[0]["beat_script"])
                for beat in bs.get("beats", []):
                    if beat.get("order") == beat_order:
                        beat["spoken_text"] = new_text
                updates["beat_script"] = json.dumps(bs)
            except (json.JSONDecodeError, TypeError):
                pass
        database.update_video(video_id, updates)
        self.load_videos()
        return rx.toast.warning(
            "Beat text updated. Changed spoken words require RE-RECORDING the "
            "narration — the video is back at Awaiting Narration.")

    def rerender_from_studio(self, video_id: int):
        """Sync owner edits from beats.json (Remotion Studio) and re-render."""
        beats_path = _beats_json_path(video_id)
        try:
            with open(beats_path) as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as error:
            return rx.toast.error(f"beats.json unreadable: {error}")
        database.update_video(video_id, {
            "beats_json": json.dumps(data),
            "status": "Pending_LongRender", "error_message": None,
        })
        self.load_videos()
        return rx.toast.success("Re-render queued from the current beats.json.")

    def resolve_citation_issue(self, video_id: int, issue_index: int):
        """Owner marks a flagged issue as a false positive."""
        conn = database.get_connection()
        row = conn.execute(
            "SELECT citation_qa_result FROM videos WHERE id = ?", (video_id,)).fetchone()
        conn.close()
        try:
            payload = json.loads(row[0] or "")
        except (TypeError, json.JSONDecodeError):
            return rx.toast.error("No citation result to update.")
        issues = payload.get("issues", [])
        if 0 <= issue_index < len(issues):
            issues[issue_index]["resolved"] = True
        database.update_video(video_id, {"citation_qa_result": json.dumps(payload)})
        self.load_videos()

    def set_disclosure(self, video_id: int, key: str, checked: bool):
        """Persist one checklist item inside compliance_metadata JSON."""
        if key not in DISCLOSURE_LABELS:
            return
        conn = database.get_connection()
        row = conn.execute(
            "SELECT compliance_metadata FROM videos WHERE id = ?", (video_id,)).fetchone()
        conn.close()
        try:
            meta = json.loads((row and row[0]) or "{}")
            if not isinstance(meta, dict):
                meta = {}
        except (TypeError, json.JSONDecodeError):
            meta = {}
        disclosure = meta.get("disclosure") or {}
        if key == "altered_content":
            # Checked = owner confirms NO AI-generated realistic scenes/voices.
            if checked:
                disclosure[key] = "no"
            else:
                disclosure.pop(key, None)
        else:
            disclosure[key] = bool(checked)
        meta["disclosure"] = disclosure
        database.update_video(video_id, {"compliance_metadata": json.dumps(meta)})
        self.load_videos()