"""Research artifact — the stable output of the draft phase.

Both draft-phase paths normalize into this one shape:
  * Manual: the owner runs Gemini Deep Research in the Gemini app, exports,
    and pastes into the dashboard; a normalizer LLM call fills this schema.
  * Automated: the existing Gemini researcher in
    Backend/nodes/scripting/node1_scripting.py (_build_research_dossier)
    produces a ResearchDossier which is converted via from_dossier().

Downstream, the script phase grounds narration in `claims` and visualizes
`data_points`; ElementCue.ref (see beat.py) points at DataPoint.id.
"""

import re
from datetime import date
from typing import Literal
from pydantic import BaseModel, Field


class Source(BaseModel):
    name: str                 # publisher or article title
    url: str
    paraphrase: str = ""      # short paraphrase of what the source says — no long quotes


class Claim(BaseModel):
    id: str                   # stable slug, e.g. "claim_03_er_visit_cost"
    text: str
    sources: list[Source] = Field(min_length=1)


class ChartPoint(BaseModel):
    label: str
    value: float


class DataPoint(BaseModel):
    """A flagged numeric/comparative set suitable for charting."""
    id: str                   # referenced by ElementCue.ref
    label: str                # e.g. "ER visit cost: PH vs US vs AU"
    unit: str                 # shared unit across all points
    points: list[ChartPoint] = Field(min_length=2, max_length=6)
    source_url: str
    source_label: str = ""
    note: str = ""            # caveat / denominator / population context


class ResearchArtifact(BaseModel):
    topic: str
    title: str = ""
    origin: Literal["manual_deep_research", "automated_researcher"]
    as_of_date: str = ""      # ISO date the research was last verified
    claims: list[Claim] = Field(min_length=1)
    data_points: list[DataPoint] = Field(default_factory=list)
    notes: str = ""           # free-form research notes, tensions, warnings


def _slug(text, prefix, index):
    words = re.findall(r"[a-z0-9]+", str(text).lower())[:5]
    return f"{prefix}_{index:02d}_" + "_".join(words or ["item"])


def from_dossier(dossier: dict, topic: str) -> ResearchArtifact:
    """Convert the existing researcher's ResearchDossier into a ResearchArtifact.

    Evidence marked usage='do_not_use' by the currentness audit is dropped so
    downstream stages can never cite superseded facts.
    """
    ledger = [item for item in dossier.get("evidence_ledger", [])
              if item.get("usage") != "do_not_use"]

    claims, data_points = [], []
    for index, item in enumerate(ledger, 1):
        text = str(item.get("claim", "")).strip()
        if not text:
            continue
        claims.append(Claim(
            id=_slug(text, "claim", index),
            text=text,
            sources=[Source(
                name=item.get("source_title") or item.get("publisher") or "Source",
                url=item.get("source_url", ""),
                paraphrase=(item.get("currentness_note") or text)[:280],
            )],
        ))
        points = item.get("chart_points") or []
        if item.get("chart_recommended") and item.get("chart_unit") and 2 <= len(points) <= 6:
            data_points.append(DataPoint(
                id=_slug(text, "dp", len(data_points) + 1),
                label=text.split(".")[0][:90],
                unit=str(item["chart_unit"]),
                points=[ChartPoint(label=str(p.get("label", "")), value=float(p.get("value", 0)))
                        for p in points],
                source_url=item.get("source_url", ""),
                source_label=item.get("publisher") or "",
                note=item.get("caveat") or "",
            ))

    note_parts = [dossier.get("thesis", "")]
    note_parts += [f"Unknown/tension: {t}" for t in dossier.get("tensions_or_unknowns") or []]
    note_parts += [f"Currentness caution: {w}" for w in dossier.get("currentness_warnings") or []]

    return ResearchArtifact(
        topic=topic,
        title=str(dossier.get("thesis", ""))[:120],
        origin="automated_researcher",
        as_of_date=dossier.get("as_of_date") or date.today().isoformat(),
        claims=claims,
        data_points=data_points,
        notes="\n".join(part for part in note_parts if part),
    )