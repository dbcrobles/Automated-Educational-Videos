"""Prompt builders for the research passes (moved verbatim from node1_scripting.py)."""
import json
from datetime import date


def scout_prompt(topic, research_profile):
    return f"""
    Find 8-12 strong candidate sources for an evidence-led short video about "{topic}".
    Research profile: {json.dumps(research_profile)}
    Prefer direct, publicly accessible article/paper/report URLs over homepages or search pages.
    For each candidate give title, publisher, date, source type, exact URL, central finding,
    and why it adds a distinct mechanism, number, caveat, or human consequence.
    Do not claim a citation count unless a source explicitly supplies it. Do not invent URLs.
    """


def curate_prompt(topic, candidates):
    return f"""
    Select 1-2 anchor candidate IDs for a video about "{topic}" from ONLY the candidates below.
    Choose the smallest set that can carry the story. Prefer one empirical/official source and,
    when useful, one rigorous explanatory or investigative article. Judge authority, recency,
    direct relevance, accessible evidence, complementary viewpoint, and narrative usefulness.
    Return candidate IDs, not URLs.

    CANDIDATES:
    {json.dumps(candidates, indent=2)}
    """


def deep_research_prompt(topic, anchor_urls, research_profile, access_instruction):
    return f"""
    Deeply analyze these anchor articles for an evidence-led video about "{topic}":
    {json.dumps(anchor_urls)}

    Today is {date.today().isoformat()}. Research profile: {json.dumps(research_profile)}
    {access_instruction} Then find 2-4 related sources that corroborate, update,
    challenge, or humanize the anchor findings. Build 6-10 atomic evidence claims. Every claim must
    include its exact source URL, population/geography, date/period, caveat, and numeric value/unit
     when applicable. Mark a number chart-worthy only when the denominator, unit, and context are clear.
     For every chart-worthy comparison or time series, fill `chart_points` with 2-6 exact, non-negative,
     consistently-unitized values stated by that source and put their shared unit in `chart_unit`. `unit`
     describes `numeric_value` and may differ from `chart_unit` (for example, a 51 percent headline whose
     chart points are PHP amounts). Otherwise set `chart_recommended` false, `chart_unit` null, and use [].
    This is the core-reading pass. Fill all source metadata. Mark old evidence historical/dated_context,
    and mark mutable claims uncertain/dated_context unless this pass verifies they are latest available.
    Use `core` for anchor evidence and an appropriate role for related evidence. Surface disagreements
    and unknowns. Do not infer a number that no retrieved source states.
    Preserve the supplied anchors exactly in `anchors`.
    """


def paste_normalize_prompt(topic, pasted_text):
    return f"""
    Convert the following Gemini Deep Research export about "{topic}" into a structured
    research artifact. Extract every distinct factual claim and link it to its source.
    For each claim, include the source name, URL, and a short paraphrase (no long quotes).
    Identify numeric data points suitable for charting — each needs a label, unit, 2-6
    chart points (label + value), source URL, and an optional note/caveat.
    Set origin to "manual_deep_research" and include today's date as as_of_date.
    Put any tensions, unknowns, or currentness cautions in the notes field.

    DEEP RESEARCH EXPORT:
    {pasted_text[:50000]}
    """


def currentness_audit_prompt(topic, dossier):
    return f"""
    Today is {date.today().isoformat()}. Audit this research dossier about "{topic}" for currentness:
    {json.dumps(dossier, indent=2)}

    Preserve the anchor articles and summarize their own contribution in `core_thesis`. Then use Google
    Search to expand and update the thesis. For every mutable claim—rates, prices, benefits, coverage,
    laws, policies, office-holders, institutional practices, and statements that something still happens—
    search explicitly for what changed AFTER its source/data period. Prefer the newest primary official
    source; rigorous reporting may explain it. A newer implementation, increase, repeal, or methodology
    makes the old claim `superseded` and `do_not_use`; retain it only as dated history and add a separate
    replacement claim. If no update can be verified, mark it `uncertain` and `dated_context`, never current.

    `current_fact` is allowed only with `latest_available`. Historical evidence must name its period when
    narrated. Fill source title, publisher, publication date, canonical source URL, and access URL. Keep the
    core evidence distinct with evidence_role `core`; classify expansion as update/context/counterpoint.
    Make `thesis` the current synthesis, list plain-language warnings, and never infer missing numbers.
    """