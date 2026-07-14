# Phase 7 handoff — DeepSeek v4 Flash (boilerplate UI only)

All Phase 7 logic is already implemented and working. Your job is ONE new
Reflex component file plus a two-line wiring edit. Do not touch any other
file. Copy the visual style of `Frontend/reflex_dashboard/panels.py`
(gray boxes, `size="2"` text, soft buttons).

## Files you may read
- `Frontend/reflex_dashboard/panels.py` — style reference (box/button patterns)
- `Frontend/reflex_dashboard/final_qa_state.py` — the handlers you bind to
- `Frontend/reflex_dashboard/components.py` lines 359–475 — the QA_Final card

## 1. Create `Frontend/reflex_dashboard/final_qa_panel.py`

One exported function:

```python
import reflex as rx
from .state import State, VideoModel

def final_qa_panel(video: VideoModel) -> rx.Component:
    return rx.cond(
        (video.status == "QA_Final") & (video.video_format == "long"),
        rx.vstack(... sections below ..., align="start", spacing="3", width="100%"),
    )
```

### Section A — Citation gate box
- If `video.citation_checked == False`: an `rx.callout("Citation check running — publish unlocks when it finishes.", icon="info", color_scheme="blue", size="1", width="100%")`.
- Else if `video.citation_issues.length() == 0`: a green callout "Citation check passed — every beat is supported by the research."
- Else `rx.foreach(video.citation_issues, ...)` — each issue is a box showing:
  - `rx.badge(issue["issue_type"], color_scheme="red", size="1")` and
    `rx.text(f"Beat {issue['beat_order']}", size="1", color="gray")`
  - `rx.text(issue["message"], size="2")`
  - `rx.cond(issue["resolved"], rx.badge("resolved", color_scheme="green", size="1"),
      rx.button("Mark resolved (false positive)", size="1", variant="soft",
                color_scheme="green",
                on_click=lambda: State.resolve_citation_issue(video.id, issue["index"])))`
  - NOTE: inside `rx.foreach` the lambda receives `issue`; write it as
    `lambda issue: rx.box(...)`.

### Section B — Per-beat controls
`rx.foreach(video.storyboard_beats, lambda beat: rx.box(...))`, each box:
- `rx.text(f"Beat {beat['order']}", size="1", weight="bold", color="gray")`
- `rx.text(beat["spoken_text"], size="2")`
- Note box: `rx.text_area(placeholder="Note for this beat…", size="1", width="100%",
    on_change=lambda val: State.set_beat_note(video.id, beat["order"], val))`
- Edit box: `rx.text_area(default_value=beat["spoken_text"], size="1", width="100%",
    on_change=lambda val: State.set_beat_edit_text(video.id, beat["order"], val))`
- Warning line: `rx.text("⚠️ Changing spoken words requires re-recording the narration.",
    size="1", color="orange")`
- Buttons row (`rx.hstack`, spacing="2", wrap="wrap"):
  - "↺ Redo visuals for this beat" → `State.redo_beat_visuals(video.id, beat["order"])`
    (color_scheme="purple", variant="soft", size="1")
  - "✏️ Save text edit (re-record)" → `State.apply_beat_text_edit(video.id, beat["order"])`
    (color_scheme="orange", variant="soft", size="1")

### Section C — Tweak in Studio
An `rx.callout` (icon="info", blue, size="1", width="100%") with text:
"Tweak in Studio: edit Backend/assets/<id>/beats.json (cd Backend/remotion && npm
run dev), then re-render." — use `f"...assets/{video.id}/beats.json..."`.
Below it a button "🎬 Re-render from beats.json" →
`State.rerender_from_studio(video.id)` (color_scheme="blue", variant="soft", size="2").

### Section D — Disclosure checklist (all four required before publish)
A box (background="var(--amber-2)", border="1px solid var(--amber-4)",
border_radius="8px", padding="3", width="100%") titled
`rx.text("YouTube disclosure checklist — required", size="2", weight="bold")`,
then four rows, each `rx.hstack(rx.checkbox(checked=..., on_change=...), rx.text(label, size="2"))`:

| checked prop | on_change | label |
|---|---|---|
| `video.disclosure_altered` | `lambda checked: State.set_disclosure(video.id, "altered_content", checked)` | "No AI-generated realistic scenes or voices (altered content: no)" |
| `video.disclosure_ai` | `lambda checked: State.set_disclosure(video.id, "ai_assistance_disclosed", checked)` | "Description discloses AI assistance" |
| `video.disclosure_sources` | `lambda checked: State.set_disclosure(video.id, "sources_cited", checked)` | "Description lists the research sources" |
| `video.disclosure_disclaimer` | `lambda checked: State.set_disclosure(video.id, "medical_disclaimer", checked)` | "Education-not-advice disclaimer present" |

## 2. Wire into `Frontend/reflex_dashboard/components.py`
- Add to the existing panels import block (top of file):
  `from .final_qa_panel import final_qa_panel`
- Inside the QA_Final `rx.vstack` (around line 398), insert `final_qa_panel(video),`
  on its own line directly AFTER the line `source_links(video),`.

## Rules
- No new state vars, no new handlers — everything you need already exists in
  `final_qa_state.py` and `state.py` (`VideoModel` has `citation_issues`,
  `citation_unresolved`, `citation_checked`, `disclosure_*`, `storyboard_beats`).
- Keep the file under 200 lines. No TODOs, no placeholders.
- Verify with: `cd Frontend && python -c "import reflex_dashboard.final_qa_panel"`.