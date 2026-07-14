"""Reusable dashboard UI components (moved verbatim from reflex_dashboard.py)."""
import reflex as rx

from .state import State, VideoModel, ACCOUNT_IDS
from .panels import (
    research_artifact_panel, beat_script_panel, storyboard_panel, narration_panel,
)
from .final_qa_panel import final_qa_panel


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
        make_badge("Pending_Research",  "🔬 Researching…",       "cyan"),
        make_badge("QA_Research",       "🔎 Research QA",         "blue"),
        make_badge("Pending_BeatScript","🎵 Awaiting Beats",      "indigo"),
        make_badge("QA_BeatScript",     "📝 Beat Script QA",      "orange"),
        make_badge("Pending_Storyboard","🎬 Storyboard…",         "indigo"),
        make_badge("QA_Storyboard",   "🖼️ Storyboard QA",       "orange"),
        make_badge("Awaiting_Narration","🎙️ Awaiting Narration",  "teal"),
        make_badge("Pending_Script",    "⚙️  Scripting…",        "indigo"),
        make_badge("QA_Script",         "✋ Awaiting Approval",   "orange"),
        make_badge("Pending_Assets",    "📦 Fetching Assets…",    "blue"),
        make_badge("Pending_Render",    "🎬 Rendering…",          "purple"),
        make_badge("Pending_LongRender","🎬 Long Render…",       "purple"),
        make_badge("QA_Final",          "👁️  Final Check",        "amber"),
        make_badge("Ready_To_Publish",  "📡 Publishing…",         "teal"),
        make_badge("Published",         "✅ Published",            "green"),
        make_badge("Paused_Cost",       "⏸️ Paused (Cost)",       "yellow"),
        make_badge("Failed",            "❌ Failed",               "red"),
    )

def research_panel(video: VideoModel) -> rx.Component:
    return rx.cond(
        video.research_thesis != "",
        rx.box(
            rx.vstack(
                rx.hstack(
                    rx.text("🔎 Research QA", size="2", weight="bold"),
                    rx.spacer(),
                    rx.badge(f"Checked {video.research_as_of}", color_scheme="blue", size="1"),
                    width="100%", align="center",
                ),
                rx.cond(
                    video.core_thesis != "",
                    rx.vstack(
                        rx.text("Core article finding", size="1", weight="bold", color="gray"),
                        rx.text(video.core_thesis, size="2"),
                        align="start", spacing="1",
                    ),
                ),
                rx.vstack(
                    rx.text("Current synthesis", size="1", weight="bold", color="gray"),
                    rx.text(video.research_thesis, size="2"),
                    align="start", spacing="1",
                ),
                rx.cond(
                    video.core_sources.length() > 0,
                    rx.vstack(
                        rx.text("Core article(s)", size="1", weight="bold", color="gray"),
                        rx.foreach(video.core_sources, lambda source: rx.link(
                            source.label, href=source.href, is_external=True, color="blue", size="2")),
                        align="start", spacing="1",
                    ),
                ),
                rx.cond(
                    video.currentness_warnings.length() > 0,
                    rx.callout(
                        rx.vstack(
                            rx.text("Currentness cautions", size="2", weight="bold"),
                            rx.foreach(video.currentness_warnings,
                                       lambda warning: rx.text(f"• {warning}", size="1")),
                            align="start", spacing="1",
                        ),
                        icon="triangle-alert", color_scheme="amber", size="1", width="100%",
                    ),
                ),
                align="start", spacing="3", width="100%",
            ),
            background="var(--blue-2)", border="1px solid var(--blue-5)",
            border_radius="8px", padding="4", width="100%",
        ),
    )

def source_links(video: VideoModel) -> rx.Component:
    return rx.cond(
        video.readable_sources.length() > 0,
        rx.vstack(
            rx.text("📎 Sources", size="2", weight="bold", color="gray"),
            rx.foreach(video.readable_sources, lambda source: rx.link(
                source.label, href=source.href, is_external=True, color="blue", size="2")),
            align="start", spacing="1",
        ),
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
                    rx.cond(
                        video.error_code == "SCRIPT_COST_SOFT_LIMIT",
                        rx.callout(
                            "Paused for cost review — automatic repairs stopped at the $0.25 soft cap. "
                            "Add a note below and press Smart Retry to keep going (hard stop at $0.55).",
                            icon="info", color_scheme="amber", size="1", width="100%",
                        ),
                    ),
                    rx.box(
                        rx.vstack(
                            rx.hstack(
                                rx.badge(
                                    video.error_code,
                                    color_scheme=rx.cond(
                                        video.error_code == "SCRIPT_COST_SOFT_LIMIT", "amber", "red"),
                                    size="1",
                                ),
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
                    research_panel(video),
                    rx.box(
                        rx.code_block(video.script, language="json", show_line_numbers=True),
                        width="100%",
                        max_height="360px",
                        overflow_y="auto",
                        border_radius="8px",
                        border="1px solid var(--gray-4)",
                    ),
                    source_links(video),
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
                            rx.hstack(
                                rx.button(
                                    "↩ Rewrite Only",
                                    color_scheme="orange", variant="soft", size="2",
                                    title="Keeps the current research dossier.",
                                    on_click=lambda: State.reject_to_script(video.id),
                                ),
                                rx.button(
                                    "🔎 Refresh Research & Rewrite",
                                    color_scheme="blue", variant="soft", size="2",
                                    title="Re-runs core research and the currentness audit before rewriting.",
                                    on_click=lambda: State.refresh_research(video.id),
                                ),
                                wrap="wrap", spacing="2",
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
                    research_panel(video),
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
                    source_links(video),
                    final_qa_panel(video),
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
                                    "🔎 Refresh Research",
                                    color_scheme="blue", variant="soft", size="2",
                                    title="Re-runs research and currentness checks, then rewrites.",
                                    on_click=lambda: State.refresh_research(video.id),
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

            # ── QA_Research: review claims & data points (extracted to research_artifact_panel) ──
            research_artifact_panel(video),

            # ── QA_BeatScript: review beats (extracted to beat_script_panel) ──
            beat_script_panel(video),

            # ── QA_Storyboard: review storyboard (extracted to storyboard_panel) ──
            storyboard_panel(video),

            # ── Awaiting_Narration: owner recording script + upload ──
            narration_panel(video),

            # ── Paused_Cost: three choices ────────────────────────────
            rx.cond(
                video.status == "Paused_Cost",
                rx.vstack(
                    rx.callout(
                        video.error_message,
                        icon="triangle-alert", color_scheme="yellow", size="1", width="100%",
                    ),
                    rx.text("Choose how to proceed:", size="2", weight="bold"),
                    rx.hstack(
                        rx.button(
                            "▶️ Continue",
                            color_scheme="green", size="2",
                            on_click=lambda: State.cost_continue(video.id),
                        ),
                        rx.button(
                            "📉 Finish on cheaper model",
                            color_scheme="amber", variant="soft", size="2",
                            on_click=lambda: State.cost_degrade(video.id),
                        ),
                        rx.button(
                            "⏹️ Stop & Keep",
                            color_scheme="gray", variant="soft", size="2",
                            on_click=lambda: State.cost_stop(video.id),
                        ),
                        spacing="2", wrap="wrap",
                    ),
                    align="start", spacing="3", width="100%",
                ),
            ),

            # ── In-progress: show only a delete option ────────────────
            rx.cond(
                (video.status != "Failed") &
                (video.status != "QA_Script") &
                (video.status != "QA_Final") &
                (video.status != "QA_Research") &
                (video.status != "QA_BeatScript") &
                (video.status != "QA_Storyboard") &
                (video.status != "Awaiting_Narration") &
                (video.status != "Paused_Cost") &
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


def long_form_creator() -> rx.Component:
    """Long-form video creation: automated research or paste Deep Research export."""
    return rx.box(
        rx.vstack(
            rx.heading("Create Long-Form Video", size="5", weight="bold"),
            rx.text(
                "3–10 minute chart-driven landscape video. Choose automated research "
                "or paste a Gemini Deep Research export.",
                size="2", color="gray",
            ),
            rx.divider(margin_y="1"),
            rx.hstack(
                rx.input(
                    placeholder="Topic (e.g. 'Why healthcare costs vary 10x across countries')",
                    on_change=State.set_long_form_topic,
                    value=State.long_form_topic,
                    flex="3", size="3",
                ),
                rx.select(
                    ACCOUNT_IDS,
                    placeholder="Category",
                    on_change=State.set_new_category,
                    value=State.new_category,
                    flex="1", size="3",
                ),
                spacing="3", width="100%",
            ),
            rx.hstack(
                rx.text("Research mode:", size="2", weight="medium"),
                rx.select(
                    ["automated", "paste"],
                    on_change=State.set_research_mode,
                    value=State.research_mode,
                    size="2",
                ),
                spacing="3", align="center",
            ),
            rx.cond(
                State.research_mode == "paste",
                rx.vstack(
                    rx.text_area(
                        placeholder="Paste your Gemini Deep Research export here…",
                        on_change=State.set_deep_research_paste,
                        value=State.deep_research_paste,
                        width="100%", rows="6", size="2",
                    ),
                    rx.button(
                        rx.cond(State.is_processing_paste, "Normalizing…", "📋 Normalize & Create"),
                        on_click=State.paste_deep_research,
                        disabled=State.is_processing_paste,
                        color_scheme="blue", size="3", width="100%",
                    ),
                    align="start", spacing="2", width="100%",
                ),
                rx.button(
                    "🚀 Start Automated Research",
                    on_click=State.add_long_form_video,
                    color_scheme="blue", size="3", width="100%",
                ),
            ),
            spacing="4", align="stretch", width="100%",
        ),
        background="white",
        border="1px solid var(--gray-4)",
        border_radius="12px",
        padding="6",
        width="100%",
        box_shadow="0 1px 4px rgba(0,0,0,0.06)",
    )
