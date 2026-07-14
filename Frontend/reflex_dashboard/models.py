"""Typed display models for the dashboard (moved verbatim from state.py).

Reflex refuses to rx.foreach over untyped nested data (list[dict] → Any),
so raw JSON from the DB is coerced into these before reaching the UI.
"""
from pydantic import BaseModel


class ClaimSourceModel(BaseModel):
    name: str = ""
    url: str = ""

class ClaimModel(BaseModel):
    text: str = ""
    sources: list[ClaimSourceModel] = []

class ChartPointModel(BaseModel):
    label: str = ""
    value: float = 0.0

class DataPointModel(BaseModel):
    label: str = ""
    unit: str = ""
    points: list[ChartPointModel] = []

class ChartSpecModel(BaseModel):
    title: str = ""
    unit: str = ""
    points: list[ChartPointModel] = []

class ElementModel(BaseModel):
    kind: str = ""
    role: str = "primary"
    ref: str = ""
    src: str = ""
    candidates: list[str] = []
    realized: bool = False
    chart: ChartSpecModel = ChartSpecModel()

class BeatModel(BaseModel):
    order: int = 0
    section: str = ""
    hook_label: str = ""
    spoken_text: str = ""
    target_duration_sec: float = 0.0
    music_cue: str = ""
    elements: list[ElementModel] = []


def _strip_none(value):
    """Drop null JSON values so pydantic field defaults apply instead."""
    if isinstance(value, dict):
        return {k: _strip_none(v) for k, v in value.items() if v is not None}
    if isinstance(value, list):
        return [_strip_none(item) for item in value]
    return value

def _coerce(model_cls, items):
    """Best-effort dict → display-model conversion; one bad row never kills the page."""
    result = []
    for item in items or []:
        try:
            if isinstance(item, BaseModel):
                item = item.model_dump()
            result.append(model_cls.model_validate(_strip_none(item)))
        except Exception:
            continue
    return result