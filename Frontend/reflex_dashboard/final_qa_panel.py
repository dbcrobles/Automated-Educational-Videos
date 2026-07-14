"""Phase 7 — QA_Final panel: citation gate, per-beat controls, studio tweak, disclosure checklist."""
import reflex as rx

from .state import State, VideoModel


def final_qa_panel(video: VideoModel) -> rx.Component:
    """Citation gate, per-beat controls, studio tweak, and disclosure checklist."""
    return rx.cond(
        (video.status == "QA_Final") & (video.video_format == "long"),
        rx.vstack(
            # ── Section A — Citation gate box ────────────────────────
            rx.cond(
                ~video.citation_checked,
                rx.callout(
                    "Citation check running — publish unlocks when it finishes.",
                    icon="info", color_scheme="blue", size="1", width="100%",
                ),
                rx.cond(
                    video.citation_issues.length() == 0,
                    rx.callout(
                        "Citation check passed — every beat is supported by the research.",
                        icon="info", color_scheme="green", size="1", width="100%",
                    ),
                    rx.vstack(
                        rx.text("Citation Issues", size="2", weight="bold"),
                        rx.foreach(
                            video.citation_issues,
                            lambda issue: rx.box(
                                rx.vstack(
                                    rx.hstack(
                                        rx.badge(issue["issue_type"], color_scheme="red", size="1"),
                                        rx.text(f"Beat {issue['beat_order']}", size="1", color="gray"),
                                        spacing="2", align="center",
                                    ),
                                    rx.text(issue["message"], size="2"),
                                    rx.cond(
                                        issue["resolved"],
                                        rx.badge("resolved", color_scheme="green", size="1"),
                                        rx.button(
                                            "Mark resolved (false positive)",
                                            size="1", variant="soft", color_scheme="green",
                                            on_click=lambda: State.resolve_citation_issue(
                                                video.id, issue["index"]),
                                        ),
                                    ),
                                    align="start", spacing="2",
                                ),
                                background="var(--gray-1)", border_radius="6px",
                                padding="3", width="100%",
                            ),
                        ),
                        align="start", spacing="2", width="100%",
                    ),
                ),
            ),
            # ── Section B — Per-beat controls ────────────────────────
            rx.text("Per-Beat Controls", size="2", weight="bold"),
            rx.foreach(
                video.storyboard_beats,
                lambda beat: rx.box(
                    rx.vstack(
                        rx.text(f"Beat {beat['order']}", size="1", weight="bold", color="gray"),
                        rx.text(beat["spoken_text"], size="2"),
                        rx.text_area(
                            placeholder="Note for this beat…",
                            size="1", width="100%",
                            on_change=lambda val: State.set_beat_note(
                                video.id, beat["order"], val),
                        ),
                        rx.text_area(
                            default_value=beat["spoken_text"],
                            size="1", width="100%",
                            on_change=lambda val: State.set_beat_edit_text(
                                video.id, beat["order"], val),
                        ),
                        rx.text(
                            "⚠️ Changing spoken words requires re-recording the narration.",
                            size="1", color="orange",
                        ),
                        rx.hstack(
                            rx.button(
                                "↺ Redo visuals for this beat",
                                color_scheme="purple", variant="soft", size="1",
                                on_click=lambda: State.redo_beat_visuals(
                                    video.id, beat["order"]),
                            ),
                            rx.button(
                                "✏️ Save text edit (re-record)",
                                color_scheme="orange", variant="soft", size="1",
                                on_click=lambda: State.apply_beat_text_edit(
                                    video.id, beat["order"]),
                            ),
                            spacing="2", wrap="wrap",
                        ),
                        align="start", spacing="2",
                    ),
                    background="var(--gray-1)", border_radius="6px",
                    padding="3", width="100%",
                ),
            ),
            # ── Section C — Tweak in Studio ──────────────────────────
            rx.callout(
                f"Tweak in Studio: edit Backend/assets/{video.id}/beats.json "
                "(cd Backend/remotion && npm run dev), then re-render.",
                icon="info", color_scheme="blue", size="1", width="100%",
            ),
            rx.button(
                "🎬 Re-render from beats.json",
                color_scheme="blue", variant="soft", size="2",
                on_click=lambda: State.rerender_from_studio(video.id),
            ),
            # ── Section D — Disclosure checklist ─────────────────────
            rx.box(
                rx.vstack(
                    rx.text(
                        "YouTube disclosure checklist — required",
                        size="2", weight="bold",
                    ),
                    rx.hstack(
                        rx.checkbox(
                            checked=video.disclosure_altered,
                            on_change=lambda checked: State.set_disclosure(
                                video.id, "altered_content", checked),
                        ),
                        rx.text(
                            "No AI-generated realistic scenes or voices "
                            "(altered content: no)",
                            size="2",
                        ),
                        spacing="2", align="center", width="100%",
                    ),
                    rx.hstack(
                        rx.checkbox(
                            checked=video.disclosure_ai,
                            on_change=lambda checked: State.set_disclosure(
                                video.id, "ai_assistance_disclosed", checked),
                        ),
                        rx.text("Description discloses AI assistance", size="2"),
                        spacing="2", align="center", width="100%",
                    ),
                    rx.hstack(
                        rx.checkbox(
                            checked=video.disclosure_sources,
                            on_change=lambda checked: State.set_disclosure(
                                video.id, "sources_cited", checked),
                        ),
                        rx.text("Description lists the research sources", size="2"),
                        spacing="2", align="center", width="100%",
                    ),
                    rx.hstack(
                        rx.checkbox(
                            checked=video.disclosure_disclaimer,
                            on_change=lambda checked: State.set_disclosure(
                                video.id, "medical_disclaimer", checked),
                        ),
                        rx.text(
                            "Education-not-advice disclaimer present", size="2",
                        ),
                        spacing="2", align="center", width="100%",
                    ),
                    align="start", spacing="2", width="100%",
                ),
                background="var(--amber-2)",
                border="1px solid var(--amber-4)",
                border_radius="8px", padding="3", width="100%",
            ),
            align="start", spacing="3", width="100%",
        ),
    )