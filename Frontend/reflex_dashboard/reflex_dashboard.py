"""Dashboard entry point: page tabs and the Reflex app.

State + models live in state.py; reusable UI pieces in components.py.
"""
import reflex as rx

from .state import State, VideoModel, ACCOUNT_IDS
from .components import (
    section_label, render_video_card, long_form_creator, filler_short_creator,
)


# ─── PAGES ────────────────────────────────────────────────────────────────────

def pipeline_tab() -> rx.Component:
    return rx.vstack(
        # ── Long-Form Video Creator (shorts are derived from published beats) ──
        long_form_creator(),

        # ── Filler short (tucked away — legacy automated pipeline) ──
        filler_short_creator(),

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
                    rx.text("Create a long-form video above; derive shorts from its beats once published.", size="2", color="gray"),
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
                columns="1",
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
                columns="1",
                spacing="4",
                width="100%",
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