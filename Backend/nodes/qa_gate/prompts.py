"""Prompt text for the Node 5 citation-match gate (Phase 7)."""
import json


def citation_check_prompt(claims, data_points, beats):
    return f"""
    Compare every factual statement in these video narration beats against the research
    claims and data points below. Return only genuine factual issues, not style advice.
    Numbers, populations, denominators, comparisons, causal strength, and caveats in the
    spoken text must match the evidence exactly. A statement with no supporting claim or
    data point is an unsupported_claim. Evidence tied to a past year/period must not be
    spoken in present-tense wording that implies it is current.
    If every beat is fully supported, return an empty issues list.
    For each issue, set beat_order to the beat's "order" value and claim_id to the id of
    the closest matching claim ("" if none matches).

    CLAIMS:
    {json.dumps(claims, indent=2)}

    DATA POINTS:
    {json.dumps(data_points, indent=2)}

    NARRATION BEATS:
    {json.dumps(beats, indent=2)}
    """