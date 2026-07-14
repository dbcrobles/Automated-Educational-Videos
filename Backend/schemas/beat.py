"""Beat — the stable interface between script, storyboard, Remotion, and shorts.

Storyboard, Remotion assembly, and shorts extraction consume beats and never
need to know whether one LLM call or several produced them. Lock this shape;
change generation strategy underneath it freely.

Layered visuals (Fireship-style): each beat carries an ordered element stack.
The single `primary` element is the background (a chart or b-roll); any number
of `overlay` elements (memes, callouts, stickers) sit on top with their own
timing, position, and animation preset. The script LLM emits the primary plus
at most one or two obvious overlays; the storyboard phase and the owner (via
Remotion Studio editing the per-video beats.json props file) enrich the rest.
"""

from typing import Literal, Optional
from pydantic import BaseModel, Field, model_validator

Position = Literal[
    "full", "lower_third", "upper_third", "center",
    "top_left", "top_right", "bottom_left", "bottom_right",
]


class ElementCue(BaseModel):
    """One visual layer inside a beat.

    This is the *request*; realized values (downloaded file paths, final chart
    specs) are added by the storyboard phase into assets/{id}/beats.json,
    which is the single source of truth Remotion renders from.
    """
    kind: Literal["chart", "broll", "image", "meme", "text_callout", "sticker", "custom"]
    role: Literal["primary", "overlay"] = "primary"
    ref: Optional[str] = None          # DataPoint.id in the research artifact (charts)
    description: Optional[str] = None  # search / creation description (b-roll, memes, ...)
    start_offset_sec: float = Field(default=0.0, ge=0)   # relative to beat start
    duration_sec: Optional[float] = None                 # None = until beat end
    position: Position = "full"
    animation: Optional[str] = None    # preset name defined in the Remotion project

    @model_validator(mode="after")
    def _needs_ref_or_description(self):
        if self.kind == "chart" and not self.ref:
            raise ValueError("chart elements must set ref to a DataPoint.id")
        if self.kind != "chart" and not (self.description or self.ref):
            raise ValueError(f"{self.kind} elements need a description")
        return self


class Beat(BaseModel):
    section: Literal["intro", "discussion", "conclusion", "counterpoint"]
    order: int = Field(ge=0)
    spoken_text: str
    target_duration_sec: float = Field(ge=20, le=90)  # aim for ~60–65
    hook_label: str        # one-line standalone takeaway — makes the beat postable as a short
    music_cue: str         # e.g. "low tension, building"
    elements: list[ElementCue] = Field(min_length=1)

    @model_validator(mode="after")
    def _exactly_one_primary(self):
        if sum(1 for element in self.elements if element.role == "primary") != 1:
            raise ValueError("each beat needs exactly one primary element")
        return self

    @property
    def primary(self) -> ElementCue:
        return next(element for element in self.elements if element.role == "primary")

    @property
    def overlays(self) -> list[ElementCue]:
        return [element for element in self.elements if element.role == "overlay"]


class BeatScript(BaseModel):
    """The full beat-tagged script for one long-form video."""
    topic: str
    title: str
    beats: list[Beat] = Field(min_length=3)

    @model_validator(mode="after")
    def _has_required_sections(self):
        sections = {beat.section for beat in self.beats}
        missing = {"intro", "discussion", "conclusion"} - sections
        if missing:
            raise ValueError(f"beat script missing sections: {sorted(missing)}")
        return self

    @property
    def total_duration_sec(self) -> float:
        return sum(beat.target_duration_sec for beat in self.beats)