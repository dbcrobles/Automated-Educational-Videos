"""Shared pipeline contracts.

These schemas are the stable interfaces between pipeline stages:
  * ResearchArtifact — output of the draft phase (manual paste or automated researcher).
  * Beat / BeatScript — output of the script phase; consumed by storyboard,
    Remotion assembly, and shorts extraction.

Phase briefs (docs/briefs/) must satisfy these shapes; change them only with
an explicit architecture decision.
"""

from .research_artifact import (
    ChartPoint,
    Claim,
    DataPoint,
    ResearchArtifact,
    Source,
    from_dossier,
)
from .beat import Beat, BeatScript, ElementCue

__all__ = [
    "ChartPoint",
    "Claim",
    "DataPoint",
    "ResearchArtifact",
    "Source",
    "from_dossier",
    "Beat",
    "BeatScript",
    "ElementCue",
]