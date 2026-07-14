"""Extracted QA panel components — kept here so components.py stays under 800 lines."""
import reflex as rx

from .state import State, VideoModel


def research_artifact_panel(video: VideoModel) -> rx.Component:
    """QA_Research review card."""
    return rx.cond(
        video.status == "QA_Research",
        rx.vstack(
            rx.hstack(
                rx.text("🔎 Research Artifact", size="2", weight="bold"),
                rx.spacer(),
                rx.cond(
                    video.artifact_origin != "",
                    rx.badge(video.artifact_origin, color_scheme="gray", size="1"),
                ),
                width="100%", align="center",
            ),
            rx.cond(
                video.artifact_claims.length() > 0,
                rx.vstack(
                    rx.text("Claims", size="1", weight="bold", color="gray"),
                    rx.foreach(video.artifact_claims, lambda claim: rx.box(
                        rx.vstack(
                            rx.text(claim["text"], size="2"),
                            rx.foreach(claim["sources"], lambda src: rx.link(
                                src["name"], href=src["url"], is_external=True,
                                color="blue", size="1")),
                            align="start", spacing="1",
                        ),
                        background="var(--gray-1)", border_radius="6px",
                        padding="3", width="100%",
                    )),
                    align="start", spacing="2", width="100%",
                ),
            ),
            rx.cond(
                video.artifact_data_points.length() > 0,
                rx.vstack(
                    rx.text("Data Points (chart-ready)", size="1", weight="bold", color="gray"),
                    rx.foreach(video.artifact_data_points, lambda dp: rx.box(
                        rx.vstack(
                            rx.text(dp["label"], size="2", weight="medium"),
                            rx.text(f"Unit: {dp['unit']}", size="1", color="gray"),
                            rx.foreach(dp["points"], lambda pt: rx.text(
                                f"  • {pt['label']}: {pt['value']}", size="1")),
                            align="start", spacing="1",
                        ),
                        background="var(--cyan-1)", border_radius="6px",
                        padding="3", width="100%",
                    )),
                    align="start", spacing="2", width="100%",
                ),
            ),
            rx.cond(
                video.artifact_claims.length() == 0,
                rx.vstack(
                    rx.text("No artifact yet — paste a Deep Research export below.", size="2", color="gray"),
                    rx.text_area(
                        placeholder="Paste your Gemini Deep Research export here…",
                        on_change=lambda val: State.set_deep_research_paste(val),
                        width="100%", rows="6", size="2",
                    ),
                    rx.button(
                        "📋 Normalize & Save",
                        on_click=State.paste_deep_research,
                        color_scheme="blue", size="2",
                    ),
                    align="start", spacing="2", width="100%",
                ),
            ),
            rx.divider(margin_y="1"),
            rx.hstack(
                rx.button(
                    "✅ Approve → Beat Script",
                    color_scheme="green", size="2",
                    on_click=lambda: State.approve_research(video.id),
                ),
                rx.cond(
                    video.artifact_origin == "automated_researcher",
                    rx.button(
                        "↺ Re-run Research",
                        color_scheme="blue", variant="soft", size="2",
                        on_click=lambda: State.rerun_research(video.id),
                    ),
                    rx.button(
                        "↺ Re-paste",
                        color_scheme="blue", variant="soft", size="2",
                        on_click=lambda: State.repaste_research(video.id),
                    ),
                ),
                rx.button(
                    "🗑 Delete",
                    color_scheme="red", variant="ghost", size="2",
                    on_click=lambda: State.delete_video(video.id),
                ),
                spacing="2", wrap="wrap",
            ),
            align="start", spacing="3", width="100%",
        ),
    )


def storyboard_panel(video: VideoModel) -> rx.Component:
    """QA_Storyboard review card with chart previews, b-roll selection, and approve/reject."""
    return rx.cond(
        video.status == "QA_Storyboard",
        rx.vstack(
            # ── Header ────────────────────────────────────────────
            rx.hstack(
                rx.text("🖼️ Storyboard Review", size="2", weight="bold"),
                rx.spacer(),
                rx.badge(
                    f"{video.storyboard_beats.length()} beats",
                    color_scheme="gray", size="1",
                ),
                width="100%", align="center",
            ),
            # ── Beats ────────────────────────────────────────────
            rx.foreach(video.storyboard_beats, lambda beat: rx.box(
                rx.vstack(
                    rx.text(beat["hook_label"], size="2", weight="bold", color="gray"),
                    rx.text(beat["spoken_text"], size="2"),
                    rx.foreach(beat["elements"], lambda el: rx.box(
                        rx.cond(
                            el["kind"] == "chart",
                            rx.vstack(
                                rx.text(f"📊 {el['chart']['title']}", size="2", weight="medium"),
                                rx.text(f"Unit: {el['chart']['unit']}", size="1", color="gray"),
                                rx.foreach(el["chart"]["points"], lambda pt: rx.text(
                                    f"  • {pt['label']}: {pt['value']}", size="1")),
                                align="start", spacing="1",
                            ),
                            rx.cond(
                                el["kind"] == "broll",
                                rx.vstack(
                                    rx.video(
                                        src=f"/storyboards/{video.id}/{el['src']}",
                                        controls=True,
                                        width="100%",
                                        max_height="240px",
                                    ),
                                    rx.radio(
                                        el["candidates"],
                                        value=el["src"],
                                        on_change=lambda candidate: State.select_broll_candidate(
                                            video.id, beat["order"], candidate),
                                        size="1",
                                    ),
                                    align="start", spacing="2",
                                ),
                                rx.cond(
                                    el["realized"] == False,
                                    rx.text(
                                        "Unrealized — add in Remotion Studio",
                                        size="1", color="gray", font_style="italic",
                                    ),
                                ),
                            ),
                        ),
                        background="var(--gray-1)", border_radius="6px",
                        padding="3", width="100%",
                    )),
                    align="start", spacing="2",
                ),
                background="var(--gray-1)", border_radius="6px",
                padding="3", width="100%",
            )),
            # ── Callout ──────────────────────────────────────────
            rx.callout(
                "Fine-tune overlays in Remotion Studio: cd Backend/remotion && npm run dev",
                icon="info", color_scheme="blue", size="1", width="100%",
            ),
            # ── Rejection note ───────────────────────────────────
            rx.box(
                rx.vstack(
                    rx.text("↩  Rejection Note", size="2", weight="bold", color="gray"),
                    rx.text_area(
                        placeholder="What needs fixing? e.g. 'Chart data is wrong' or 'Replace this b-roll clip'",
                        on_change=lambda val: State.set_rejection_note(video.id, val),
                        width="100%", rows="3", size="2",
                    ),
                    align="start", spacing="2", width="100%",
                ),
                background="var(--orange-2)",
                border="1px solid var(--orange-4)",
                border_radius="8px", padding="3", width="100%",
            ),
            # ── Action buttons ───────────────────────────────────
            rx.hstack(
                rx.button(
                    "✅ Approve → Narration",
                    color_scheme="green", size="2",
                    on_click=lambda: State.approve_storyboard(video.id),
                ),
                rx.button(
                    "↺ Refetch Visuals",
                    color_scheme="orange", variant="soft", size="2",
                    on_click=lambda: State.reject_storyboard(video.id),
                ),
                rx.button(
                    "🗑 Delete",
                    color_scheme="red", variant="ghost", size="2",
                    on_click=lambda: State.delete_video(video.id),
                ),
                spacing="2", wrap="wrap",
            ),
            align="start", spacing="3", width="100%",
        ),
    )


def beat_script_panel(video: VideoModel) -> rx.Component:
    """QA_BeatScript review card."""
    return rx.cond(
        video.status == "QA_BeatScript",
        rx.vstack(
            rx.hstack(
                rx.text("📝 Beat Script Review", size="2", weight="bold"),
                rx.spacer(),
                rx.cond(
                    video.beat_script_duration > 0,
                    rx.badge(
                        f"⏱ {video.beat_script_duration:.0f}s · {video.beat_script_beats.length()} beats",
                        color_scheme="gray", size="1",
                    ),
                ),
                width="100%", align="center",
            ),
            rx.cond(
                video.beat_script_title != "",
                rx.text(video.beat_script_title, size="3", weight="medium"),
            ),
            rx.foreach(video.beat_script_beats, lambda beat: rx.box(
                rx.vstack(
                    rx.hstack(
                        rx.badge(
                            beat["section"],
                            color_scheme=rx.cond(
                                beat["section"] == "intro", "cyan",
                                rx.cond(beat["section"] == "discussion", "blue", "teal")),
                            size="1",
                        ),
                        rx.text(f"Beat {beat['order']} · {beat['target_duration_sec']:.0f}s", size="1", color="gray"),
                        spacing="2", align="center",
                    ),
                    rx.text(beat["hook_label"], size="2", weight="bold", color="gray"),
                    rx.text(beat["spoken_text"], size="2"),
                    rx.hstack(
                        rx.text(f"🎵 {beat['music_cue']}", size="1", color="gray"),
                        rx.spacer(),
                        rx.foreach(beat["elements"], lambda el: rx.badge(
                            rx.cond(el["role"] == "primary", "🎯 ", "📎 ")
                            + el["kind"]
                            + rx.cond(el["kind"] == "chart", f" → {el['ref']}", ""),
                            color_scheme=rx.cond(el["role"] == "primary", "blue", "gray"),
                            variant="soft", size="1",
                        )),
                        spacing="1", wrap="wrap", align="center", width="100%",
                    ),
                    align="start", spacing="1",
                ),
                background="var(--gray-1)", border_radius="6px",
                padding="3", width="100%",
            )),
            rx.box(
                rx.vstack(
                    rx.text("↩  Rewrite with note", size="2", weight="bold", color="gray"),
                    rx.text_area(
                        placeholder="What needs fixing? e.g. 'Conclusion doesn't pay off the intro hook' or 'Beat 3 word count is too high'",
                        on_change=lambda val: State.set_rejection_note(video.id, val),
                        width="100%", rows="3", size="2",
                    ),
                    rx.button(
                        "↩ Rewrite Beats",
                        color_scheme="orange", variant="soft", size="2",
                        on_click=lambda: State.reject_beat_script(video.id),
                    ),
                    align="start", spacing="2", width="100%",
                ),
                background="var(--orange-2)",
                border="1px solid var(--orange-4)",
                border_radius="8px", padding="3", width="100%",
            ),
            rx.hstack(
                rx.button(
                    "✅ Approve → Storyboard",
                    color_scheme="green", size="2",
                    on_click=lambda: State.approve_beat_script(video.id),
                ),
                rx.button(
                    "🗑 Delete",
                    color_scheme="red", variant="ghost", size="2",
                    on_click=lambda: State.delete_video(video.id),
                ),
                spacing="2",
            ),
            align="start", spacing="3", width="100%",
        ),
    )